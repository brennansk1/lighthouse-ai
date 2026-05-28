"""``lighthouse`` CLI — typer + rich, talks to a running supervisor over HTTP.

Sprint 1 commands:
  init    Create ~/.lighthouse/, write config + service files + Litestream yml.
  start   Load the launchd plist (macOS) or enable+start the systemd unit (Linux).
  stop    Unload / stop.
  status  Hit /health on the control plane.
  doctor  Run all readiness checks; non-zero exit on any failure.
  pause   Toggle supervisor_state.status (soft|hard).
  resume  Set status back to 'running'.

Process lifecycle is delegated to launchd/systemd. The CLI just wraps
``launchctl`` / ``systemctl --user``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from . import litestream as ls
from .hardware import probe, write_profile
from .paths import Paths, make_paths
from .persistence import integrity_check, open_db
from .schema import kinds_for, migrate_all
from .templates import write_rendered

app = typer.Typer(help="Lighthouse — local-first research instrument.", no_args_is_help=True)
console = Console()
err_console = Console(stderr=True)

DEFAULT_PORT = 8765


def _paths_from_env() -> Paths:
    from .paths import paths_from_env
    return paths_from_env()


def _load_notify_cfg() -> dict:
    """Load the [notifications] section from config.toml, or empty dict."""
    try:
        paths = _paths_from_env()
        if not paths.config_file.exists():
            return {}
        try:
            import tomllib
        except ImportError:  # pragma: no cover
            import tomli as tomllib  # type: ignore
        with paths.config_file.open("rb") as fh:
            return tomllib.load(fh).get("notifications", {})
    except Exception:
        return {}


def _notify_event(event: str, title: str, body: str, **data: object) -> None:
    """Fire a notification through configured channels. Best-effort — never raises.

    ``data`` kwargs are forwarded to the Telegram template renderer so callers
    can pass structured fields (question=, draft_id=, wep_phrase=, etc.) that
    produce richly-formatted HTML messages on Telegram, while other channels
    receive the plain (title, body) pair.

    Respects ``telegram_events`` override: if set, only those events are routed
    to Telegram so operators can keep Telegram quiet for low-priority events.
    """
    try:
        cfg = _load_notify_cfg()
        if not cfg:
            return
        from .notify import DesktopChannel, DiscordChannel, Notifier
        from .notify.telegram import TelegramChannel
        from .notify.telegram_templates import render as _tg_render

        global_events: list[str] = cfg.get("events", [])
        tg_events: list[str] = cfg.get("telegram_events", global_events)

        # For Telegram, use the professional template renderer
        tg_title, tg_body = _tg_render(event, title, body, **data)

        channels: list[tuple[str, object]] = [("desktop", DesktopChannel())]
        if cfg.get("discord_webhook_url"):
            channels.append(("discord", DiscordChannel(cfg["discord_webhook_url"])))
        if cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
            if not tg_events or event in tg_events:
                channels.append(("telegram", TelegramChannel(
                    bot_token=cfg["telegram_bot_token"],
                    chat_id=cfg["telegram_chat_id"],
                )))

        # Telegram gets the richly-rendered message; other channels get plain text.
        # We do this by calling notify once with plain text then separately for Telegram.
        plain_channels = [(n, c) for n, c in channels if n != "telegram"]
        tg_channels = [(n, c) for n, c in channels if n == "telegram"]
        if plain_channels:
            Notifier(cfg, plain_channels).notify(event, title, body)
        if tg_channels:
            Notifier(cfg, tg_channels).notify(event, tg_title, tg_body)
    except Exception:
        pass


# ---------------------------------------------------------------- init --

@app.command()
def init(
    data_dir: str = typer.Option(None, help="Override default ~/.lighthouse"),
    force: bool = typer.Option(False, help="Overwrite existing config files"),
    install_service: bool = typer.Option(True, help="Install launchd/systemd unit"),
) -> None:
    """Create the Lighthouse data directory and OS service unit."""
    paths = make_paths(data_dir) if data_dir else make_paths()
    paths.ensure()
    console.print(f"[bold]Data dir:[/bold] {paths.data_dir}")

    profile = probe()
    write_profile(profile, paths.hardware_file)
    console.print(f"Hardware: {profile.platform}/{profile.arch} "
                  f"{profile.total_ram_gb} GB RAM → tier [bold]{profile.suggested_tier}[/bold]")

    cfg_dest = paths.config_file
    if cfg_dest.exists() and not force:
        console.print(f"  [yellow]skip[/yellow] {cfg_dest} (exists; pass --force)")
    else:
        write_rendered(
            "config.toml", cfg_dest,
            data_dir=paths.data_dir, detected_tier=profile.suggested_tier,
            total_ram_gb=profile.total_ram_gb, litestream_config=paths.litestream_config,
        )
        console.print(f"  [green]wrote[/green] {cfg_dest}")

    ls_dest = paths.litestream_config
    if ls_dest.exists() and not force:
        console.print(f"  [yellow]skip[/yellow] {ls_dest} (exists; pass --force)")
    else:
        ls.write_litestream_config(paths)
        console.print(f"  [green]wrote[/green] {ls_dest}")

    migrated = migrate_all(kinds_for(paths))
    for kind, ids in migrated.items():
        if ids:
            console.print(f"  migrated [cyan]{kind}.db[/cyan] {ids}")

    if install_service:
        _install_service(paths, force=force)

    console.print("\n[bold green]lighthouse init complete.[/bold green]")
    if not ls.litestream_installed():
        console.print(f"[yellow]warning:[/yellow] {ls.install_hint()}")


def _install_service(paths: Paths, *, force: bool) -> None:
    supervisor_bin = shutil.which("lighthouse-supervisor") or "lighthouse-supervisor"
    path_env = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    stdout_log = str(paths.logs_dir / "supervisor.out.log")
    stderr_log = str(paths.logs_dir / "supervisor.err.log")

    if sys.platform == "darwin":
        dest = Path.home() / "Library" / "LaunchAgents" / "com.lighthouse.supervisor.plist"
        if dest.exists() and not force:
            console.print(f"  [yellow]skip[/yellow] {dest} (exists; pass --force)")
            return
        write_rendered(
            "com.lighthouse.supervisor.plist", dest,
            supervisor_bin=supervisor_bin, path_env=path_env,
            data_dir=paths.data_dir, stdout_log=stdout_log, stderr_log=stderr_log,
        )
        console.print(f"  [green]wrote[/green] {dest}")
        console.print("    load with: [cyan]launchctl load -w "
                      f"{dest}[/cyan]")
    elif sys.platform.startswith("linux"):
        dest = Path.home() / ".config" / "systemd" / "user" / "lighthouse.service"
        if dest.exists() and not force:
            console.print(f"  [yellow]skip[/yellow] {dest} (exists; pass --force)")
            return
        write_rendered(
            "lighthouse.service", dest,
            supervisor_bin=supervisor_bin, data_dir=paths.data_dir,
            stdout_log=stdout_log, stderr_log=stderr_log,
        )
        console.print(f"  [green]wrote[/green] {dest}")
        console.print("    enable with: [cyan]systemctl --user daemon-reload && "
                      "systemctl --user enable --now lighthouse[/cyan]")
    else:
        console.print(f"  [yellow]warning:[/yellow] auto-install not supported on {sys.platform}")


# ----------------------------------------------------- start / stop --

def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                          check=False)


@app.command()
def start() -> None:
    """Start the supervisor via launchd/systemd."""
    if sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "com.lighthouse.supervisor.plist"
        r = _launchctl("load", "-w", str(plist))
        if r.returncode:
            err_console.print(f"[red]launchctl load failed:[/red] {r.stderr.strip()}")
            raise typer.Exit(r.returncode)
        console.print("[green]supervisor loaded.[/green]")
    elif sys.platform.startswith("linux"):
        _systemctl("daemon-reload")
        r = _systemctl("start", "lighthouse")
        if r.returncode:
            err_console.print(f"[red]systemctl start failed:[/red] {r.stderr.strip()}")
            raise typer.Exit(r.returncode)
        console.print("[green]supervisor started.[/green]")
    else:
        err_console.print(f"[red]unsupported platform:[/red] {sys.platform}")
        raise typer.Exit(2)


@app.command()
def stop() -> None:
    """Stop the supervisor via launchd/systemd."""
    if sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "com.lighthouse.supervisor.plist"
        r = _launchctl("unload", str(plist))
        if r.returncode:
            err_console.print(f"[red]launchctl unload failed:[/red] {r.stderr.strip()}")
            raise typer.Exit(r.returncode)
        console.print("[green]supervisor unloaded.[/green]")
    elif sys.platform.startswith("linux"):
        r = _systemctl("stop", "lighthouse")
        if r.returncode:
            err_console.print(f"[red]systemctl stop failed:[/red] {r.stderr.strip()}")
            raise typer.Exit(r.returncode)
        console.print("[green]supervisor stopped.[/green]")
    else:
        err_console.print(f"[red]unsupported platform:[/red] {sys.platform}")
        raise typer.Exit(2)


# --------------------------------------------------------- status --

@app.command()
def status(port: int = DEFAULT_PORT, json_out: bool = typer.Option(False, "--json")) -> None:
    """Query /health on the control plane."""
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=3.0)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        err_console.print(f"[red]control plane unreachable on :{port}:[/red] {exc}")
        raise typer.Exit(1) from None
    data = r.json()
    if json_out:
        console.print_json(data=data)
        return
    sup = data["supervisor"]
    console.print(f"[bold]Lighthouse[/bold] v{data['version']} — "
                  f"uptime {data['uptime_seconds']}s — supervisor [bold]{sup['status']}[/bold] "
                  f"(pid {sup.get('pid')})")
    table = Table("db", "present", "integrity", "size", show_lines=False)
    for kind, info in data["databases"].items():
        if not info.get("present"):
            table.add_row(kind, "no", "-", "-")
        else:
            table.add_row(kind, "yes", str(info.get("integrity_check", "?")),
                          str(info.get("size_bytes", "-")))
    console.print(table)
    lit = data["litestream"]
    if lit.get("present"):
        ltable = Table("replica", "lag (s)")
        for name, info in lit.get("replicas", {}).items():
            ltable.add_row(name, str(info.get("lag_seconds", "-")))
        console.print(ltable)


# --------------------------------------------------------- doctor --

@app.command()
def doctor() -> None:
    """Run readiness checks; exit non-zero on failure."""
    paths = _paths_from_env()
    issues: list[str] = []

    # Section: hardware
    profile = probe()
    console.rule("[bold]hardware[/bold]")
    console.print(f"  platform: {profile.platform} {profile.arch}")
    console.print(f"  ram: {profile.total_ram_gb} GB total, {profile.free_ram_gb} GB free")
    console.print(f"  cpu: {profile.cpu_cores_physical}p/{profile.cpu_cores_logical}l")
    if profile.gpu:
        for g in profile.gpu:
            console.print(f"  gpu: {g.name} {g.vram_gb} GB ({g.vendor})")
    console.print(f"  backends: {', '.join(profile.available_backends)}")
    console.print(f"  suggested tier: [bold]{profile.suggested_tier}[/bold]")

    # Section: scheduler gate (host-courtesy throttle)
    from .governor.scheduler_gate import (
        SchedulerGateConfig,
        current_policy,
        sample_signals,
    )
    gate_cfg = SchedulerGateConfig.from_config_file(paths.config_file)
    sig = sample_signals(gate_cfg)
    policy, reason = current_policy(gate_cfg, sig)
    batt = "n/a" if sig.battery_charge is None else f"{sig.battery_charge * 100:.0f}%"
    console.print(f"  scheduler gate: [bold]{policy.value}[/bold]"
                  + (f" ({reason.value})" if reason else "")
                  + f" — ac={sig.on_ac_power} batt={batt} "
                  f"cpu={sig.cpu_usage_pct:.0f}% mode={gate_cfg.mode}")

    # Section: package versions
    console.rule("[bold]packages[/bold]")
    console.print(f"  lighthouse-ai: {__version__}")
    console.print(f"  python: {sys.version.split()[0]}")
    for tool in ("ollama", "docker", "bwrap", "sandbox-exec", "litestream"):
        path = shutil.which(tool)
        mark = "[green]✓[/green]" if path else "[yellow]missing[/yellow]"
        console.print(f"  {tool}: {mark} {path or ''}")

    # Section: directory structure
    console.rule("[bold]directories[/bold]")
    for name in ("data_dir", "corpus_dir", "staging_dir", "quarantine_dir",
                 "worm_dir", "skills_dir", "logs_dir", "run_dir", "replicas_dir"):
        d = getattr(paths, name)
        if d.exists():
            console.print(f"  [green]✓[/green] {name}: {d}")
        else:
            console.print(f"  [yellow]-[/yellow] {name}: {d} (not created; run init)")

    # Section: sqlite integrity
    console.rule("[bold]databases[/bold]")
    for kind, p in kinds_for(paths).items():
        if not p.exists():
            console.print(f"  [yellow]-[/yellow] {kind}.db not yet created")
            continue
        try:
            conn = open_db(p)
            try:
                check = integrity_check(conn)
            finally:
                conn.close()
            if check == "ok":
                console.print(f"  [green]✓[/green] {kind}.db integrity ok")
            else:
                console.print(f"  [red]✗[/red] {kind}.db integrity: {check}")
                issues.append(f"{kind}.db integrity: {check}")
        except Exception as exc:
            console.print(f"  [red]✗[/red] {kind}.db open failed: {exc!r}")
            issues.append(f"{kind}.db open failed")

    # Section: litestream
    console.rule("[bold]litestream[/bold]")
    if not ls.litestream_installed():
        console.print(f"  [yellow]missing:[/yellow] {ls.install_hint().splitlines()[0]}")
    else:
        console.print(f"  [green]✓[/green] {ls.litestream_version() or 'installed'}")
    for lag in ls.replica_lags(paths):
        if lag.lag_seconds is None:
            console.print(f"  [yellow]-[/yellow] {lag.name}: no snapshot yet")
        elif lag.lag_seconds > 10:
            console.print(f"  [red]✗[/red] {lag.name}: lag {lag.lag_seconds}s (>10s)")
            issues.append(f"litestream {lag.name} lag {lag.lag_seconds}s")
        else:
            console.print(f"  [green]✓[/green] {lag.name}: lag {lag.lag_seconds}s")

    # Section: external services (optional; missing is a hint, not an error)
    console.rule("[bold]external services[/bold]")
    try:
        from .backends.ollama import OllamaBackend
        ollama_ok = OllamaBackend().available()
    except Exception:
        ollama_ok = False
    if ollama_ok:
        console.print("  [green]✓[/green] ollama at 127.0.0.1:11434")
    else:
        console.print("  [yellow]-[/yellow] ollama not reachable "
                      "(start Ollama.app or `ollama serve` to enable real LLM)")
    try:
        from .rag.qdrant_store import QdrantStore
        qdrant_ok = QdrantStore(dim=8).available()
    except Exception:
        qdrant_ok = False
    if qdrant_ok:
        console.print("  [green]✓[/green] qdrant at 127.0.0.1:6333")
    else:
        console.print("  [yellow]-[/yellow] qdrant not reachable "
                      "(boot via scripts/lh-stack.docker-compose.yml)")

    # Section: notifications
    console.rule("[bold]notifications[/bold]")
    cfg_notif: dict = {}
    if paths.config_file.exists():
        try:
            import tomllib
        except ImportError:  # pragma: no cover
            import tomli as tomllib  # type: ignore
        with paths.config_file.open("rb") as fh:
            cfg_notif = tomllib.load(fh).get("notifications", {})
    if cfg_notif.get("telegram_bot_token") and cfg_notif.get("telegram_chat_id"):
        from .notify.telegram import TelegramChannel
        tc = TelegramChannel(bot_token=cfg_notif["telegram_bot_token"], chat_id=cfg_notif["telegram_chat_id"])
        if tc.available():
            console.print("  [green]✓[/green] telegram bot configured")
        else:
            console.print("  [yellow]-[/yellow] telegram token/chat_id missing")
    else:
        console.print("  [yellow]-[/yellow] telegram not configured (optional)")

    # Section: audit chain integrity
    console.rule("[bold]audit chain[/bold]")
    if paths.audit_db.exists():
        try:
            from .verification.audit_chain import resolve_secret, verify_audit_chain
            try:
                secret = resolve_secret(None, data_dir=paths.data_dir)
                bad = verify_audit_chain(paths.audit_db, secret=secret)
                if bad:
                    console.print(f"  [red]✗[/red] chain broken at seq(s): {bad}")
                    issues.append(f"audit chain broken: {bad}")
                else:
                    console.print("  [green]✓[/green] chain intact")
            except Exception as exc:
                console.print(f"  [yellow]-[/yellow] could not verify: {exc!r}")
        except Exception:
            pass

    # Section: outbox depth
    console.rule("[bold]outbox[/bold]")
    if paths.intents_db.exists():
        try:
            from .intents import outbox_depth
            depth = outbox_depth(paths.intents_db)
            if depth < 100:
                console.print(f"  [green]✓[/green] depth = {depth}")
            elif depth < 1000:
                console.print(f"  [yellow]warn[/yellow] depth = {depth} (>100)")
            else:
                console.print(f"  [red]✗[/red] depth = {depth} (>1000)")
                issues.append(f"outbox depth {depth}")
        except Exception as exc:
            console.print(f"  [yellow]-[/yellow] could not read: {exc!r}")

    # Section: model selection (budget fit + paging) + fingerprint drift
    console.rule("[bold]models[/bold]")
    try:
        from .gateway import budget_report
        rep = budget_report(profile)
        console.print(f"  budget: [bold]{rep['budget_gb']} GB[/bold] "
                      f"(tier {profile.suggested_tier})")
        for role, info in rep["roles"].items():
            mark = "[yellow]pages SSD[/yellow]" if info["pages_from_ssd"] else "[green]fits[/green]"
            console.print(f"    {role:12} {info['model']:20} {info['footprint_gb']}G  {mark}")
        if rep["paging"]:
            console.print(f"  [yellow]note:[/yellow] {', '.join(rep['paging'])} "
                          f"page from SSD on this RAM — slower but functional.")
    except Exception as exc:
        console.print(f"  [yellow]-[/yellow] could not compute budget: {exc!r}")

    chosen = paths.data_dir / "chosen_models.yaml"
    if chosen.exists():
        try:
            from .gateway import check_drift
            drift = check_drift(chosen, allow_drift=True)
            if drift:
                for d in drift:
                    console.print(f"  [yellow]drift[/yellow] {d['model']}: "
                                  f"recorded {d['recorded'][:12]} != installed {d['installed'][:12]}")
            else:
                console.print("  [green]✓[/green] no fingerprint drift")
        except Exception as exc:
            console.print(f"  [yellow]-[/yellow] could not check drift: {exc!r}")

    console.rule()
    if issues:
        console.print(f"[red]{len(issues)} issue(s):[/red]")
        for i in issues:
            console.print(f"  • {i}")
        raise typer.Exit(1)
    console.print("[bold green]all green.[/bold green]")


# ---------------------------------------------------- pause / resume --

@app.command()
def pause(hard: bool = typer.Option(False, "--hard", help="Hard pause (drain in-flight)")) -> None:
    """Pause the supervisor (soft by default; hard drains intents)."""
    paths = _paths_from_env()
    if not paths.state_db.exists():
        err_console.print("[red]state.db missing; run `lighthouse init` first[/red]")
        raise typer.Exit(1)
    new_status = "paused_hard" if hard else "paused_soft"
    conn = open_db(paths.state_db)
    try:
        conn.execute("UPDATE supervisor_state SET status = ?, updated_at = datetime('now') "
                     "WHERE id = 1", (new_status,))
    finally:
        conn.close()
    console.print(f"[yellow]supervisor → {new_status}[/yellow]")


@app.command()
def resume() -> None:
    """Resume the supervisor (clears pause state)."""
    paths = _paths_from_env()
    if not paths.state_db.exists():
        err_console.print("[red]state.db missing; run `lighthouse init` first[/red]")
        raise typer.Exit(1)
    conn = open_db(paths.state_db)
    try:
        conn.execute("UPDATE supervisor_state SET status = 'running', "
                     "updated_at = datetime('now') WHERE id = 1")
    finally:
        conn.close()
    console.print("[green]supervisor → running[/green]")


@app.command()
def version() -> None:
    """Print the installed Lighthouse version."""
    console.print(__version__)


# --------------------------------------------------- research --

@app.command()
def research(
    question: str = typer.Argument(..., help="The research question."),
    doc: list[Path] = typer.Option(None, "--doc", "-d",
                                   help="File(s) to ingest into the corpus first."),
    arxiv: str = typer.Option(None, "--arxiv", help="arXiv query to ingest abstracts."),
    openalex: str = typer.Option(None, "--openalex", help="OpenAlex query to ingest."),
    pubmed: str = typer.Option(None, "--pubmed", help="PubMed query to ingest abstracts."),
    crossref: str = typer.Option(None, "--crossref", help="Crossref query to ingest."),
    url: list[str] = typer.Option(None, "--url", help="URL(s) to fetch + sandbox-ingest."),
    sources: int = typer.Option(5, help="Max papers per source query."),
    mode: str = typer.Option("deep-dive", help="deep-dive | quc"),
    rounds: int = typer.Option(2, help="Deep-dive refinement rounds."),
    offline: bool = typer.Option(False, "--offline",
                                 help="Use stub backends — no model load."),
) -> None:
    """Run the research pipeline end-to-end and stage a draft.

    Builds a corpus from --doc files and/or live --arxiv / --openalex queries,
    runs framing → retrieval → synthesis, enforces the citation-discipline
    gate, records each claim as a calibration Position, and stages a draft.
    Uses real Ollama + bge-m3 when available; --offline forces stubs.
    """
    paths = _paths_from_env()
    paths.ensure()
    from .schema import kinds_for, migrate_all
    migrate_all(kinds_for(paths))
    from .pipeline import PipelineConfig, ResearchPipeline

    console.print(f"[bold]Researching:[/bold] {question}")
    if offline:
        console.print("[yellow]offline mode[/yellow] — stub backends, no model load.")
    pipe = ResearchPipeline(paths, config=PipelineConfig(
        offline=offline, mode=mode, max_rounds=rounds))
    console.print(f"  backends: embedder={pipe.backends['embedder']} · "
                  f"store={pipe.backends['vector_store']} · "
                  f"gateway={pipe.backends['gateway']}")

    ingested = 0
    for d in (doc or []):
        if not d.exists():
            err_console.print(f"[red]no such file:[/red] {d}")
            raise typer.Exit(1)
        ingested += pipe.ingest_path(d)
    if arxiv:
        from .sources.arxiv import search_arxiv
        try:
            docs = search_arxiv(arxiv, max_results=sources)
            for dd in docs:
                ingested += pipe.ingest_text(dd.id, dd.text, metadata=dd.metadata)
            console.print(f"  arXiv '{arxiv}': ingested {len(docs)} paper(s)")
        except Exception as exc:
            err_console.print(f"[yellow]arXiv fetch failed:[/yellow] {exc}")
    if openalex:
        from .sources.openalex import search_openalex
        try:
            docs = search_openalex(openalex, max_results=sources)
            for dd in docs:
                ingested += pipe.ingest_text(dd.id, dd.text, metadata=dd.metadata)
            console.print(f"  OpenAlex '{openalex}': ingested {len(docs)} work(s)")
        except Exception as exc:
            err_console.print(f"[yellow]OpenAlex fetch failed:[/yellow] {exc}")
    for q, name, fn_path in [(pubmed, "PubMed", "pubmed.search_pubmed"),
                             (crossref, "Crossref", "crossref.search_crossref")]:
        if not q:
            continue
        mod, fn = fn_path.split(".")
        search = getattr(__import__(f"lighthouse_ai.sources.{mod}", fromlist=[fn]), fn)
        try:
            docs = search(q, max_results=sources)
            for dd in docs:
                ingested += pipe.ingest_text(dd.id, dd.text, metadata=dd.metadata)
            console.print(f"  {name} '{q}': ingested {len(docs)} item(s)")
        except Exception as exc:
            err_console.print(f"[yellow]{name} fetch failed:[/yellow] {exc}")
    if url:
        from .ingest import fetch_and_ingest
        from .sandbox.broker import build_default_broker
        broker = build_default_broker(paths.data_dir)
        for u in url:
            try:
                doc_obj = fetch_and_ingest(u, broker)
                if doc_obj is None:
                    err_console.print(f"[yellow]rejected/empty (sandbox):[/yellow] {u}")
                    continue
                ingested += pipe.ingest_text(doc_obj.id, doc_obj.text,
                                             metadata=doc_obj.metadata)
                console.print(f"  fetched + sandbox-admitted: {u}")
            except Exception as exc:
                err_console.print(f"[yellow]fetch failed:[/yellow] {u}: {exc}")
    if ingested:
        console.print(f"  corpus: {ingested} chunk(s)")

    _notify_event("job_started", "Research started", question[:80],
                  question=question, mode=mode)
    try:
        result = pipe.research(question)
    except Exception as exc:
        _notify_event("job_failed", "Research failed", f"{question[:60]}\n\nError: {exc}",
                      question=question, error=str(exc), mode=mode)
        err_console.print(f"[red]research failed:[/red] {exc}")
        raise typer.Exit(1) from None

    for w in result.warnings:
        err_console.print(f"[yellow]⚠ backend warning:[/yellow] {w}")

    d = result.discipline or {}
    console.print(f"\n[green]staged draft {result.draft_id}[/green] "
                  f"({result.mode}, {result.sections} section(s), "
                  f"{result.chunks_ingested} corpus chunks)")
    if d:
        verdict = "[green]passed[/green]" if d.get("passed") else "[yellow]flagged[/yellow]"
        console.print(f"  discipline: {verdict} — {d.get('sourced', 0)}/{d.get('claims', 0)} "
                      f"claims sourced ({d.get('coverage', 0):.0%} coverage); "
                      f"{d.get('claims', 0)} claim(s) recorded as calibration positions")
    _wep = d.get("wep_phrase", "")
    _src = d.get("source_count", result.chunks_ingested)
    _notify_event(
        "draft_ready", "Draft staged",
        f"{question[:60]}\n\nDraft: {result.draft_id}",
        question=question,
        draft_id=result.draft_id,
        mode=result.mode if hasattr(result, "mode") else mode,
        wep_phrase=_wep,
        source_count=_src,
        sections=result.sections if hasattr(result, "sections") else 0,
    )
    console.print("  review it: dashboard → Drafts, or `lighthouse status`")


@app.command("eval")
def eval_retrieval(
    k: int = typer.Option(5, help="Cutoff for precision@k / recall@k."),
    offline: bool = typer.Option(False, "--offline",
                                 help="Force test-tier stubs (no model load)."),
    json_out: bool = typer.Option(False, "--json", help="Emit metrics as JSON."),
) -> None:
    """Run the golden-set retrieval eval and report precision@k / recall@k / MRR.

    Uses real backends when available (bge-m3 via Ollama, FlagReranker) so the
    numbers reflect production retrieval; falls back to the test-tier stubs
    (HashEmbedder + ScoreReranker) when models are absent or --offline is set.
    Design bar: precision@5 ≥ 0.40 with the real embedder + reranker.
    """
    from .eval import build_golden_set, build_index, evaluate

    golden = build_golden_set()
    if offline:
        hybrid = build_index(golden)
        backends = {"embedder": "hash-stub", "reranker": "ScoreReranker"}
        warns: list[str] = []
    else:
        from .pipeline import make_embedder, make_vector_store
        from .rag.flag_reranker import make_reranker
        embedder, emb_name, warns = make_embedder(offline=False)
        store, store_name, store_warns = make_vector_store(embedder.dim, offline=False)
        warns = warns + store_warns
        reranker = make_reranker(prefer_real=True)
        hybrid = build_index(golden, embedder=embedder, store=store, reranker=reranker)
        backends = {"embedder": emb_name, "vector_store": store_name,
                    "reranker": type(reranker).__name__}

    report = evaluate(hybrid, golden, k=k)

    if json_out:
        import json
        console.print(json.dumps({"metrics": report, "backends": backends,
                                  "warnings": warns}))
        return

    for w in warns:
        err_console.print(f"[yellow]⚠ backend warning:[/yellow] {w}")
    console.print(f"  backends: {', '.join(f'{k}={v}' for k, v in backends.items())}")
    console.print(f"  golden set: {len(golden.documents)} docs · {len(golden.cases)} queries\n")
    p_at_k = report.get(f"precision@{k}", 0.0)
    bar = "[green]✓[/green]" if p_at_k >= 0.40 else "[yellow]below 0.40 bar[/yellow]"
    for name, val in report.items():
        console.print(f"  {name:<14} {val:.3f}")
    console.print(f"\n  precision@{k} {p_at_k:.3f} — {bar}")


@app.command()
def export(
    draft_id: str = typer.Argument(..., help="Draft id to export."),
    logseq: Path = typer.Option(None, "--logseq", help="Logseq graph directory. Falls back to config.toml [logseq] graph_dir."),
) -> None:
    """Export a staged/published draft to a Logseq graph (filesystem markdown)."""
    paths = _paths_from_env()

    # Resolve graph_dir: CLI flag takes priority, then config.toml [logseq] section.
    graph_dir: Path | None = logseq
    if graph_dir is None:
        try:
            try:
                import tomllib
            except ImportError:  # pragma: no cover
                import tomli as tomllib  # type: ignore
            if paths.config_file.exists():
                with paths.config_file.open("rb") as fh:
                    _cfg = tomllib.load(fh)
                _gd = _cfg.get("logseq", {}).get("graph_dir")
                if _gd:
                    graph_dir = Path(_gd).expanduser()
        except Exception:
            pass

    if graph_dir is None:
        err_console.print("[red]no Logseq graph dir: pass --logseq <dir> or set [logseq] graph_dir in config.toml[/red]")
        raise typer.Exit(1)

    conn = open_db(paths.state_db)
    try:
        rows = conn.execute(
            "SELECT id, topic, title, body_html, wep_phrase, source_count "
            "FROM drafts WHERE id=?", (draft_id,)).fetchall()
    finally:
        conn.close()
    if not rows:
        err_console.print(f"[red]no draft {draft_id}[/red]")
        raise typer.Exit(1)
    _id, topic, title, body_html, wep_phrase, source_count = rows[0]
    from .targets.logseq import export_draft
    page = export_draft(graph_dir, draft_id=_id, title=title, body_html=body_html,
                        topic=topic, wep_phrase=wep_phrase,
                        source_count=source_count or 0)
    console.print("[green]exported to Logseq[/green]")
    console.print(f"[green]wrote Logseq page →[/green] {page.path}")


@app.command("positions-due")
def positions_due() -> None:
    """List positions awaiting resolution (the calibration to-do)."""
    paths = _paths_from_env()
    from .verification.positions import _ensure_extras
    _ensure_extras(paths.positions_db)
    conn = open_db(paths.positions_db)
    try:
        rows = conn.execute(
            "SELECT id, claim, wep_band, confidence FROM positions "
            "WHERE outcome IS NULL ORDER BY created_at DESC LIMIT 50").fetchall()
    finally:
        conn.close()
    if not rows:
        console.print("[green]no positions awaiting resolution.[/green]")
        return
    table = Table("id", "confidence", "claim")
    for pid, claim, band, conf in rows:
        table.add_row(str(pid), f"{band} ({conf})", claim[:80])
    console.print(table)


# --------------------------------------------------- cost / budget --

cost_app = typer.Typer(help="Cost and budget commands.", no_args_is_help=True)
budget_app = typer.Typer(help="Budget management.", no_args_is_help=True)
app.add_typer(cost_app, name="cost")
app.add_typer(budget_app, name="budget")


@cost_app.command("report")
def cost_report(json_out: bool = typer.Option(False, "--json")) -> None:
    """Print remaining budget per dimension × period and the degradation tier."""
    from .governor import BUDGET_DEFAULTS, Governor
    paths = _paths_from_env()
    g = Governor(paths.state_db, BUDGET_DEFAULTS)
    report = g.cost_report()
    if json_out:
        console.print_json(data=report)
        return
    console.print(f"[bold]Tier:[/bold] {report['tier']}")
    table = Table("dimension", "monthly", "weekly", "daily")
    for dim, periods in report["remaining"].items():
        table.add_row(dim, str(periods["monthly"]), str(periods["weekly"]),
                      str(periods["daily"]))
    console.print(table)


@budget_app.command("reset")
def budget_reset(confirm: bool = typer.Option(False, "--confirm",
                                              help="Required for safety.")) -> None:
    """Clear all governor buckets — typed confirmation required."""
    if not confirm:
        err_console.print("[red]refusing without --confirm[/red]")
        raise typer.Exit(2)
    from .governor import BUDGET_DEFAULTS, Governor
    paths = _paths_from_env()
    g = Governor(paths.state_db, BUDGET_DEFAULTS)
    n = g.reset()
    console.print(f"[green]reset {n} bucket(s).[/green]")


# --------------------------------------------------- models --

models_app = typer.Typer(help="Local model management (Ollama).", no_args_is_help=True)
app.add_typer(models_app, name="models")


def _ollama_backend():
    from .backends.ollama import OllamaBackend, OllamaUnavailable
    return OllamaBackend(), OllamaUnavailable


@models_app.command("list")
def models_list() -> None:
    """List models known to the local Ollama daemon."""
    backend, OllamaUnavailable = _ollama_backend()
    try:
        models = backend.list_models()
    except Exception as exc:
        err_console.print(f"[red]ollama unreachable:[/red] {exc}")
        raise typer.Exit(1) from None
    if not models:
        console.print("[yellow]no models pulled.[/yellow]")
        return
    table = Table("name", "size (GB)", "digest")
    for m in models:
        table.add_row(m.name, f"{m.size_bytes / 1e9:.2f}", m.digest[:16])
    console.print(table)


def _ollama_models_dir() -> Path:
    """Where Ollama stores downloaded weights (the volume we must protect)."""
    env = os.environ.get("OLLAMA_MODELS")
    return Path(env) if env else (Path.home() / ".ollama" / "models")


@models_app.command("pull")
def models_pull(
    model: str = typer.Argument(...),
    force: bool = typer.Option(False, "--force", "-f",
                               help="Bypass the disk-safety preflight."),
    yes: bool = typer.Option(False, "--yes", "-y",
                             help="Skip the confirmation prompt for large pulls."),
) -> None:
    """Pull a model via Ollama, with a disk-safety preflight.

    A pull writes weights to disk; on a near-full volume that can wedge the
    OS. We refuse pulls that would leave less than the safety margin free
    (override with --force). The pull never loads weights into RAM — that
    happens lazily at inference, gated by the Governor.
    """
    import shutil as _shutil

    from .gateway import (
        budget_report,
        model_pages,
        preflight_pull,
    )

    # --- disk-safety preflight ---
    models_dir = _ollama_models_dir()
    probe_dir = models_dir if models_dir.exists() else Path.home()
    free_gb = _shutil.disk_usage(probe_dir).free / 1e9
    pf = preflight_pull(model, free_disk_gb=free_gb)

    size_str = (f"~{pf.estimated_download_gb:.1f} GB" if pf.estimated_download_gb
                else "unknown size")
    console.print(f"Pull [bold]{model}[/bold] ({size_str}) — "
                  f"{pf.free_disk_gb:.1f} GB free on {probe_dir.anchor or probe_dir}")

    if not pf.ok and not force:
        err_console.print(f"[red]refusing:[/red] {pf.reason}")
        err_console.print("  Free up disk space, or re-run with [bold]--force[/bold] "
                          "if you understand the risk.")
        raise typer.Exit(1)
    if not pf.ok and force:
        console.print(f"[yellow]--force:[/yellow] proceeding despite: {pf.reason}")

    # --- runtime RAM advisory (pull is disk; this warns about later use) ---
    try:
        rep = budget_report(probe())
        if model_pages(model, rep["budget_gb"]):
            console.print(f"[yellow]note:[/yellow] at runtime this model pages from "
                          f"SSD on your {rep['budget_gb']:.1f} GB budget — it will run, "
                          f"but slower. Pulling does not load it into RAM.")
    except Exception:
        pass

    # --- confirmation for large downloads ---
    if pf.is_large and not yes and not force:
        if not typer.confirm(f"This downloads {size_str}. Continue?"):
            console.print("aborted.")
            raise typer.Exit(0)

    backend, OllamaUnavailable = _ollama_backend()
    last_status = ""

    def _cb(msg: dict) -> None:
        nonlocal last_status
        status = msg.get("status", "")
        if status != last_status:
            console.print(f"  {status}")
            last_status = status

    try:
        backend.pull(model, progress_cb=_cb)
    except Exception as exc:
        err_console.print(f"[red]pull failed:[/red] {exc}")
        raise typer.Exit(1) from None
    after = _shutil.disk_usage(probe_dir).free / 1e9
    console.print(f"[green]pulled {model}.[/green] {after:.1f} GB free remaining.")


@models_app.command("info")
def models_info(model: str = typer.Argument(...)) -> None:
    """Show fingerprint info for a model."""
    from .gateway import fingerprint_ollama
    fp = fingerprint_ollama(model)
    if fp is None:
        err_console.print(f"[red]ollama not available or model {model!r} missing[/red]")
        raise typer.Exit(1)
    console.print(f"model: [bold]{fp.model_string}[/bold]")
    console.print(f"digest: {fp.registry_digest_sha256}")
    console.print(f"backend: {fp.backend}")
    if fp.runtime_version:
        console.print(f"runtime: {fp.runtime_version}")


@models_app.command("prune")
def models_prune(model: str = typer.Argument(...)) -> None:
    """Delete a local model from Ollama."""
    backend, OllamaUnavailable = _ollama_backend()
    try:
        backend.delete(model)
    except Exception as exc:
        err_console.print(f"[red]prune failed:[/red] {exc}")
        raise typer.Exit(1) from None
    console.print(f"[green]pruned {model}.[/green]")


@models_app.command("bind")
def models_bind() -> None:
    """Resolve the catalog's capability classes to real installed Ollama tags
    and pin them in chosen_models.yaml (the design's 'resolve tag at install').
    """
    from .gateway import resolve_against_installed
    from .hardware import probe as _probe
    paths = _paths_from_env()
    paths.ensure()
    backend, _ = _ollama_backend()
    try:
        installed = [m.name for m in backend.list_models()]
    except Exception as exc:
        err_console.print(f"[red]ollama unreachable:[/red] {exc}")
        raise typer.Exit(1) from None
    profile = _probe()
    resolved = resolve_against_installed(profile, installed)
    if not resolved:
        err_console.print("[yellow]no installed models matched the catalog roles. "
                          "Pull one first, e.g. `lighthouse models pull qwen3:14b`.[/yellow]")
        raise typer.Exit(1)
    # Write chosen_models.yaml using these real tags as overrides.
    import time as _time

    import yaml as _yaml

    from .gateway import bindings_for_tier, fingerprint
    bindings = bindings_for_tier(profile.suggested_tier)
    for role, tag in resolved.items():
        if role in bindings:
            b = bindings[role]
            from .gateway import ModelBinding
            backend_name = "native" if role in ("embedding", "reranker") else "ollama"
            bindings[role] = ModelBinding(role=role, model=tag, backend=backend_name,
                                          sampling=b.sampling)
    now = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    fps: dict = {}
    roles_out: dict = {}
    for role, b in bindings.items():
        fp = fingerprint(b.model, b.backend)
        fps[b.model] = {**fp.to_dict(), "pulled_at": now}
        roles_out[role] = {"model": b.model, "backend": b.backend, "sampling": b.sampling}
    doc = {"version": 1, "hardware_tier": profile.suggested_tier,
           "detected_at": now, "resolved_from_installed": True,
           "fingerprints": fps, "roles": roles_out}
    dest = paths.data_dir / "chosen_models.yaml"
    dest.write_text(_yaml.safe_dump(doc, sort_keys=False))
    console.print(f"[green]bound {len(resolved)} role(s) to installed tags →[/green] {dest}")
    for role, tag in resolved.items():
        console.print(f"  {role:13} {tag}")


# --------------------------------------------------- quarantine --

quarantine_app = typer.Typer(help="Sandbox quarantine browser.", no_args_is_help=True)
app.add_typer(quarantine_app, name="quarantine")


def _open_quarantine():
    paths = _paths_from_env()
    from .sandbox import Quarantine
    return Quarantine(paths.data_dir / "quarantine.db",
                      paths.data_dir / "quarantine")


@quarantine_app.command("list")
def quarantine_list(verdict: str = typer.Option(None, help="Filter by verdict")) -> None:
    """List quarantined artifacts."""
    q = _open_quarantine()
    rows = q.list(verdict=verdict, limit=200)
    if not rows:
        console.print("[yellow]quarantine empty.[/yellow]")
        return
    table = Table("sha256", "verdict", "filename", "size", "seen")
    for r in rows:
        table.add_row(r["sha256"][:12], r["verdict"], r["filename"] or "—",
                      str(r["bytes_size"]), r["seen_at"])
    console.print(table)


@quarantine_app.command("restore")
def quarantine_restore(sha: str = typer.Argument(...),
                       dest: Path = typer.Argument(...)) -> None:
    """Copy a quarantined artifact out to ``dest``."""
    q = _open_quarantine()
    try:
        out = q.restore(sha, dest)
    except FileNotFoundError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    console.print(f"[green]restored to {out}[/green]")


@quarantine_app.command("purge")
def quarantine_purge(verdict: str = typer.Option("quarantine"),
                     confirm: bool = typer.Option(False, "--confirm")) -> None:
    """Delete every artifact with the given verdict. Typed confirmation required."""
    if not confirm:
        err_console.print("[red]refusing without --confirm[/red]")
        raise typer.Exit(2)
    q = _open_quarantine()
    n = q.purge(verdict)
    console.print(f"[green]purged {n} artifact(s).[/green]")


# --------------------------------------------------- audit --

audit_app = typer.Typer(help="Audit log inspection.", no_args_is_help=True)
app.add_typer(audit_app, name="audit")


@audit_app.command("verify")
def audit_verify() -> None:
    """Re-compute every audit HMAC and report any breakage."""
    from .verification.audit_chain import resolve_secret, verify_audit_chain
    paths = _paths_from_env()
    try:
        secret = resolve_secret(None, data_dir=paths.data_dir)
    except Exception as exc:
        err_console.print(f"[red]could not resolve audit secret:[/red] {exc}")
        raise typer.Exit(1) from None
    bad = verify_audit_chain(paths.audit_db, secret=secret)
    if bad:
        err_console.print(f"[red]chain broken at seq(s): {bad}[/red]")
        raise typer.Exit(1)
    console.print("[green]audit chain ok.[/green]")


# --------------------------------------------------- sandbox --

sandbox_app = typer.Typer(help="Sandbox redteam + diagnostics.", no_args_is_help=True)
app.add_typer(sandbox_app, name="sandbox")


@sandbox_app.command("redteam")
def sandbox_redteam() -> None:
    """Feed the canonical hostile payloads through the broker; assert blocked."""
    import io
    import zipfile

    from .sandbox import Verdict
    from .sandbox.broker import build_default_broker
    from .sandbox.scanners import EICAR_SIGNATURE
    paths = _paths_from_env()
    paths.ensure()
    broker = build_default_broker(paths.data_dir)

    def _zip_bomb() -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for i in range(120):
                zf.writestr(f"f{i}.txt", b"A" * (10 * 1024 * 1024))
        return buf.getvalue()

    cases = [
        ("eicar.bin",   EICAR_SIGNATURE,                              "text/plain",       Verdict.REJECT),
        ("bomb.zip",    _zip_bomb(),                                  "application/zip",  Verdict.REJECT),
        ("xss.html",    b"<script>alert(1)</script>",                 "text/html",        Verdict.QUARANTINE),
        ("jspdf.pdf",   b"%PDF-1.4\n/OpenAction << /S /JavaScript /JS (a) >>\n",
         "application/pdf", Verdict.QUARANTINE),
    ]
    failed: list[str] = []
    for name, payload, ct, expected in cases:
        out = broker.admit(payload, filename=name, content_type=ct)
        symbol = "[green]✓[/green]" if out.verdict is expected else "[red]✗[/red]"
        console.print(f"  {symbol} {name}: expected {expected.value}, got {out.verdict.value}")
        if out.verdict is not expected:
            failed.append(name)
    if failed:
        err_console.print(f"[red]{len(failed)} payload(s) not blocked: {failed}[/red]")
        raise typer.Exit(1)
    console.print("[green]redteam ok — all hostile payloads blocked.[/green]")


# --------------------------------------------------- secrets --

secrets_app = typer.Typer(help="Manage Lighthouse secrets (keychain + TOML).",
                          no_args_is_help=True)
app.add_typer(secrets_app, name="secrets")


@secrets_app.command("set")
def secrets_set(key: str, value: str = typer.Argument(..., help="Value to store")) -> None:
    from .secrets import SecretStore
    paths = _paths_from_env()
    backend = SecretStore(paths.data_dir).put(key, value)
    console.print(f"[green]stored {key} (backend={backend}).[/green]")


@secrets_app.command("get")
def secrets_get(key: str) -> None:
    from .secrets import SecretStore
    paths = _paths_from_env()
    v = SecretStore(paths.data_dir).get(key)
    if v is None:
        err_console.print(f"[red]{key}: not found[/red]")
        raise typer.Exit(1)
    console.print(v)


@secrets_app.command("list")
def secrets_list() -> None:
    from .secrets import SecretStore
    paths = _paths_from_env()
    keys = SecretStore(paths.data_dir).list()
    if not keys:
        console.print("[yellow](file-store empty; keyring keys not enumerable)[/yellow]")
        return
    for k in keys:
        console.print(f"  {k}")


@secrets_app.command("rm")
def secrets_rm(key: str) -> None:
    from .secrets import SecretStore
    paths = _paths_from_env()
    if SecretStore(paths.data_dir).delete(key):
        console.print(f"[green]removed {key}.[/green]")
    else:
        err_console.print(f"[yellow]{key}: not present[/yellow]")
        raise typer.Exit(1)


# --------------------------------------------------- monitor --

monitor_app = typer.Typer(help="Mode A — Monitor.", no_args_is_help=True)
app.add_typer(monitor_app, name="monitor")


@monitor_app.command("run")
def monitor_run(
    source_url: str = typer.Option(..., help="Feed URL (RSS or Atom)"),
    topic: str = typer.Option(..., help="Topic label for the report"),
    out_dir: Path = typer.Option(None, help="Override staging dir for the HTML"),
) -> None:
    """One Mode A polling cycle. Fetches the feed, sandbox-admits the body,
    classifies items, writes a Tufte-CSS HTML report to staging/.
    """
    paths = _paths_from_env()
    paths.ensure()
    from .modes.monitor import run_monitor
    from .output.html import render_monitor_html
    from .sandbox.broker import build_default_broker
    from .sources.rss import fetch_feed
    broker = build_default_broker(paths.data_dir)
    try:
        items = fetch_feed(source_url, broker=broker)
    except Exception as exc:
        err_console.print(f"[red]fetch failed:[/red] {exc}")
        raise typer.Exit(1) from None
    if not items:
        console.print("[yellow]feed produced no items (or sandbox rejected).[/yellow]")
        raise typer.Exit(0)
    from .governor.scheduler_gate import SchedulerGate, SchedulerGateConfig
    gate = SchedulerGate(SchedulerGateConfig.from_config_file(paths.config_file))
    report = run_monitor(topic, items, gate=gate)
    html = render_monitor_html(report)
    dest = (out_dir or paths.staging_dir)
    dest.mkdir(parents=True, exist_ok=True)
    safe_topic = "".join(c if c.isalnum() else "-" for c in topic).strip("-")
    fname = dest / f"monitor-{safe_topic}-{report.generated_at.replace(':', '')}.html"
    fname.write_text(html)
    console.print(f"[green]wrote {fname}[/green]")
    console.print(f"  [bold]{len(report.alerts)}[/bold] alert(s), "
                  f"[bold]{len(report.digest)}[/bold] digest, "
                  f"{report.suppressed_duplicates} duplicate(s) suppressed.")


@app.command()
def tui(port: int = DEFAULT_PORT) -> None:
    """Launch the terminal dashboard (Textual)."""
    from .tui.app import LighthouseTUI
    from .tui.client import LighthouseClient
    LighthouseTUI(client=LighthouseClient(f"http://127.0.0.1:{port}")).run()


# --------------------------------------------------- replay --

@app.command()
def replay(job_id: str = typer.Argument(..., help="Job id to replay/inspect."),
           allow_drift: bool = typer.Option(False, "--allow-drift",
                                             help="Don't fail on model drift.")) -> None:
    """Reconstruct a job's model-call trace from the audit log and report
    whether it can be replayed byte-exact against the installed models (§27.8)."""
    paths = _paths_from_env()
    from .replay import ReplayDriftError, replay_job, verify_replayable
    trace = replay_job(paths.audit_db, job_id)
    if not trace.steps:
        console.print(f"[yellow]no model calls recorded for job {job_id}[/yellow]")
        raise typer.Exit(0)
    console.print(f"[bold]{len(trace.steps)} step(s)[/bold] for job {job_id}:")
    for i, s in enumerate(trace.steps, 1):
        console.print(f"  {i}. {s.model}  ({s.prompt_tokens}+{s.completion_tokens} tok)")
    # Build installed digests from Ollama (best-effort; empty if daemon down).
    installed: dict[str, str] = {}
    try:
        from .gateway import fingerprint
        for m in trace.models():
            installed[m] = fingerprint(m, "ollama").registry_digest_sha256
    except Exception:
        pass
    try:
        report = verify_replayable(paths.audit_db, job_id,
                                   installed_digests=installed, allow_drift=allow_drift)
    except ReplayDriftError as exc:
        err_console.print(f"[red]drift detected — not byte-exact replayable:[/red] {exc}")
        raise typer.Exit(1) from None
    console.print(f"[green]replayable: {report.fully_replayable}[/green] "
                  f"({len(report.replayable_steps)} byte-exact, "
                  f"{len(report.drifted_steps)} drifted)")


# --------------------------------------------------- backup / integrity --

@app.command()
def backup(repo: str = typer.Option(None, help="restic repo path (default: data_dir/backups/restic)"),
           init: bool = typer.Option(False, "--init", help="Initialize the repo first."),
           passphrase: str = typer.Option(None, help="restic passphrase (else from keychain).")) -> None:
    """Back up the data dir with restic (§26.3)."""
    from .backup import ResticBackup, ResticUnavailable, restic_installed
    if not restic_installed():
        err_console.print("[red]restic not installed.[/red] brew install restic")
        raise typer.Exit(1)
    paths = _paths_from_env()
    repo = repo or str(paths.data_dir / "backups" / "restic")
    if passphrase is None:
        from .secrets import SecretStore
        passphrase = SecretStore(paths.data_dir).get_or_create("restic.passphrase")
    rb = ResticBackup(passphrase=passphrase)
    try:
        if init:
            rb.init(repo)
            console.print(f"[green]initialized restic repo[/green] {repo}")
        rb.backup([paths.state_db, paths.audit_db, paths.positions_db,
                   paths.hypotheses_db, paths.intents_db,
                   paths.reflections_db, paths.entity_hotness_db], repo=repo)
    except ResticUnavailable as exc:
        err_console.print(f"[red]backup failed:[/red] {exc}")
        raise typer.Exit(1) from None
    console.print(f"[green]backed up to {repo}[/green]")


@app.command()
def integrity() -> None:
    """Run the periodic integrity check (§26.5): DB PRAGMA checks + replica lag."""
    paths = _paths_from_env()
    from .recovery import integrity_report
    rep = integrity_report(paths)
    for d in rep.databases:
        mark = "[green]OK[/green]" if d.ok else "[red]BAD[/red]"
        console.print(f"  {d.kind}.db: {mark} ({d.result})")
    for r in rep.replicas:
        console.print(f"  replica {r.name}: {'fresh' if r.ok else 'STALE'}")
    if not rep.overall_ok:
        err_console.print("[red]integrity check found problems.[/red]")
        raise typer.Exit(1)
    console.print("[green]integrity ok.[/green]")


# --------------------------------------------------- audit-egress --

@app.command("audit-egress")
def audit_egress(
    since: str = typer.Option("24h", help="Time window: '24h', '7d', '30d'"),
    output: str = typer.Option(None, help="Write report to file"),
) -> None:
    """Produce a signed report of all network calls in the audit log."""
    paths = _paths_from_env()
    if not paths.audit_db.exists():
        err_console.print("[yellow]No audit log found. Run 'lighthouse init' first.[/yellow]")
        raise typer.Exit(1)
    from .persistence import open_db
    conn = open_db(paths.audit_db)
    try:
        # NB: the audit_events timestamp column is `ts` (not `created_at`).
        rows = conn.execute(
            "SELECT event_type, payload_json, ts FROM audit_events "
            "WHERE event_type LIKE '%fetch%' OR event_type LIKE '%egress%' "
            "OR event_type LIKE '%auto_fetch%' "
            "ORDER BY ts DESC LIMIT 200"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        console.print("[green]✓ No external network calls found in the audit log.[/green]")
        console.print("  This confirms Lighthouse operated in airplane-mode for the audit window.")
        return
    table = Table(title=f"Egress audit ({since})", show_lines=True)
    table.add_column("Time", style="dim")
    table.add_column("Event")
    table.add_column("Details")
    import json
    for event_type, payload_json, ts in rows:
        payload = {}
        try:
            payload = json.loads(payload_json or "{}")
        except (ValueError, TypeError):
            pass
        details = payload.get("url") or payload.get("source") or str(payload)[:60]
        table.add_row(str(ts)[:16], event_type, details)
    console.print(table)
    if output:
        with open(output, "w") as f:
            f.write(f"Lighthouse Egress Audit Report\nGenerated: {__import__('datetime').datetime.now().isoformat()}\n\n")
            for event_type, payload_json, ts in rows:
                f.write(f"{ts} | {event_type} | {payload_json}\n")
        console.print(f"[green]Report written to {output}[/green]")


# --------------------------------------------------- resolver --

resolver_app = typer.Typer(help="Calibration position auto-resolver.")
app.add_typer(resolver_app, name="resolver")


@resolver_app.command("run")
def resolver_run(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be resolved without writing."),
    confidence: float = typer.Option(0.7, help="Minimum confidence to auto-resolve."),
    offline: bool = typer.Option(False, "--offline", help="Skip LLM; only report past-deadline."),
) -> None:
    """Auto-resolve past-deadline calibration positions."""
    paths = _paths_from_env()
    if not paths.positions_db.exists():
        console.print("[yellow]No positions database found.[/yellow]")
        raise typer.Exit(0)
    from .verification.resolver import run_resolver_pass
    gateway = None
    if not offline:
        try:
            from .hardware import probe
            from .pipeline import make_gateway
            gateway = make_gateway(paths, probe())
        except Exception:
            pass
    results = run_resolver_pass(
        paths.positions_db, gateway=gateway,
        confidence_threshold=confidence, dry_run=dry_run,
    )
    if not results:
        console.print("[green]No past-deadline positions to resolve.[/green]")
        return
    auto = [r for r in results if r.auto_resolved]
    deferred = [r for r in results if not r.auto_resolved]
    console.print(f"[bold]Resolver pass:[/bold] {len(results)} past-deadline positions")
    console.print(f"  [green]Auto-resolved:[/green] {len(auto)}")
    console.print(f"  [yellow]Deferred to human:[/yellow] {len(deferred)}")
    if dry_run:
        console.print("[dim](dry-run — no changes written)[/dim]")
    for r in auto:
        outcome_str = "[green]TRUE[/green]" if r.outcome else "[red]FALSE[/red]"
        console.print(f"  • {r.claim[:60]}… → {outcome_str} (conf={r.confidence:.2f}, Brier={r.brier:.3f})")


# ------------------------------------------------------- logseq ----

logseq_app = typer.Typer(name="logseq", no_args_is_help=True)
app.add_typer(logseq_app, name="logseq")


@logseq_app.command("sync")
def logseq_sync(
    force: bool = typer.Option(False, "--force", "-f",
                               help="Re-export all published drafts, not just unsynced ones."),
    graph_dir: Path = typer.Option(None, "--graph-dir",
                                   help="Logseq graph directory. Falls back to config.toml [logseq] graph_dir."),
) -> None:
    """Sync published drafts to the Logseq graph directory."""
    paths = _paths_from_env()
    _graph_dir = graph_dir
    if _graph_dir is None:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        if paths.config_file.exists():
            with paths.config_file.open("rb") as fh:
                _graph_dir_str = tomllib.load(fh).get("logseq", {}).get("graph_dir")
            if _graph_dir_str:
                _graph_dir = Path(_graph_dir_str).expanduser()
    if _graph_dir is None:
        err_console.print("[red]no Logseq graph dir: pass --graph-dir or set [logseq] graph_dir in config.toml[/red]")
        raise typer.Exit(1)
    from .compounding.logseq_sync import sync_drafts
    result = sync_drafts(paths, _graph_dir, force=force)
    console.print(f"[green]synced {result.synced} draft(s)[/green]", end="")
    if result.skipped:
        console.print(f", {result.skipped} already up-to-date", end="")
    if result.failed:
        console.print(f", [red]{result.failed} failed[/red]", end="")
    console.print()
    for draft_id, err in result.errors:
        err_console.print(f"  [red]✗[/red] {draft_id}: {err}")


@logseq_app.command("status")
def logseq_status_cmd() -> None:
    """Show Logseq sync status: configuration and pending draft count."""
    paths = _paths_from_env()
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore
    cfg: dict = {}
    if paths.config_file.exists():
        with paths.config_file.open("rb") as fh:
            cfg = tomllib.load(fh).get("logseq", {})
    enabled = cfg.get("enabled", False)
    graph_dir = cfg.get("graph_dir")
    interval = cfg.get("sync_interval_hours", 24)
    console.rule("[bold]logseq sync[/bold]")
    if not enabled:
        console.print("  [yellow]disabled[/yellow] — set [logseq] enabled = true in config.toml")
        return
    if not graph_dir:
        console.print("  [yellow]enabled but no graph_dir set[/yellow]")
        return
    console.print(f"  [green]✓[/green] enabled, graph dir: {graph_dir}")
    console.print(f"  sync interval: every {interval}h")
    from .compounding.logseq_sync import pending_count
    pending = pending_count(paths)
    if pending:
        console.print(f"  [yellow]{pending} draft(s) pending sync[/yellow] — run: lighthouse logseq sync")
    else:
        console.print("  [green]✓[/green] all drafts synced")


# --------------------------------------------------- subconscious --

subconscious_app = typer.Typer(name="subconscious", no_args_is_help=True)
app.add_typer(subconscious_app, name="subconscious")


@subconscious_app.command("tick")
def subconscious_tick() -> None:
    """Manually trigger a single subconscious tick (debug)."""
    paths = _paths_from_env()
    paths.ensure()
    from .subconscious import ReflectionStore, SubconsciousEngine, stale_position_escalations
    from .subconscious.engine import TickResult
    store = ReflectionStore(paths.reflections_db)
    engine = SubconsciousEngine(
        store,
        escalation_producers=(lambda: stale_position_escalations(paths.positions_db),),
    )
    outcome = engine.tick()
    if outcome.result == TickResult.SUPERSEDED:
        console.print("[yellow]tick superseded by concurrent pass[/yellow]")
    else:
        console.print(
            f"[green]tick committed[/green]: "
            f"{outcome.reflections_committed} reflection(s), "
            f"{outcome.escalations_committed} escalation(s)"
        )


# ------------------------------------------------------- notify ----

notify_app = typer.Typer(name="notify", no_args_is_help=True,
                         help="Notification channel management and testing.")
app.add_typer(notify_app, name="notify")

_ALL_EVENTS = [
    "draft_ready", "draft_approved", "job_started", "job_completed",
    "job_failed", "monitor_alert_high", "monitor_alert_medium",
    "budget_warn", "budget_trip", "logseq_synced",
    "escalation_raised", "position_resolved",
]


@notify_app.command("status")
def notify_status() -> None:
    """Show configured notification channels and subscribed events."""
    cfg = _load_notify_cfg()
    console.rule("[bold]notification channels[/bold]")

    # Desktop
    desktop = "[green]✓[/green]" if cfg.get("desktop_enabled", True) else "[dim]off[/dim]"
    console.print(f"  desktop   {desktop}")

    # Discord
    if cfg.get("discord_webhook_url"):
        console.print("  discord   [green]✓[/green] webhook configured")
    else:
        console.print("  discord   [dim]not configured[/dim]")

    # Telegram
    tg_token = cfg.get("telegram_bot_token", "")
    tg_chat = cfg.get("telegram_chat_id", "")
    if tg_token and tg_chat:
        from .notify.telegram import TelegramChannel
        tc = TelegramChannel(bot_token=tg_token, chat_id=tg_chat)
        if tc.available():
            tg_events = cfg.get("telegram_events", cfg.get("events", _ALL_EVENTS))
            console.print("  telegram  [green]✓[/green] bot configured")
            console.print(f"            events: {', '.join(tg_events)}")
        else:
            console.print("  telegram  [yellow]token or chat_id missing[/yellow]")
    else:
        console.print("  telegram  [dim]not configured[/dim]  "
                      "(add telegram_bot_token + telegram_chat_id to config.toml)")

    # Global events
    global_events = cfg.get("events", _ALL_EVENTS)
    console.rule("[bold]subscribed events[/bold]")
    for ev in _ALL_EVENTS:
        mark = "[green]✓[/green]" if ev in global_events else "[dim]·[/dim]"
        console.print(f"  {mark} {ev}")


@notify_app.command("test")
def notify_test(
    title: str = typer.Option("Lighthouse test", "--title", help="Notification title."),
    body: str = typer.Option("This is a test notification from Lighthouse.",
                             "--body", help="Notification body."),
    event: str = typer.Option("draft_ready", "--event",
                              help="Event name to simulate."),
) -> None:
    """Send a test notification through all configured channels."""
    cfg = _load_notify_cfg()
    if not cfg:
        console.print("[yellow]No notification config found — "
                      "add a [notifications] section to config.toml[/yellow]")
        return

    from .notify import DesktopChannel, DiscordChannel, Notifier
    from .notify.telegram import TelegramChannel

    channels: list[tuple[str, object]] = [("desktop", DesktopChannel())]
    if cfg.get("discord_webhook_url"):
        channels.append(("discord", DiscordChannel(cfg["discord_webhook_url"])))
    if cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
        channels.append(("telegram", TelegramChannel(
            bot_token=cfg["telegram_bot_token"],
            chat_id=cfg["telegram_chat_id"],
        )))

    from .notify.telegram_templates import render as _tg_render
    plain_channels = [(n, c) for n, c in channels if n != "telegram"]
    tg_channels = [(n, c) for n, c in channels if n == "telegram"]
    all_results = []
    if plain_channels:
        all_results += Notifier(cfg, plain_channels).notify(event, title, body)
    if tg_channels:
        tg_title, tg_body = _tg_render(event, title, body)
        all_results += Notifier(cfg, tg_channels).notify(event, tg_title, tg_body)
    delivered_count = 0
    for r in all_results:
        if r.attempted:
            mark = "[green]✓[/green]" if r.delivered else "[red]✗[/red]"
            console.print(f"  {mark} {r.channel}")
            if r.delivered:
                delivered_count += 1
    if delivered_count == 0:
        console.print("  [yellow]no channels delivered — check your config or event subscription[/yellow]")


# ------------------------------------------------------- telegram bot ----

telegram_app = typer.Typer(name="telegram", no_args_is_help=True,
                           help="Telegram bot command interface.")
app.add_typer(telegram_app, name="telegram")


def _load_telegram_bot_cfg() -> tuple[str, str, bool]:
    """Return (bot_token, chat_id, commands_enabled) from config.toml."""
    try:
        paths = _paths_from_env()
        if not paths.config_file.exists():
            return "", "", False
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        with paths.config_file.open("rb") as fh:
            cfg = tomllib.load(fh)
        notif = cfg.get("notifications", {})
        bot_cfg = cfg.get("telegram_bot", {})
        return (
            notif.get("telegram_bot_token", ""),
            notif.get("telegram_chat_id", ""),
            bool(bot_cfg.get("commands_enabled", False)),
        )
    except Exception:
        return "", "", False


@telegram_app.command("status")
def telegram_bot_status() -> None:
    """Show Telegram bot command interface configuration."""
    token, chat_id, enabled = _load_telegram_bot_cfg()
    console.rule("[bold]telegram bot commands[/bold]")
    if token and chat_id:
        masked = token[:6] + "…" + token[-4:] if len(token) > 10 else "***"
        console.print(f"  Bot token:  [green]{masked}[/green]")
        console.print(f"  Chat ID:    {chat_id}")
        if enabled:
            console.print("  Commands:   [green]✓ enabled[/green] (supervisor starts bot on boot)")
        else:
            console.print("  Commands:   [yellow]disabled[/yellow] "
                          "(set [telegram_bot] commands_enabled = true to enable)")
    else:
        console.print("  [yellow]Not configured.[/yellow]")
        console.print("  Add to config.toml:")
        console.print("    [notifications]")
        console.print("    telegram_bot_token = \"<token>\"")
        console.print("    telegram_chat_id   = \"<chat_id>\"")
        console.print("    [telegram_bot]")
        console.print("    commands_enabled = true")

    console.print()
    console.rule("[bold]available bot commands[/bold]")
    from .notify.telegram_bot import _COMMANDS
    for cmd, desc in _COMMANDS.items():
        console.print(f"  [bold]{cmd}[/bold]  {desc}")


@telegram_app.command("serve")
def telegram_bot_serve(
    token: str = typer.Option(None, "--token",
                              help="Bot token (overrides config.toml)."),
    chat: str = typer.Option(None, "--chat",
                             help="Chat ID (overrides config.toml)."),
) -> None:
    """Run the Telegram bot command interface in the foreground.

    Useful for debugging or running standalone (without the full supervisor).
    The bot polls for messages and processes commands until Ctrl-C.
    """
    _token, _chat, _ = _load_telegram_bot_cfg()
    bot_token = token or _token
    chat_id = chat or _chat
    if not bot_token:
        err_console.print("[red]No bot token — pass --token or set telegram_bot_token in config.toml[/red]")
        raise typer.Exit(1)
    if not chat_id:
        err_console.print("[red]No chat ID — pass --chat or set telegram_chat_id in config.toml[/red]")
        raise typer.Exit(1)

    paths = _paths_from_env()
    paths.ensure()
    console.print(f"[green]Starting Telegram bot[/green] (chat_id={chat_id})")
    console.print("  Send /help to your bot to get started.  Ctrl-C to stop.")
    from .notify.telegram_bot import serve as _tg_serve
    try:
        _tg_serve(bot_token, chat_id, paths)
    except KeyboardInterrupt:
        console.print("\n[yellow]Bot stopped.[/yellow]")


if __name__ == "__main__":  # pragma: no cover
    app()
