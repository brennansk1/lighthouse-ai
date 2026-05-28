"""Professional Telegram notification templates for Lighthouse events.

Each template produces a (title, body) pair formatted as Telegram HTML.
Telegram HTML supports: <b>, <i>, <code>, <pre>, <a href="...">, <s>, <u>.

Templates use structured data kwargs so callers pass named fields rather than
pre-formatted strings — this keeps the formatting centralised and testable.
"""
from __future__ import annotations

from typing import Any


def _fmt(s: str) -> str:
    """HTML-escape a string for safe inclusion in a Telegram message."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _line(*parts: str) -> str:
    return "  ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Per-event templates
# ---------------------------------------------------------------------------

def draft_ready(
    *,
    question: str = "",
    draft_id: str = "",
    mode: str = "",
    wep_phrase: str = "",
    source_count: int = 0,
    sections: int = 0,
    **_: Any,
) -> tuple[str, str]:
    title = "Research complete"
    lines = []
    if question:
        lines.append(f"<b>Question:</b> {_fmt(question[:120])}")
    if draft_id:
        lines.append(f"<b>Draft ID:</b> <code>{_fmt(draft_id)}</code>")
    if mode:
        lines.append(f"<b>Mode:</b> {_fmt(mode.title())}")
    if wep_phrase:
        lines.append(f"<b>Confidence:</b> {_fmt(wep_phrase)}")
    if source_count:
        lines.append(f"<b>Sources:</b> {source_count}")
    if sections:
        lines.append(f"<b>Sections:</b> {sections}")
    lines.append("")
    lines.append("<i>Review: Lighthouse dashboard → Drafts</i>")
    return title, "\n".join(lines)


def draft_approved(
    *,
    draft_id: str = "",
    title: str = "",
    topic: str = "",
    **_: Any,
) -> tuple[str, str]:
    tpl_title = "Draft approved"
    lines = []
    if title:
        lines.append(f"<b>{_fmt(title)}</b>")
    if topic:
        lines.append(f"<b>Topic:</b> {_fmt(topic)}")
    if draft_id:
        lines.append(f"<b>Draft ID:</b> <code>{_fmt(draft_id)}</code>")
    lines.append("")
    lines.append("<i>Published to your knowledge base.</i>")
    return tpl_title, "\n".join(lines)


def job_started(
    *,
    question: str = "",
    mode: str = "",
    job_id: str = "",
    **_: Any,
) -> tuple[str, str]:
    title = "Research started"
    lines = []
    if question:
        lines.append(f"<b>Question:</b> {_fmt(question[:120])}")
    if mode:
        lines.append(f"<b>Mode:</b> {_fmt(mode.title())}")
    if job_id:
        lines.append(f"<b>Job:</b> <code>{_fmt(job_id)}</code>")
    return title, "\n".join(lines)


def job_completed(
    *,
    question: str = "",
    draft_id: str = "",
    mode: str = "",
    wep_phrase: str = "",
    source_count: int = 0,
    **_: Any,
) -> tuple[str, str]:
    return draft_ready(
        question=question,
        draft_id=draft_id,
        mode=mode,
        wep_phrase=wep_phrase,
        source_count=source_count,
    )


def job_failed(
    *,
    question: str = "",
    error: str = "",
    mode: str = "",
    **_: Any,
) -> tuple[str, str]:
    title = "Research failed"
    lines = []
    if question:
        lines.append(f"<b>Question:</b> {_fmt(question[:120])}")
    if mode:
        lines.append(f"<b>Mode:</b> {_fmt(mode.title())}")
    if error:
        lines.append(f"<b>Error:</b> <code>{_fmt(error[:200])}</code>")
    lines.append("")
    lines.append("<i>Check logs: lighthouse doctor</i>")
    return title, "\n".join(lines)


def monitor_alert_high(
    *,
    topic: str = "",
    summary: str = "",
    source: str = "",
    **_: Any,
) -> tuple[str, str]:
    title = "High-priority alert"
    lines = []
    if topic:
        lines.append(f"<b>Topic:</b> {_fmt(topic)}")
    if summary:
        lines.append(f"\n{_fmt(summary[:300])}")
    if source:
        lines.append(f"\n<b>Source:</b> {_fmt(source[:100])}")
    lines.append("")
    lines.append("<i>Review: Lighthouse dashboard → Monitor</i>")
    return title, "\n".join(lines)


def monitor_alert_medium(
    *,
    topic: str = "",
    summary: str = "",
    **_: Any,
) -> tuple[str, str]:
    title = "Monitor alert"
    lines = []
    if topic:
        lines.append(f"<b>Topic:</b> {_fmt(topic)}")
    if summary:
        lines.append(f"\n{_fmt(summary[:300])}")
    return title, "\n".join(lines)


def budget_warn(
    *,
    used_pct: float = 0.0,
    budget_usd: float = 0.0,
    period: str = "",
    **_: Any,
) -> tuple[str, str]:
    title = "Budget warning"
    lines = []
    if used_pct:
        lines.append(f"<b>Used:</b> {used_pct:.0f}% of budget")
    if budget_usd:
        lines.append(f"<b>Limit:</b> ${budget_usd:.2f}{' / ' + period if period else ''}")
    lines.append("")
    lines.append("<i>Adjust limit: lighthouse budget set</i>")
    return title, "\n".join(lines)


def budget_trip(
    *,
    used_pct: float = 0.0,
    budget_usd: float = 0.0,
    period: str = "",
    **_: Any,
) -> tuple[str, str]:
    title = "Budget limit reached"
    lines = []
    lines.append("<b>New LLM requests are paused.</b>")
    if used_pct:
        lines.append(f"<b>Used:</b> {used_pct:.0f}%")
    if budget_usd:
        lines.append(f"<b>Limit:</b> ${budget_usd:.2f}{' / ' + period if period else ''}")
    lines.append("")
    lines.append("<i>Reset: lighthouse budget reset</i>")
    return title, "\n".join(lines)


def logseq_synced(
    *,
    synced: int = 0,
    failed: int = 0,
    graph_dir: str = "",
    **_: Any,
) -> tuple[str, str]:
    title = "Logseq sync complete"
    lines = []
    lines.append(f"<b>Synced:</b> {synced} draft(s)")
    if failed:
        lines.append(f"<b>Failed:</b> {failed} draft(s)")
    if graph_dir:
        lines.append(f"<b>Graph:</b> <code>{_fmt(graph_dir[:80])}</code>")
    return title, "\n".join(lines)


def escalation_raised(
    *,
    escalation_id: str = "",
    kind: str = "",
    body: str = "",
    priority: str = "",
    **_: Any,
) -> tuple[str, str]:
    title = "Escalation raised"
    lines = []
    if kind:
        lines.append(f"<b>Type:</b> {_fmt(kind.replace('_', ' ').title())}")
    if priority:
        lines.append(f"<b>Priority:</b> {_fmt(priority)}")
    if body:
        lines.append(f"\n{_fmt(body[:300])}")
    if escalation_id:
        lines.append(f"\n<b>ID:</b> <code>{_fmt(escalation_id)}</code>")
    lines.append("")
    lines.append("<i>Act: Lighthouse dashboard → Intelligence</i>")
    return title, "\n".join(lines)


def position_resolved(
    *,
    statement: str = "",
    outcome: str = "",
    topic: str = "",
    **_: Any,
) -> tuple[str, str]:
    title = "Position resolved"
    lines = []
    if statement:
        lines.append(f"<b>Claim:</b> {_fmt(statement[:200])}")
    if outcome:
        lines.append(f"<b>Outcome:</b> {_fmt(outcome.title())}")
    if topic:
        lines.append(f"<b>Topic:</b> {_fmt(topic)}")
    return title, "\n".join(lines)


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, Any] = {
    "draft_ready": draft_ready,
    "draft_approved": draft_approved,
    "job_started": job_started,
    "job_completed": job_completed,
    "job_failed": job_failed,
    "monitor_alert_high": monitor_alert_high,
    "monitor_alert_medium": monitor_alert_medium,
    "budget_warn": budget_warn,
    "budget_trip": budget_trip,
    "logseq_synced": logseq_synced,
    "escalation_raised": escalation_raised,
    "position_resolved": position_resolved,
}


def render(event: str, fallback_title: str, fallback_body: str, **data: Any) -> tuple[str, str]:
    """Render a Telegram notification template for ``event``.

    Falls back to the plain (title, body) pair when no template is registered
    for the event — so plain callers that don't pass structured data still work.
    """
    fn = _TEMPLATES.get(event)
    if fn is None or not data:
        return fallback_title, fallback_body
    return fn(**data)
