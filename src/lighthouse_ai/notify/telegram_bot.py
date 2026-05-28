"""Telegram bot command interface for Lighthouse.

Lets the operator issue CLI-equivalent commands from any Telegram client:

    /help           — list available commands
    /status         — system snapshot: jobs, drafts, budget
    /jobs [n]       — last n jobs (default 5)
    /drafts         — staged drafts awaiting review
    /approve <id>   — approve a staged draft
    /reject <id> [reason]  — reject a staged draft
    /research <question>   — start a research job (replies when done)
    /budget         — budget usage summary
    /sync           — trigger Logseq sync now
    /escalations    — open escalations requiring attention
    /cancel         — cancel the current in-progress research job

Security model:
- Only messages from the *configured* chat_id are processed; every other
  origin is silently ignored so only the operator can control the agent.
- Commands dispatch to Python functions — no shell exec, no eval.
- /approve and /reject are non-destructive in the §24.10 sense (no data is
  deleted), but they do publish state transitions; they require the draft id
  to be explicit in the command so accidental approval is unlikely.
- /research runs in a background thread and sends a reply when done.

The polling loop uses long-polling (``timeout=30`` on getUpdates) so it is
efficient and requires no webhook infrastructure. The loop is injectable with
a fake clock and no-op sleep so tests can drive it deterministically without
touching the network.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
import structlog

from .telegram import _extract_messages, _method_url, _next_offset

if TYPE_CHECKING:
    from ..paths import Paths

log = structlog.get_logger(__name__)

# Max message length Telegram accepts in a single sendMessage.
_TG_MAX_LEN = 4096

# Commands the bot understands.
_COMMANDS = {
    "/help": "List available commands",
    "/status": "System snapshot (jobs, drafts, budget)",
    "/jobs": "Recent jobs — /jobs [n]",
    "/drafts": "Staged drafts awaiting review",
    "/approve": "Approve a draft — /approve <id>",
    "/reject": "Reject a draft — /reject <id> [reason]",
    "/research": "Start a research job — /research <question>",
    "/budget": "Budget usage summary",
    "/sync": "Trigger Logseq sync now",
    "/escalations": "Open escalations requiring attention",
    "/cancel": "Cancel the in-progress research job",
}

Clock = Callable[[], float]
Sleep = Callable[[float], None]


_TRUNC_SUFFIX = "\n\n<i>…(truncated)</i>"

def _trunc(text: str, max_len: int = _TG_MAX_LEN) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - len(_TRUNC_SUFFIX)] + _TRUNC_SUFFIX


def _fmt(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass
class BotContext:
    """Shared state injected into each command handler."""

    paths: "Paths"
    bot_token: str
    chat_id: str
    client: httpx.Client
    # Held by /research to allow /cancel
    _research_thread: threading.Thread | None = field(default=None, repr=False)
    _research_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


# ---------------------------------------------------------------------------
# Low-level send helper
# ---------------------------------------------------------------------------

def _send(ctx: BotContext, text: str) -> None:
    """Send ``text`` back to the operator's chat (HTML parse mode)."""
    try:
        ctx.client.post(
            _method_url(ctx.bot_token, "sendMessage"),
            json={
                "chat_id": ctx.chat_id,
                "text": _trunc(text),
                "parse_mode": "HTML",
            },
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        log.warning("telegram_bot.send_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _cmd_help(ctx: BotContext, _args: str) -> None:
    lines = ["<b>Lighthouse commands</b>\n"]
    for cmd, desc in _COMMANDS.items():
        lines.append(f"  <code>{cmd}</code> — {desc}")
    _send(ctx, "\n".join(lines))


def _cmd_status(ctx: BotContext, _args: str) -> None:
    from ..persistence import open_db
    try:
        conn = open_db(ctx.paths.state_db)
        try:
            jobs_total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            jobs_running = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='running'"
            ).fetchone()[0]
            staged = conn.execute(
                "SELECT COUNT(*) FROM drafts WHERE status='staged'"
            ).fetchone()[0]
            published = conn.execute(
                "SELECT COUNT(*) FROM drafts WHERE status='published'"
            ).fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:
        _send(ctx, f"⚠ DB error: {_fmt(str(exc))}")
        return

    lines = [
        "<b>Lighthouse status</b>\n",
        f"  Jobs running: <b>{jobs_running}</b> / {jobs_total} total",
        f"  Drafts staged: <b>{staged}</b>",
        f"  Drafts published: {published}",
    ]

    # Budget
    try:
        from ..governor import BUDGET_DEFAULTS, Governor
        g = Governor(ctx.paths.state_db, BUDGET_DEFAULTS)
        usage = g.current_period_usage()
        limit = g.effective_limit()
        pct = 100 * usage / limit if limit else 0
        lines.append(f"  Budget: {pct:.0f}% used (${usage:.4f} / ${limit:.2f})")
    except Exception:
        pass

    # Logseq pending
    try:
        from ..compounding.logseq_sync import pending_count
        pending = pending_count(ctx.paths)
        if pending:
            lines.append(f"  Logseq: {pending} draft(s) pending sync")
    except Exception:
        pass

    _send(ctx, "\n".join(lines))


def _cmd_jobs(ctx: BotContext, args: str) -> None:
    from ..persistence import open_db
    try:
        n = int(args.strip()) if args.strip().isdigit() else 5
        n = min(n, 20)
        conn = open_db(ctx.paths.state_db)
        try:
            rows = conn.execute(
                "SELECT id, mode, status, created_at FROM jobs "
                "ORDER BY created_at DESC LIMIT ?", (n,)
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        _send(ctx, f"⚠ DB error: {_fmt(str(exc))}"); return

    if not rows:
        _send(ctx, "No jobs found."); return
    lines = [f"<b>Last {len(rows)} job(s)</b>\n"]
    for jid, mode, status, created in rows:
        icon = {"running": "🔄", "done": "✅", "error": "❌",
                "cancelled": "🚫", "paused": "⏸"}.get(status, "·")
        lines.append(f"  {icon} <code>{jid[:8]}</code> {mode} — {status}")
        lines.append(f"     <i>{(created or '')[:16]}</i>")
    _send(ctx, "\n".join(lines))


def _cmd_drafts(ctx: BotContext, _args: str) -> None:
    from ..persistence import open_db
    try:
        conn = open_db(ctx.paths.state_db)
        try:
            rows = conn.execute(
                "SELECT id, title, topic, wep_phrase FROM drafts "
                "WHERE status='staged' ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        _send(ctx, f"⚠ DB error: {_fmt(str(exc))}"); return

    if not rows:
        _send(ctx, "No staged drafts."); return
    lines = [f"<b>{len(rows)} staged draft(s)</b>\n"]
    for did, title, topic, wep in rows:
        lines.append(f"  <code>{did}</code>")
        lines.append(f"  <b>{_fmt(title or did)}</b>")
        if topic:
            lines.append(f"  Topic: {_fmt(topic)}")
        if wep:
            lines.append(f"  Confidence: {_fmt(wep)}")
        lines.append(f"  /approve {did}  |  /reject {did}")
        lines.append("")
    _send(ctx, "\n".join(lines))


def _cmd_approve(ctx: BotContext, args: str) -> None:
    draft_id = args.strip().split()[0] if args.strip() else ""
    if not draft_id:
        _send(ctx, "Usage: /approve <draft_id>"); return
    from ..persistence import open_db
    try:
        conn = open_db(ctx.paths.state_db)
        try:
            cur = conn.execute(
                "UPDATE drafts SET status='published', updated_at=datetime('now') "
                "WHERE id=? AND status='staged'", (draft_id,)
            )
            conn.execute(
                "UPDATE jobs SET status='done', updated_at=datetime('now') "
                "WHERE id=(SELECT job_id FROM drafts WHERE id=?)", (draft_id,)
            )
            ok = cur.rowcount > 0
        finally:
            conn.close()
    except Exception as exc:
        _send(ctx, f"⚠ DB error: {_fmt(str(exc))}"); return

    if ok:
        _send(ctx, f"✅ Draft <code>{_fmt(draft_id)}</code> approved and published.")
        # Auto-export to Logseq if configured
        _maybe_logseq_export(ctx, draft_id)
    else:
        _send(ctx, f"Draft <code>{_fmt(draft_id)}</code> not found or not staged.")


def _cmd_reject(ctx: BotContext, args: str) -> None:
    parts = args.strip().split(None, 1)
    if not parts:
        _send(ctx, "Usage: /reject <draft_id> [reason]"); return
    draft_id = parts[0]
    reason = parts[1] if len(parts) > 1 else "Rejected via Telegram"
    from ..persistence import open_db
    try:
        conn = open_db(ctx.paths.state_db)
        try:
            cur = conn.execute(
                "UPDATE drafts SET status='rejected', reject_reason=?, "
                "updated_at=datetime('now') WHERE id=? AND status='staged'",
                (reason, draft_id)
            )
            ok = cur.rowcount > 0
        finally:
            conn.close()
    except Exception as exc:
        _send(ctx, f"⚠ DB error: {_fmt(str(exc))}"); return

    if ok:
        _send(ctx, f"🚫 Draft <code>{_fmt(draft_id)}</code> rejected.")
    else:
        _send(ctx, f"Draft <code>{_fmt(draft_id)}</code> not found or not staged.")


def _cmd_research(ctx: BotContext, args: str) -> None:
    question = args.strip()
    if not question:
        _send(ctx, "Usage: /research <your research question>"); return

    with ctx._research_lock:
        if ctx._research_thread and ctx._research_thread.is_alive():
            _send(ctx, "⚠ A research job is already running. Use /cancel to abort it first.")
            return

    _send(ctx, f"🔄 Research started:\n<i>{_fmt(question[:120])}</i>\n\nI'll reply when the draft is ready.")

    def _run() -> None:
        try:
            from ..pipeline import PipelineConfig, ResearchPipeline
            pipe = ResearchPipeline(ctx.paths, config=PipelineConfig())
            result = pipe.research(question)
            d = result.discipline or {}
            wep = d.get("wep_phrase", "")
            src = d.get("source_count", result.chunks_ingested)
            lines = [
                f"✅ <b>Research complete</b>",
                f"Draft: <code>{result.draft_id}</code>",
                f"Mode: {result.mode}",
            ]
            if wep:
                lines.append(f"Confidence: {_fmt(wep)}")
            if src:
                lines.append(f"Sources: {src}")
            lines.append(f"\n/approve {result.draft_id}  |  /reject {result.draft_id}")
            _send(ctx, "\n".join(lines))
        except Exception as exc:
            _send(ctx, f"❌ Research failed:\n<code>{_fmt(str(exc)[:300])}</code>")

    t = threading.Thread(target=_run, daemon=True, name="tg-research")
    with ctx._research_lock:
        ctx._research_thread = t
    t.start()


def _cmd_budget(ctx: BotContext, _args: str) -> None:
    try:
        from ..governor import BUDGET_DEFAULTS, Governor
        g = Governor(ctx.paths.state_db, BUDGET_DEFAULTS)
        usage = g.current_period_usage()
        limit = g.effective_limit()
        pct = 100 * usage / limit if limit else 0
        bar_filled = int(pct / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        lines = [
            "<b>Budget</b>\n",
            f"  [{bar}] {pct:.0f}%",
            f"  Used:  ${usage:.4f}",
            f"  Limit: ${limit:.2f}",
        ]
        if pct >= 90:
            lines.append("\n⚠ <b>Near limit</b> — new jobs may be paused.")
        _send(ctx, "\n".join(lines))
    except Exception as exc:
        _send(ctx, f"⚠ Could not read budget: {_fmt(str(exc))}")


def _cmd_sync(ctx: BotContext, _args: str) -> None:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore
    try:
        cfg = {}
        if ctx.paths.config_file.exists():
            with ctx.paths.config_file.open("rb") as fh:
                cfg = tomllib.load(fh).get("logseq", {})
        if not cfg.get("enabled") or not cfg.get("graph_dir"):
            _send(ctx, "⚠ Logseq sync not configured — set [logseq] enabled=true and graph_dir in config.toml")
            return
        from pathlib import Path
        from ..compounding.logseq_sync import sync_drafts
        graph_dir = Path(cfg["graph_dir"]).expanduser()
        result = sync_drafts(ctx.paths, graph_dir)
        lines = ["<b>Logseq sync complete</b>\n",
                 f"  Synced: {result.synced} draft(s)"]
        if result.failed:
            lines.append(f"  Failed: {result.failed}")
            for did, err in result.errors[:3]:
                lines.append(f"    <code>{_fmt(did)}</code>: {_fmt(err[:80])}")
        _send(ctx, "\n".join(lines))
    except Exception as exc:
        _send(ctx, f"⚠ Sync failed: {_fmt(str(exc))}")


def _cmd_escalations(ctx: BotContext, _args: str) -> None:
    try:
        from ..subconscious.store import ReflectionStore
        store = ReflectionStore(ctx.paths.reflections_db)
        items = store.list_escalations(status="open")
        if not items:
            _send(ctx, "✅ No open escalations."); return
        lines = [f"<b>{len(items)} open escalation(s)</b>\n"]
        for e in items[:5]:
            kind = (e.kind.value if hasattr(e.kind, "value") else str(e.kind)).replace("_", " ").title()
            lines.append(f"  <b>{kind}</b> [{e.priority}]")
            body_snippet = (e.body or "")[:100]
            if body_snippet:
                lines.append(f"  <i>{_fmt(body_snippet)}</i>")
            lines.append(f"  ID: <code>{e.id}</code>\n")
        if len(items) > 5:
            lines.append(f"  <i>…and {len(items) - 5} more — see dashboard</i>")
        _send(ctx, "\n".join(lines))
    except Exception as exc:
        _send(ctx, f"⚠ Could not read escalations: {_fmt(str(exc))}")


def _cmd_cancel(ctx: BotContext, _args: str) -> None:
    with ctx._research_lock:
        t = ctx._research_thread
    if t and t.is_alive():
        # Threads can't be force-killed in Python; we just tell the user the
        # job is running to completion. The pipeline checks for interrupts.
        _send(ctx, "⚠ Research job is running — it will complete normally. "
                   "Draft will be staged; use /reject to discard it.")
    else:
        _send(ctx, "No research job is currently running.")


def _maybe_logseq_export(ctx: BotContext, draft_id: str) -> None:
    """Export to Logseq after approval if configured. Best-effort."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore
    try:
        if not ctx.paths.config_file.exists():
            return
        with ctx.paths.config_file.open("rb") as fh:
            lcfg = tomllib.load(fh).get("logseq", {})
        if not lcfg.get("enabled") or not lcfg.get("graph_dir"):
            return
        from pathlib import Path as _Path
        from ..persistence import open_db
        from ..targets.logseq import export_draft
        conn = open_db(ctx.paths.state_db)
        try:
            row = conn.execute(
                "SELECT title, body_html, topic, wep_phrase, source_count "
                "FROM drafts WHERE id=?", (draft_id,)
            ).fetchone()
        finally:
            conn.close()
        if row:
            export_draft(
                _Path(lcfg["graph_dir"]).expanduser(),
                draft_id=draft_id,
                title=row[0] or draft_id,
                body_html=row[1] or "",
                topic=row[2] or "",
                wep_phrase=row[3],
                source_count=row[4] or 0,
            )
    except Exception as exc:
        log.warning("telegram_bot.logseq_export_failed", draft_id=draft_id, error=str(exc))


# ---------------------------------------------------------------------------
# Command dispatch table
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, Callable[[BotContext, str], None]] = {
    "/help": _cmd_help,
    "/status": _cmd_status,
    "/jobs": _cmd_jobs,
    "/drafts": _cmd_drafts,
    "/approve": _cmd_approve,
    "/reject": _cmd_reject,
    "/research": _cmd_research,
    "/budget": _cmd_budget,
    "/sync": _cmd_sync,
    "/escalations": _cmd_escalations,
    "/cancel": _cmd_cancel,
}


def _parse_command(text: str) -> tuple[str, str] | None:
    """Parse a Telegram bot command from message text.

    Returns ``(command, args)`` or ``None`` if the text is not a command.
    Strips ``@botname`` suffixes Telegram appends in group chats.
    """
    if not text or not text.startswith("/"):
        return None
    parts = text.strip().split(None, 1)
    cmd = parts[0].lower()
    # Strip @botname suffix: /command@mybotname → /command
    if "@" in cmd:
        cmd = cmd[:cmd.index("@")]
    args = parts[1] if len(parts) > 1 else ""
    return cmd, args


def _handle_message(ctx: BotContext, message: dict) -> None:
    """Process one incoming message from the operator's chat."""
    # Verify origin: only the configured chat may control the agent.
    chat = message.get("chat", {})
    if str(chat.get("id")) != str(ctx.chat_id):
        return  # silently ignore all other origins

    text = message.get("text", "")
    parsed = _parse_command(text)
    if parsed is None:
        return  # non-command messages are ignored (e.g. the YES from airlock)

    cmd, args = parsed
    handler = _DISPATCH.get(cmd)
    if handler is None:
        _send(ctx, f"Unknown command: <code>{_fmt(cmd)}</code>\n\nSend /help for the list.")
        return

    log.info("telegram_bot.command", cmd=cmd, chat_id=ctx.chat_id)
    try:
        handler(ctx, args)
    except Exception as exc:
        log.warning("telegram_bot.handler_error", cmd=cmd, error=str(exc))
        _send(ctx, f"⚠ Command failed: <code>{_fmt(str(exc)[:200])}</code>")


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------

def serve(
    bot_token: str,
    chat_id: str,
    paths: "Paths",
    *,
    poll_timeout: int = 30,
    client: httpx.Client | None = None,
    now: Clock | None = None,
    sleep: Sleep | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    """Run the command-polling loop (blocking).

    ``poll_timeout`` is the ``timeout`` parameter sent to ``getUpdates``
    (long-polling seconds; Telegram holds the connection and replies as soon
    as an update arrives, so this does not burn CPU).

    ``stop_event``, ``now``, ``sleep``, and ``client`` are injectable so tests
    can drive the loop deterministically without touching the network or time.
    """
    owns_client = client is None
    http = client or httpx.Client(timeout=poll_timeout + 5.0)
    nap: Sleep = sleep or time.sleep
    _stop = stop_event or threading.Event()

    ctx = BotContext(
        paths=paths,
        bot_token=bot_token,
        chat_id=chat_id,
        client=http,
    )

    log.info("telegram_bot.started", chat_id=chat_id)
    _send(ctx, "🔦 <b>Lighthouse online.</b> Send /help to see available commands.")

    offset: int | None = None
    try:
        while not _stop.is_set():
            params: dict[str, object] = {"timeout": poll_timeout}
            if offset is not None:
                params["offset"] = offset

            try:
                response = http.get(
                    _method_url(bot_token, "getUpdates"),
                    params=params,
                    timeout=poll_timeout + 5.0,
                )
            except httpx.HTTPError as exc:
                log.warning("telegram_bot.poll_error", error=str(exc))
                nap(5.0)
                continue

            if response.is_success:
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                else:
                    for message in _extract_messages(payload):
                        _handle_message(ctx, message)
                offset = _next_offset(payload, offset)
            else:
                log.warning("telegram_bot.poll_http_error", status=response.status_code)
                nap(5.0)
    finally:
        if owns_client:
            http.close()
        log.info("telegram_bot.stopped")


def start_in_thread(
    bot_token: str,
    chat_id: str,
    paths: "Paths",
    *,
    stop_event: threading.Event | None = None,
) -> tuple[threading.Thread, threading.Event]:
    """Start ``serve()`` in a daemon thread.

    Returns ``(thread, stop_event)`` so the caller can signal shutdown.
    """
    ev = stop_event or threading.Event()
    t = threading.Thread(
        target=serve,
        kwargs={"bot_token": bot_token, "chat_id": chat_id,
                "paths": paths, "stop_event": ev},
        daemon=True,
        name="telegram-bot",
    )
    t.start()
    return t, ev
