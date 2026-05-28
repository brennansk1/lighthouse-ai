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
import sys
import threading
import time
from pathlib import Path

import structlog
import uvicorn

from .controlplane import create_app
from .governor.scheduler_gate import SchedulerGate, SchedulerGateConfig
from .paths import Paths, make_paths
from .persistence import open_db
from .schema import kinds_for, migrate_all
from .subconscious import SubconsciousEngine, stale_position_escalations, ReflectionStore

log = structlog.get_logger(__name__)


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


def _start_logseq_sync_loop(paths: Paths, *, graph_dir: Path, interval_s: float = 86400.0) -> threading.Thread:
    """Start a daemon thread that syncs published drafts to Logseq every interval_s seconds."""
    from .compounding.logseq_sync import sync_drafts

    def _loop() -> None:
        while True:
            time.sleep(interval_s)
            try:
                result = sync_drafts(paths, graph_dir)
                log.info("logseq_sync.tick", synced=result.synced, failed=result.failed)
            except Exception as exc:
                log.warning("logseq_sync.tick_error", error=str(exc))

    thread = threading.Thread(target=_loop, daemon=True, name="logseq-sync-loop")
    thread.start()
    return thread


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
        _start_subconscious_loop(p)
        # Start Logseq sync loop if configured
        try:
            import tomllib as _tomllib
        except ImportError:
            import tomli as _tomllib  # type: ignore
        try:
            if p.config_file.exists():
                with p.config_file.open("rb") as _fh:
                    _lcfg = _tomllib.load(_fh).get("logseq", {})
                if _lcfg.get("enabled") and _lcfg.get("graph_dir"):
                    from pathlib import Path as _Path
                    _graph_dir = _Path(_lcfg["graph_dir"]).expanduser()
                    _interval = float(_lcfg.get("sync_interval_hours", 24)) * 3600
                    if _interval > 0:
                        _start_logseq_sync_loop(p, graph_dir=_graph_dir, interval_s=_interval)
                        log.info("logseq_sync.scheduled", interval_hours=_lcfg.get("sync_interval_hours", 24))
        except Exception as _exc:
            log.warning("logseq_sync.setup_failed", error=str(_exc))
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
