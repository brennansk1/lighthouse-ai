"""lighthouse-supervisor: long-lived process that owns the control plane.

Sprint 1 scope (per design Sprint 1 deliverables):
  * Opens all 5 SQLite DBs with PRAGMAs, runs migrations.
  * Boots FastAPI on 127.0.0.1:8765 via uvicorn.
  * Writes a PID file and a 'running' supervisor_state row.
  * Handles SIGTERM/SIGINT gracefully (drains uvicorn, marks state).
  * Resource watchdog (§19.4) STUB — real thresholds in later sprints.

Pause/resume (§19.2):
  Soft pause sets supervisor_state.status='paused_soft'; the supervisor stops
  scheduling new jobs (no scheduler yet in Sprint 1, so this is a flag toggle).
  Hard pause sets 'paused_hard' and drains; in Sprint 1 we just toggle status.

The CLI talks to a running supervisor over the control plane (HTTP). Process
lifecycle (start/stop) is delegated to launchd/systemd.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import structlog
import uvicorn

from .controlplane import create_app
from .governor.scheduler_gate import SchedulerGate, SchedulerGateConfig
from .paths import Paths, make_paths
from .persistence import open_db
from .schema import kinds_for, migrate_all
from .subconscious import ReflectionStore, SubconsciousEngine, stale_position_escalations

log = structlog.get_logger(__name__)

# Sentinel used by _start_backup_loop: distinguishes "caller passed None (fake
# runner for tests)" from "caller didn't pass runner (use production default)".
_SENTINEL: object = object()


class _BackupRunner(Protocol):
    """Structural type satisfied by :class:`~lighthouse_ai.backup.ResticBackup`.

    Using a Protocol (rather than a direct import) keeps the supervisor free of
    a hard dependency on the backup module at import time — it is only imported
    inside the loop thread.
    """

    def init(self, repo: str, passphrase: str
             ) -> subprocess.CompletedProcess[str]: ...

    def backup(
        self,
        paths: Sequence[Path],
        *,
        repo: str,
        passphrase: str | None = None,
    ) -> subprocess.CompletedProcess[str]: ...

    def check(self, repo: str, *, passphrase: str | None = None
              ) -> subprocess.CompletedProcess[str]: ...


def _set_state(paths: Paths, status: str, pid: int | None) -> None:
    conn = open_db(paths.state_db)
    try:
        conn.execute(
            """
            UPDATE supervisor_state
               SET status = ?, pid = ?, updated_at = datetime('now'),
                   started_at = COALESCE(started_at, datetime('now'))
             WHERE id = 1
            """,
            (status, pid),
        )
    finally:
        conn.close()


# --- global runtime pause (single source of truth) ------------------------
# `lighthouse pause` / the dashboard Pause button set supervisor_state.status to
# a paused_* value; EVERY 24/7 loop consults is_paused() each tick and skips its
# work while paused, so the user can reclaim the machine. Resume clears it.
PAUSED_STATUSES: frozenset[str] = frozenset({"paused_soft", "paused_hard"})


def runtime_status(paths: Paths) -> str:
    """Current supervisor status from state.db (``running`` if unknown/missing)."""
    if not paths.state_db.exists():
        return "running"
    try:
        conn = open_db(paths.state_db)
    except Exception:
        return "running"
    try:
        row = conn.execute(
            "SELECT status FROM supervisor_state WHERE id = 1"
        ).fetchone()
    except Exception:
        return "running"
    finally:
        conn.close()
    return str(row[0]) if row and row[0] else "running"


def is_paused(paths: Paths) -> bool:
    """True when the user has globally paused all background activity."""
    return runtime_status(paths) in PAUSED_STATUSES


def set_runtime_status(paths: Paths, status: str) -> str:
    """Set the supervisor status (used by CLI pause/resume + the API). Returns it."""
    conn = open_db(paths.state_db)
    try:
        conn.execute(
            "UPDATE supervisor_state SET status = ?, updated_at = datetime('now') "
            "WHERE id = 1",
            (status,),
        )
    finally:
        conn.close()
    return status


def _notify_web_alert(paths: Paths, alert: dict) -> None:
    """Best-effort: notify the user when a watched website fires a trigger.

    Reads the ``[ui]`` config (``notify_enabled`` + telegram token/chat id) and
    sends a plain one-liner so the user is told "your monitor changed" without
    opening the dashboard. No-op when disabled/unconfigured; never raises (the
    monitor sweep must stay alive regardless of notification outcome).
    """
    try:
        if not paths.config_file.exists():
            return
        try:
            import tomllib
        except ImportError:  # pragma: no cover
            import tomli as tomllib  # type: ignore
        with paths.config_file.open("rb") as fh:
            ui = tomllib.load(fh).get("ui", {})
        if not ui.get("notify_enabled", False):
            return
        from .notify import notify_monitor_alert

        name = alert.get("name") or alert.get("url") or "a website"
        reason = alert.get("reason") or alert.get("detail") or "changed"
        notify_monitor_alert(
            f"Website changed: {name}", str(reason),
            bot_token=str(ui.get("telegram_bot_token", "")),
            chat_id=str(ui.get("telegram_chat_id", "")),
            enabled=True,
        )
    except Exception:
        pass


def _write_pidfile(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid))


def _remove_pidfile(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _configure_logging(paths: Paths) -> None:
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    logfile = paths.logs_dir / "supervisor.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stderr), logging.FileHandler(logfile)],
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


def _start_subconscious_loop(paths: Paths, *, interval_s: float = 60.0) -> threading.Thread:
    """Start a daemon thread that calls SubconsciousEngine.tick() every interval_s seconds."""
    store = ReflectionStore(paths.reflections_db)
    gate_cfg = SchedulerGateConfig.from_config_file(paths.config_file)
    gate = SchedulerGate(gate_cfg)
    engine = SubconsciousEngine(
        store,
        gate=gate,
        escalation_producers=(lambda: stale_position_escalations(paths.positions_db),),
    )

    def _loop() -> None:
        while True:
            time.sleep(interval_s)
            if is_paused(paths):
                continue
            try:
                outcome = engine.tick()
                log.info(
                    "subconscious.tick",
                    result=outcome.result.value,
                    reflections_committed=outcome.reflections_committed,
                    escalations_committed=outcome.escalations_committed,
                )
            except Exception as exc:
                log.warning("subconscious.tick.error", exc=str(exc))

    thread = threading.Thread(target=_loop, daemon=True, name="subconscious-loop")
    thread.start()
    return thread


def _start_monitor_loop(paths: Paths, *, interval_s: float = 60.0) -> threading.Thread:
    """Daemon thread that sweeps due event-monitor sessions every interval_s.

    Heuristic salience only (no LLM, no gateway), so the sweep is cheap. It is
    still gated by the SchedulerGate: while the host is paused/offline we skip
    the tick entirely rather than poll the network.
    """
    from datetime import UTC, datetime

    from .governor.scheduler_gate import Policy
    from .modes.monitor_session import due_sessions, run_session_cycle
    from .modes.web_monitor_store import run_web_monitor_tick

    gate_cfg = SchedulerGateConfig.from_config_file(paths.config_file)
    gate = SchedulerGate(gate_cfg)

    def _web_monitor_fetch(url: str) -> str:
        """Production fetch for Watch v2: guarded, user-explicit host permitted.

        The page text is extracted from the guarded response. Offline-safe at the
        tick level — any error raised here is caught per-monitor inside
        ``run_web_monitor_tick`` and that monitor is skipped, never the sweep.
        """
        from .governor.egress_proxy import DEFAULT_ALLOWED_DOMAINS, extract_host
        from .ingest import extract_text
        from .net import guarded_get

        host = extract_host(url)
        allowed = frozenset(DEFAULT_ALLOWED_DOMAINS | {host}) if host else None
        resp = guarded_get(url, allowed_domains=allowed)
        ctype = dict(resp.headers or {}).get("content-type")
        return extract_text(resp.content or b"", ctype, None)

    def _loop() -> None:
        while True:
            time.sleep(interval_s)
            try:
                policy, _ = gate.policy()
                if is_paused(paths) or policy is Policy.PAUSED:
                    continue
                for s in due_sessions(paths.state_db):
                    try:
                        run_session_cycle(paths.state_db, s.id)
                    except Exception as exc:
                        log.warning("monitor.cycle.error", session=s.id, exc=str(exc))
                # Watch v2 web-monitor sweep. Wrapped so a failure here never
                # kills the loop; the tick is itself offline-safe (per-monitor
                # fetch errors are caught inside run_web_monitor_tick).
                try:
                    run_web_monitor_tick(
                        paths.state_db,
                        fetch=_web_monitor_fetch,
                        now=datetime.now(UTC).isoformat(timespec="seconds"),
                        alert_sink=lambda a: _notify_web_alert(paths, a),
                    )
                except Exception as exc:
                    log.warning("web_monitor.tick.error", exc=str(exc))
            except Exception as exc:
                log.warning("monitor.sweep.error", exc=str(exc))

    thread = threading.Thread(target=_loop, daemon=True, name="monitor-loop")
    thread.start()
    return thread


def _start_dispatch_loop(paths: Paths, *, interval_s: float = 5.0,
                         bus=None, offline: bool = False) -> threading.Thread:
    """Daemon thread that runs one queued job per tick.

    Mirrors the monitor loop: a single daemon thread, one job per tick, gated by
    the SchedulerGate so a paused host stops claiming work. RAM admission is
    inherited through ``Gateway.complete`` — no second queue here. Stuck
    ``running`` jobs from a previous process are re-queued once at startup.

    ``offline=True`` pins the loop to the stub gateway without probing Ollama —
    harnesses that promise "no model load" (soak, supervisor smoke) need stub
    dispatch even on a box where Ollama is reachable; otherwise they either run
    real models or starve behind the runtime RAM gate and never dispatch.

    ``bus`` is the FastAPI app's :class:`EventBus`; passing it through lets a job
    publish live ``job.step`` progress events to the dashboard's SSE stream as it
    runs (the persisted trace is written regardless).
    """
    from .dispatcher import (
        build_runtime_gateway,
        dispatch_once,
        reap_stuck_jobs,
        runtime_ram_ok,
    )
    from .governor.scheduler_gate import Policy

    gate_cfg = SchedulerGateConfig.from_config_file(paths.config_file)
    gate = SchedulerGate(gate_cfg)

    # Resolve a real Ollama gateway once (RAM-gated via Gateway.complete's
    # ollama_slot). Falls back to None — offline-deterministic stubs — when
    # Ollama is unreachable, so a paused/absent backend never fails jobs.
    gateway = None if offline else build_runtime_gateway(paths)
    log.info("dispatch.gateway",
             backend="offline-forced" if offline
             else ("ollama" if gateway is not None else "offline"))

    try:
        requeued = reap_stuck_jobs(paths.state_db, paths=paths)
        if requeued:
            log.info("dispatch.reaped", jobs=requeued)
    except Exception as exc:
        log.warning("dispatch.reap.error", exc=str(exc))

    def _loop() -> None:
        while True:
            time.sleep(interval_s)
            try:
                policy, _ = gate.policy()
                if is_paused(paths) or policy is Policy.PAUSED:
                    continue
                # Real-gateway runs need RAM headroom for a reasoning model;
                # if free RAM is below the floor, defer this tick (leave the job
                # queued) rather than thrash or silently degrade to the mock.
                # Offline (stub) dispatch is cheap and always proceeds.
                if gateway is not None and not runtime_ram_ok():
                    log.info("dispatch.deferred", reason="low_free_ram")
                    continue
                dispatch_once(paths, gateway=gateway, gate=gate, bus=bus)
            except Exception as exc:
                log.warning("dispatch.tick.error", exc=str(exc))

    thread = threading.Thread(target=_loop, daemon=True, name="dispatch-loop")
    thread.start()
    return thread


def _backup_tick(
    paths: Paths,
    *,
    repo: str,
    passphrase: str | None,
    runner: _BackupRunner | None,
) -> None:
    """One scheduled backup + integrity pass.

    Separated from the thread loop so tests can drive it directly with injected
    deps (fake runner, known repo) without touching real time or real restic.

    Skips silently (logs a warning) when:
    * ``runner`` is None  — restic binary absent or not yet installed
    * ``repo`` is empty   — no repo configured
    * ``passphrase`` is None/empty — passphrase not in keychain/config yet

    The function never raises: any failure is logged and swallowed so a single
    bad backup never tears down the supervisor.
    """
    from .backup import ResticUnavailable

    if runner is None:
        log.info("backup.tick.skipped", reason="restic_unavailable")
        return
    if not repo:
        log.info("backup.tick.skipped", reason="repo_not_configured")
        return
    if not passphrase:
        log.info("backup.tick.skipped", reason="passphrase_not_configured")
        return

    # Turnkey: initialize the repository on first use. Without this the hourly
    # tick fails forever until an operator runs `lighthouse backup --init`.
    try:
        repo_path = Path(repo)
        if not repo_path.exists() or not any(repo_path.iterdir()):
            runner.init(repo, passphrase)
            log.info("backup.tick.repo_initialized", repo=repo)
    except ResticUnavailable as exc:
        log.warning("backup.tick.restic_unavailable", exc=str(exc))
        return
    except Exception as exc:
        log.warning("backup.tick.init_error", exc=str(exc))
        return

    try:
        runner.backup(paths.all_dbs(), repo=repo, passphrase=passphrase)
        log.info("backup.tick.backup_ok", repo=repo)
    except ResticUnavailable as exc:
        log.warning("backup.tick.restic_unavailable", exc=str(exc))
        return
    except Exception as exc:
        log.warning("backup.tick.backup_error", exc=str(exc))
        return

    try:
        runner.check(repo, passphrase=passphrase)
        log.info("backup.tick.check_ok", repo=repo)
    except ResticUnavailable as exc:
        log.warning("backup.tick.restic_unavailable", exc=str(exc))
    except Exception as exc:
        log.warning("backup.tick.check_error", exc=str(exc))


def _start_backup_loop(
    paths: Paths,
    *,
    interval_s: float = 3600.0,
    runner: _BackupRunner | None | object = _SENTINEL,
) -> threading.Thread:
    """Daemon thread that backs up all DBs + runs a restic integrity check hourly.

    Mirrors :func:`_start_resolver_loop` in structure: a single daemon thread,
    gated by ``SchedulerGate`` (skips while PAUSED), offline-safe (no-op when
    the ``restic`` binary is absent or the repo/passphrase are not configured).

    ``runner`` is injectable for tests: pass a ``ResticBackup``-compatible fake
    to assert on the exact calls without spawning a real ``restic`` process.  The
    production default (sentinel) resolves at loop-start time so the supervisor
    never fails to boot just because restic isn't installed.
    """
    from .backup import ResticBackup, restic_installed
    from .governor.scheduler_gate import Policy
    from .secrets import SecretStore

    gate_cfg = SchedulerGateConfig.from_config_file(paths.config_file)
    gate = SchedulerGate(gate_cfg)

    # Resolve production runner once so the probe happens at startup, not import.
    resolved_runner: _BackupRunner | None
    if runner is _SENTINEL:
        resolved_runner = ResticBackup() if restic_installed() else None
    else:
        resolved_runner = runner  # type: ignore[assignment]

    def _loop() -> None:
        while True:
            time.sleep(interval_s)
            try:
                policy, _ = gate.policy()
                if is_paused(paths) or policy is Policy.PAUSED:
                    log.info("backup.tick.skipped", reason="paused")
                    continue
                # Resolve repo + passphrase fresh each tick — the operator may
                # have configured them after the supervisor started.
                repo = str(paths.data_dir / "backups" / "restic")
                try:
                    passphrase: str | None = SecretStore(paths.data_dir).get("restic.passphrase")
                except Exception:
                    passphrase = None
                _backup_tick(
                    paths, repo=repo, passphrase=passphrase, runner=resolved_runner
                )
            except Exception as exc:
                log.warning("backup.loop.error", exc=str(exc))

    thread = threading.Thread(target=_loop, daemon=True, name="backup-loop")
    thread.start()
    return thread


def _start_resolver_loop(paths: Paths, *, interval_s: float = 3600.0) -> threading.Thread:
    """Daemon thread that auto-resolves past-deadline calibration positions (Zone V).

    Closes the Brier loop: at its deadline a position is re-researched and, when
    the verdict is confident, scored — so the system learns whether its stated
    confidence was warranted. Gated two ways: it is a no-op unless live resolution
    is opted into (``LIGHTHOUSE_REAL_BACKEND=1``), and even then it skips ticks
    while the SchedulerGate reports PAUSED (offline / user-disabled). Offline runs
    never touch the network. Resolution is delegated to
    :func:`run_resolver_pass` — the evidence-grounded path: a position is resolved
    only from retrieved evidence, else deferred to the human-resolution queue. With
    no evidence retriever wired yet, due positions defer (never self-graded from the
    model's own memory).
    """
    from .dispatcher import build_runtime_gateway
    from .governor.scheduler_gate import Policy
    from .verification.resolver import run_resolver_pass

    live = os.environ.get("LIGHTHOUSE_REAL_BACKEND") == "1"
    gate_cfg = SchedulerGateConfig.from_config_file(paths.config_file)
    gate = SchedulerGate(gate_cfg)
    gateway = build_runtime_gateway(paths) if live else None
    # Re-fetch evidence at the deadline so resolution is grounded in fresh sources,
    # never the model's own memory. None when offline → due positions defer.
    retriever = None
    if gateway is not None:
        from .verification.evidence import build_evidence_retriever
        retriever = build_evidence_retriever(paths, gateway=gateway)
    log.info("resolver.gateway", live=live,
             backend="ollama" if gateway is not None else "offline",
             retriever=retriever is not None)

    def _loop() -> None:
        while True:
            time.sleep(interval_s)
            if not live or gateway is None:
                continue  # offline / opt-out: no-op
            try:
                policy, _ = gate.policy()
                if is_paused(paths) or policy is Policy.PAUSED:
                    continue
                results = run_resolver_pass(paths.positions_db, gateway=gateway,
                                            retriever=retriever)
                resolved = sum(1 for r in results if r.auto_resolved)
                if results:
                    log.info("resolver.pass", attempted=len(results), resolved=resolved)
            except Exception as exc:
                log.warning("resolver.pass.error", exc=str(exc))

    thread = threading.Thread(target=_loop, daemon=True, name="resolver-loop")
    thread.start()
    return thread


def _recover_orphaned_intents(paths: Paths) -> int:
    """Reclaim ``in_flight`` intents orphaned by a previous crash.

    Mirrors the ``reap_stuck_jobs`` recovery in :func:`_start_dispatch_loop`:
    a crash between :func:`intents.claim_one` (which marks an intent
    ``in_flight``) and :func:`intents.mark_applied`/``mark_failed`` would leave
    the row stuck forever, since ``claim_one`` only selects ``pending`` rows.
    Run once at startup *before* any effector begins so the outbox drains.

    Offline-safe: a missing intents DB (or any error) is logged and swallowed —
    it never blocks the supervisor from booting. Returns the number of intents
    requeued (0 on no-op / error).
    """
    from . import intents

    try:
        requeued = intents.requeue_stuck(paths.intents_db)
        if requeued:
            log.info("supervisor.intents_requeued", intents=requeued)
        return requeued
    except Exception as exc:
        log.warning("supervisor.intents_requeue.error", exc=str(exc))
        return 0


def serve(paths: Paths | None = None, *, host: str = "127.0.0.1",
          port: int = 8765, run: bool = True) -> uvicorn.Server:
    """Boot the supervisor. ``run=False`` returns the Server for tests."""
    p = paths or make_paths()
    p.ensure()
    _configure_logging(p)

    log.info("supervisor.boot", data_dir=str(p.data_dir))
    migrated = migrate_all(kinds_for(p))
    log.info("supervisor.migrations_applied", **migrated)

    # Ensure self-initialising side DBs exist
    from .compounding.hotness_store import EntityHotnessStore
    ReflectionStore(p.reflections_db)
    EntityHotnessStore(p.entity_hotness_db)

    pid = os.getpid()
    _write_pidfile(p.pid_file, pid)
    _set_state(p, "running", pid)
    started_at = time.time()

    app = create_app(p, started_at=started_at)
    config = uvicorn.Config(app, host=host, port=port, log_level="info",
                            loop="asyncio", lifespan="on")
    server = uvicorn.Server(config)

    def _on_signal(signum: int, _frame: object) -> None:
        log.info("supervisor.signal", signum=signum)
        server.should_exit = True

    if run:
        # Outbox recovery: reclaim in_flight intents orphaned by a prior crash
        # BEFORE any effector/dispatch loop starts (mirrors reap_stuck_jobs).
        _recover_orphaned_intents(p)
        # Share the app's EventBus with the dispatch loop so a running job can
        # push live job.step progress to the dashboard SSE stream.
        _bus = getattr(app.state, "event_bus", None)
        _start_subconscious_loop(p)
        _start_monitor_loop(p)
        _start_dispatch_loop(p, bus=_bus)
        _start_resolver_loop(p)
        _start_backup_loop(p)
        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)
        try:
            server.run()
        finally:
            _set_state(p, "running", None)  # clear pid; status stays for next boot
            _remove_pidfile(p.pid_file)
            log.info("supervisor.exit")
    return server


def serve_in_thread(paths: Paths, *, host: str = "127.0.0.1", port: int = 0) -> tuple[
        uvicorn.Server, threading.Thread, int]:
    """Helper used by integration tests: bind to ephemeral port, run in thread."""
    paths.ensure()
    migrate_all(kinds_for(paths))
    pid = os.getpid()
    _write_pidfile(paths.pid_file, pid)
    _set_state(paths, "running", pid)
    app = create_app(paths, started_at=time.time())
    config = uvicorn.Config(app, host=host, port=port, log_level="warning",
                            loop="asyncio", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Wait for the socket to bind, then read the actual port.
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if server.started and server.servers and server.servers[0].sockets:
            sock = server.servers[0].sockets[0]
            return server, thread, sock.getsockname()[1]
        time.sleep(0.02)
    raise RuntimeError("supervisor failed to start within 5s")


def main() -> None:
    """Console-script entrypoint for `lighthouse-supervisor`."""
    from .paths import paths_from_env
    serve(paths_from_env())


if __name__ == "__main__":
    main()
