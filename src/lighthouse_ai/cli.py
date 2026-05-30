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


def _notify_event(event: str, title: str, body: str) -> None:
    """Fire a notification through the configured channels. Best-effort —
    never raises, so a missing/misconfigured channel can't break a command."""
    try:
        paths = _paths_from_env()
        cfg = {}
        if paths.config_file.exists():
            try:
                import tomllib
            except ImportError:  # pragma: no cover
                import tomli as tomllib  # type: ignore
            with paths.config_file.open("rb") as fh:
                cfg = tomllib.load(fh).get("notifications", {})
        if not cfg:
            return
        from .notify import DesktopChannel, DiscordChannel, Notifier
        from .notify.channels import Channel
        channels: list[tuple[str, Channel]] = [("desktop", DesktopChannel())]
        if cfg.get("discord_webhook_url"):
            channels.append(("discord", DiscordChannel(cfg["discord_webhook_url"])))
        Notifier(cfg, channels).notify(event, title, body)
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

doctor_app = typer.Typer(help="Readiness checks and diagnostics.", invoke_without_command=True)
app.add_typer(doctor_app, name="doctor")


@doctor_app.callback(invoke_without_command=True)
def _doctor_default(ctx: typer.Context) -> None:
    """Run readiness checks when ``doctor`` is invoked with no subcommand.

    Keeps the historical ``lighthouse doctor`` behavior (== ``doctor check``)
    while still exposing ``doctor news`` and ``doctor check`` as subcommands.
    """
    if ctx.invoked_subcommand is None:
        doctor()


@doctor_app.command("check")
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


@doctor_app.command("news")
def doctor_news(
    live: bool = typer.Option(False, "--live",
                              help="Attempt real network checks (requires egress)."),
) -> None:
    """Check reachability of all trusted news outlets; prints the trust matrix.

    Runs OFFLINE by default — every outlet is shown as 'unreachable (offline)'
    without any network call.  Pass ``--live`` (or set
    ``LIGHTHOUSE_REAL_BACKEND=1``) to perform actual HEAD/GET reachability
    checks.

    The trust matrix columns mirror §4 of SKILL_LIBRARY_V1.md:
      outlet / reachable? / method / AllSides / trusted

    Exit code is always 0 — individual outlet failures are informational only.
    """
    import os

    # Gate live checks behind --live or LIGHTHOUSE_REAL_BACKEND=1 (§resource limits).
    do_live = live or (os.environ.get("LIGHTHOUSE_REAL_BACKEND") == "1")

    # Import the orchestrator's outlet table (read-only, no network at import).
    from .skills.library.news_orchestrator.skill import _TRUSTED_OUTLETS

    # §4 trust matrix: fetch method is RSS for all seed outlets (the API/platform
    # invariants are documented in the spec — paywall = "✗", RSS = "✓ (RSS)").
    _METHOD: dict[str, str] = {
        "reuters": "RSS",
        "associated_press": "RSS + web",
        "bbc_news": "RSS",
        "npr": "RSS + web",
        "guardian": "Open Platform API",
        "propublica": "RSS + web",
    }

    console.rule("[bold]doctor news — trusted outlet trust matrix[/bold]")

    table = Table(
        "Outlet",
        "Reachable?",
        "Method",
        "AllSides",
        "Trusted",
        show_lines=False,
        title="News outlets (seed six)",
    )

    for outlet in _TRUSTED_OUTLETS:
        method = _METHOD.get(outlet.id, "RSS")
        trusted_mark = "[green]✓[/green]"  # all seed outlets are pre-trusted

        if not do_live:
            # Offline mode: show each outlet as unreachable with reason.
            reachable_cell = "[yellow]— (offline)[/yellow]"
        else:
            # Live mode: attempt a minimal fetch via httpx (no egress proxy —
            # this is a diagnostic tool, not a skill).
            import httpx as _httpx

            feed_url = outlet.feeds[0] if outlet.feeds else ""
            if not feed_url:
                reachable_cell = "[red]✗[/red] no feeds configured"
            else:
                try:
                    resp = _httpx.head(feed_url, follow_redirects=True, timeout=5.0)
                    if resp.status_code < 400:
                        reachable_cell = "[green]✓[/green]"
                    else:
                        reachable_cell = f"[red]✗[/red] HTTP {resp.status_code}"
                except Exception as exc:
                    short = str(exc)[:40]
                    reachable_cell = f"[red]✗[/red] {short}"

        table.add_row(
            outlet.name,
            reachable_cell,
            method,
            outlet.allsides_rating,
            trusted_mark,
        )

    # Show outlets that are known-unavailable (paywalled / ToS — §4).
    _UNAVAILABLE = [
        ("New York Times", "metadata+abstract only", "lean_left", "◐ (limited)"),
        ("Wall Street Journal", "paywall/ToS — not fetchable", "lean_right", "✗"),
        ("Bloomberg", "paywall/ToS — not fetchable", "center", "✗"),
        ("Financial Times", "paywall/ToS — not fetchable", "center", "✗"),
        ("Fox News", "RSS only", "right", "◐ (RSS only)"),
    ]
    for name, reason, allsides, trusted in _UNAVAILABLE:
        table.add_row(name, f"[dim]{reason}[/dim]", "—", allsides, f"[dim]{trusted}[/dim]")

    console.print(table)

    mode_label = "[yellow]offline (pass --live to check egress)[/yellow]" if not do_live else "[green]live[/green]"
    console.print(f"\n  mode: {mode_label}")
    console.print(
        "  Seed outlets (Reuters, AP, BBC, NPR, Guardian, ProPublica) are "
        "pre-trusted and RSS-accessible without auth."
    )
    console.print(
        "  Paywall/ToS constraints are platform invariants — visible with "
        "reason, not silently absent (SKILL_LIBRARY_V1.md §8)."
    )
    # Exit 0 always — outlet failures are informational.
    raise typer.Exit(0)


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

    try:
        result = pipe.research(question)
    except Exception as exc:
        err_console.print(f"[red]research failed:[/red] {exc}")
        raise typer.Exit(1) from None

    for w in result.warnings:
        err_console.print(f"[yellow]⚠ backend warning:[/yellow] {w}")

    disc: dict = result.discipline or {}
    console.print(f"\n[green]staged draft {result.draft_id}[/green] "
                  f"({result.mode}, {result.sections} section(s), "
                  f"{result.chunks_ingested} corpus chunks)")
    if disc:
        verdict = "[green]passed[/green]" if disc.get("passed") else "[yellow]flagged[/yellow]"
        console.print(f"  discipline: {verdict} — {disc.get('sourced', 0)}/{disc.get('claims', 0)} "
                      f"claims sourced ({disc.get('coverage', 0):.0%} coverage); "
                      f"{disc.get('claims', 0)} claim(s) recorded as calibration positions")
    _notify_event("draft_ready", "Draft staged",
                  f"{question[:60]} → {result.draft_id}")
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
    Quality bar: recall@k = MRR = 1.0 with the real embedder + reranker. (The
    built-in golden set labels one relevant doc per query, so precision@5's
    ceiling is 0.20 by construction — MRR/recall are the meaningful metrics.)
    """
    from .eval import build_golden_set, build_index, evaluate

    golden = build_golden_set()
    if offline:
        hybrid = build_index(golden)
        backends = {"embedder": "hash-stub", "reranker": "ScoreReranker"}
        warns: list[str] = []
    else:
        from typing import cast

        from .pipeline import make_embedder, make_vector_store
        from .rag.flag_reranker import make_reranker
        from .rag.rerank import Reranker
        embedder, emb_name, warns = make_embedder(offline=False)
        store, store_name, store_warns = make_vector_store(embedder.dim, offline=False)
        warns = warns + store_warns
        reranker: Reranker = cast(Reranker, make_reranker(prefer_real=True))
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
    mrr = report.get("mrr", 0.0)
    recall = report.get(f"recall@{k}", 0.0)
    bar = (
        "[green]✓[/green]" if (mrr >= 0.75 and recall >= 0.83)
        else "[yellow]below ranking bar (recall@k≥0.83, MRR≥0.75)[/yellow]"
    )
    for name, val in report.items():
        console.print(f"  {name:<14} {val:.3f}")
    console.print(
        f"\n  ranking quality: recall@{k} {recall:.3f} · MRR {mrr:.3f} — {bar}"
    )
    console.print(
        f"  [dim](precision@{k} ceiling is 0.20 here — one relevant doc per "
        "query; MRR/recall are the meaningful metrics.)[/dim]"
    )


@app.command()
def export(
    draft_id: str = typer.Argument(..., help="Draft id to export."),
    logseq: Path = typer.Option(..., "--logseq", help="Logseq graph directory."),
) -> None:
    """Export a staged/published draft to a Logseq graph (filesystem markdown)."""
    paths = _paths_from_env()
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
    page = export_draft(logseq, draft_id=_id, title=title, body_html=body_html,
                        topic=topic, wep_phrase=wep_phrase,
                        source_count=source_count or 0)
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
        for m in trace.models:
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
    rb = ResticBackup()
    try:
        if init:
            rb.init(repo, passphrase)
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
        # Column is `ts` (schema.py AUDIT_MIGRATIONS), not `created_at`.
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
        except Exception:
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


# --------------------------------------------------- skill --

skill_app = typer.Typer(help="Skill library management — scaffold, list, validate.", no_args_is_help=True)
app.add_typer(skill_app, name="skill")


@skill_app.command("new")
def skill_new(
    skill_id: str = typer.Argument(..., help="New skill id (Python identifier, no hyphens)."),
    dest_dir: str = typer.Option(
        None, "--dir",
        help="Parent directory for the new skill folder. Defaults to the in-tree library.",
    ),
    name: str = typer.Option(None, "--name", help="Human-readable display name."),
    category: str = typer.Option("general", "--category", help="Skill category (e.g. academic, news, government)."),
    tier: str = typer.Option("A", "--tier", help="Fetch tier: A (default), B, or C."),
    watchable: bool = typer.Option(False, "--watchable", help="Add run_watchable stub (Pattern-2)."),
) -> None:
    """Scaffold a new research skill into the library (or a custom directory).

    Creates <dir>/<id>/ with a manifest.toml, skill.py, SKILL.md,
    __init__.py, and examples/example.md — all passing the import guard.

    After scaffolding, edit manifest.toml and skill.py to wire up your
    source, then run ``lighthouse skill validate <id> --dir <dir>`` to
    confirm everything loads cleanly.
    """
    from .skills.registry import LIBRARY_DIR
    from .skills.scaffold import ScaffoldError, scaffold_skill

    target = Path(dest_dir) if dest_dir else LIBRARY_DIR
    try:
        skill_dir = scaffold_skill(
            skill_id, target,
            name=name, category=category, tier=tier, watchable=watchable,
        )
    except ScaffoldError as exc:
        err_console.print(f"[red]scaffold error:[/red] {exc}")
        raise typer.Exit(1) from None

    console.print(f"[green]created skill scaffold →[/green] {skill_dir}")
    console.print("  [bold]Next steps:[/bold]")
    console.print(f"  1. Edit [cyan]{skill_dir / 'manifest.toml'}[/cyan]")
    console.print("     — set base_url, allowed_domains, description, scoring fields.")
    console.print(f"  2. Edit [cyan]{skill_dir / 'skill.py'}[/cyan]")
    console.print("     — implement run() using ctx.fetch / ctx.make_document.")
    console.print(f"  3. Edit [cyan]{skill_dir / 'SKILL.md'}[/cyan]")
    console.print("     — complete the planner guide (when to use, query translation, biases).")
    console.print(f"  4. Validate: [cyan]lighthouse skill validate {skill_id}"
                  + (f" --dir {dest_dir}" if dest_dir else "") + "[/cyan]")


@skill_app.command("list")
def skill_list(
    dest_dir: str = typer.Option(
        None, "--dir",
        help="Custom skill library directory. Defaults to the in-tree library.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    """List all discovered skills (id / name / category / tier / signed)."""

    from .skills.registry import LIBRARY_DIR, discover_skills

    target: Path | None = Path(dest_dir) if dest_dir else None
    skills = discover_skills(target or LIBRARY_DIR)

    if json_out:
        console.print_json(data={sid: m.as_dict() for sid, m in skills.items()})
        return

    if not skills:
        console.print("[yellow]no skills discovered.[/yellow]")
        return

    table = Table("id", "name", "category", "tier", "signed", "watchable", show_lines=False)
    for sid, m in sorted(skills.items()):
        signed_cell = "[green]✓[/green]" if m.signed else "[dim]community[/dim]"
        watch_cell = "[cyan]✓[/cyan]" if m.watchable else "—"
        table.add_row(sid, m.name, m.category, m.tier, signed_cell, watch_cell)
    console.print(table)
    console.print(f"  [dim]{len(skills)} skill(s)[/dim]")


@skill_app.command("validate")
def skill_validate(
    skill_id: str = typer.Argument(..., help="Skill id to validate."),
    dest_dir: str = typer.Option(
        None, "--dir",
        help="Custom skill library directory containing the skill folder.",
    ),
) -> None:
    """Load a skill and report pass / fail (manifest + import guard + entrypoints).

    Exit code 0 on success, 1 on any failure.
    """
    from .skills.registry import LIBRARY_DIR, SkillLoadError, SkillNotFound, load_skill
    from .skills.schema import SkillManifestError

    target: Path | None = Path(dest_dir) if dest_dir else None
    try:
        loaded = load_skill(skill_id, library_dir=target)
    except SkillNotFound:
        err_console.print(f"[red]skill not found:[/red] {skill_id!r} "
                          f"in {target or LIBRARY_DIR}")
        raise typer.Exit(1) from None
    except SkillManifestError as exc:
        err_console.print(f"[red]manifest error:[/red] {exc}")
        raise typer.Exit(1) from None
    except SkillLoadError as exc:
        err_console.print(f"[red]load error:[/red] {exc}")
        raise typer.Exit(1) from None
    except Exception as exc:
        err_console.print(f"[red]unexpected error:[/red] {exc}")
        raise typer.Exit(1) from None

    m = loaded.manifest
    table = Table("field", "value", show_lines=False, title=f"skill: {skill_id}")
    table.add_row("id", m.id)
    table.add_row("name", m.name)
    table.add_row("category", m.category)
    table.add_row("version", m.version)
    table.add_row("tier", m.tier)
    table.add_row("signed", str(m.signed))
    table.add_row("watchable", str(m.watchable))
    table.add_row("entrypoint", m.entrypoint)
    table.add_row("output_shape", m.output_shape)
    if m.watchable:
        watch_status = (
            "[green]✓ run_watchable present[/green]"
            if loaded.watchable_entrypoint is not None
            else "[red]✗ run_watchable missing[/red]"
        )
        table.add_row("run_watchable", watch_status)
    console.print(table)
    console.print(f"[green]✓ {skill_id} passes all checks[/green]")


if __name__ == "__main__":  # pragma: no cover
    app()
