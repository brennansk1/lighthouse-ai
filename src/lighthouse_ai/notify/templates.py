"""Per-artifact-type Telegram message templates + the staged-review alert path.

Telegram is the primary *mobile* surface (design §21.3): glanceable, read-mostly.
When a research job finishes and its artifact is staged for review, the operator
should get a one-screen summary on their phone — winner+crux for a Decide, the
PRISMA counts for a Survey, the event span for a Reconstruct — not a wall of
HTML. This module owns that rendering.

Two layers, kept deliberately separate so the hard part stays trivially testable:

* :func:`render_artifact` — a **pure** function (``(artifact_type, title,
  body_json) -> str``). No I/O, no network, no clock. It covers all seven
  artifact types and degrades to a generic summary for anything it does not
  recognise or when ``body_json`` is missing/malformed. Every line is escaped for
  Telegram MarkdownV2 (see :func:`escape_md`) so a title containing ``*`` or
  ``[`` cannot break the message or smuggle markup.

* :func:`notify_artifact_staged` — the thin effectful wrapper. It honours a
  ``notify_enabled`` flag (default **off**), no-ops when the channel is not
  configured (no token / chat id), renders via :func:`render_artifact`, and sends
  through the injected :class:`~lighthouse_ai.notify.telegram.TelegramChannel`.
  It returns a bool and never raises, so a best-effort caller (the job
  dispatcher) can fire it without a guard of its own — though the dispatcher
  wraps it anyway, belt-and-suspenders, so notification can never break a job.

The Telegram client is injectable end-to-end (it lives on the channel), so the
test-suite drives this with a fake/respx client and never touches the network.
"""

from __future__ import annotations

from typing import Any

from .telegram import TelegramChannel

# Telegram MarkdownV2 reserves these characters; any literal occurrence in user
# text must be backslash-escaped or the Bot API rejects the message (HTTP 400).
# https://core.telegram.org/bots/api#markdownv2-style
_MD2_SPECIALS = r"_*[]()~`>#+-=|{}.!"


def escape_md(text: object) -> str:
    """Escape ``text`` for Telegram MarkdownV2.

    Coerces to ``str`` first so callers can pass numbers/None straight from a
    decoded ``body_json`` without pre-stringifying. Every reserved character is
    backslash-escaped; this is intentionally aggressive (escaping inside what
    would be markup too) because these templates never embed *user* text inside
    markup — our own ``*bold*`` wrappers are added around already-escaped spans.
    """
    s = "" if text is None else str(text)
    out = []
    for ch in s:
        if ch in _MD2_SPECIALS:
            out.append("\\")
        out.append(ch)
    return "".join(out)


def _truncate(text: str, limit: int = 160) -> str:
    """Clip a one-line snippet for mobile, before escaping.

    Operates on the *raw* string so the ellipsis math counts visible characters,
    not escape backslashes. A blank/whitespace-only string collapses to "".
    """
    s = " ".join(str(text).split())
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"  # … single-char ellipsis


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _first_nonempty(*candidates: object) -> str:
    for c in candidates:
        s = "" if c is None else str(c).strip()
        if s:
            return s
    return ""


# ── per-type renderers ───────────────────────────────────────────────────────
#
# Each takes the (already-escaped) title plus the raw ``body_json`` dict and
# returns the full MarkdownV2 message. They are forgiving: a missing key yields a
# sensible blank rather than a KeyError, because ``body_json`` shapes evolve and
# a notification must never be the thing that crashes.


def _render_matrix(title_md: str, body: dict) -> str:
    winner = body.get("winner") or "(no winner)"
    margin = body.get("margin")
    crux = _truncate(_first_nonempty(body.get("crux")), 200)
    margin_md = ""
    if isinstance(margin, (int, float)):
        margin_md = f" \\(margin {escape_md(f'{margin:.2f}')}\\)"
    lines = [
        f"*Decision:* {title_md}",
        f"*Winner:* {escape_md(winner)}{margin_md}",
    ]
    if crux:
        lines.append(f"*Crux:* {escape_md(crux)}")
    return "\n".join(lines)


def _render_verdict(title_md: str, body: dict) -> str:
    # DebateResult has judge_summary + responses + disputes (and may carry an
    # explicit crux). Prefer an explicit crux, else the first named dispute.
    verdict = _truncate(_first_nonempty(body.get("judge_summary")), 220)
    disputes = _as_list(body.get("disputes"))
    crux = _truncate(
        _first_nonempty(body.get("crux"), disputes[0] if disputes else ""), 200
    )
    n = len(_as_list(body.get("responses")))
    lines = [f"*Verdict:* {title_md}"]
    if verdict:
        lines.append(escape_md(verdict))
    if crux:
        lines.append(f"*Crux:* {escape_md(crux)}")
    if n:
        lines.append(f"_{escape_md(str(n))} perspectives weighed_")
    return "\n".join(lines)


def _citation_coverage(body: dict, sections: list) -> float | None:
    """Coverage as a 0..1 fraction.

    Prefer an explicit ``citation_coverage`` field; otherwise derive it as the
    share of sections carrying at least one citation. Returns ``None`` when there
    is nothing to measure (no field, no sections)."""
    explicit = body.get("citation_coverage")
    if isinstance(explicit, (int, float)):
        return float(explicit)
    if not sections:
        return None
    cited = sum(1 for s in sections if isinstance(s, dict) and s.get("citations"))
    return cited / len(sections)


def _render_report(title_md: str, body: dict) -> str:
    sections = _as_list(body.get("sections"))
    coverage = _citation_coverage(body, sections)
    # Top finding: first section with a body, preferring load-bearing ones.
    ordered = sorted(
        (s for s in sections if isinstance(s, dict)),
        key=lambda s: 0 if s.get("is_load_bearing") else 1,
    )
    top = ""
    for s in ordered:
        top = _truncate(_first_nonempty(s.get("body"), s.get("title")), 200)
        if top:
            break
    lines = [
        f"*Report:* {title_md}",
        f"*Sections:* {escape_md(str(len(sections)))}",
    ]
    if coverage is not None:
        pct = f"{round(coverage * 100)}%"
        lines.append(f"*Citation coverage:* {escape_md(pct)}")
    if top:
        lines.append(f"*Top finding:* {escape_md(top)}")
    return "\n".join(lines)


def _render_table(title_md: str, body: dict) -> str:
    _prisma_raw = body.get("prisma")
    prisma: dict = _prisma_raw if isinstance(_prisma_raw, dict) else {}
    included = prisma.get("included", 0)
    identified = prisma.get("identified", 0)
    return "\n".join(
        [
            f"*Survey:* {title_md}",
            f"*PRISMA:* included {escape_md(str(included))} of "
            f"{escape_md(str(identified))} identified",
        ]
    )


def _render_timeline(title_md: str, body: dict) -> str:
    events = _as_list(body.get("events"))
    dates: list[str] = sorted(
        str(e.get("date")) for e in events
        if isinstance(e, dict) and e.get("date") is not None and e.get("date") != ""
    )
    lines = [
        f"*Timeline:* {title_md}",
        f"*Events:* {escape_md(str(len(events)))}",
    ]
    if dates:
        span = dates[0] if dates[0] == dates[-1] else f"{dates[0]} → {dates[-1]}"
        lines.append(f"*Span:* {escape_md(span)}")
    return "\n".join(lines)


def _render_transcript(title_md: str, body: dict) -> str:
    turns = _as_list(body.get("turns"))
    question = _truncate(
        _first_nonempty(
            body.get("topic"),
            next(
                (t.get("text") for t in turns
                 if isinstance(t, dict) and t.get("role") == "user"),
                "",
            ),
        ),
        160,
    )
    answer = _truncate(
        _first_nonempty(
            *[
                t.get("text") for t in reversed(turns)
                if isinstance(t, dict) and t.get("role") in ("assistant", "agent")
            ]
        ),
        220,
    )
    lines = [f"*Ask:* {title_md}"]
    if question:
        lines.append(f"*Q:* {escape_md(question)}")
    if answer:
        lines.append(f"*A:* {escape_md(answer)}")
    return "\n".join(lines)


def _render_digest(title_md: str, body: dict) -> str:
    alerts = _as_list(body.get("alerts"))
    digest = _as_list(body.get("digest"))
    items = alerts + digest
    top = ""
    for c in items:
        if isinstance(c, dict):
            _item_raw = c.get("item")
            item: dict = _item_raw if isinstance(_item_raw, dict) else {}
            top = _truncate(_first_nonempty(item.get("title"), item.get("url")), 160)
            if top:
                break
    lines = [
        f"*Watch:* {title_md}",
        f"*Items:* {escape_md(str(len(items)))} "
        f"\\({escape_md(str(len(alerts)))} alert"
        f"{'' if len(alerts) == 1 else 's'}\\)",
    ]
    if top:
        lines.append(f"*Top:* {escape_md(top)}")
    return "\n".join(lines)


_RENDERERS = {
    "matrix": _render_matrix,
    "verdict": _render_verdict,
    "report": _render_report,
    "table": _render_table,
    "timeline": _render_timeline,
    "transcript": _render_transcript,
    "digest": _render_digest,
}


def render_artifact(artifact_type: str, title: str, body_json: Any) -> str:
    """Render a concise, MarkdownV2-escaped Telegram message for a staged artifact.

    Pure: same inputs → same string, no side effects. ``body_json`` may be any
    decoded JSON value; non-dict bodies (or an unrecognised ``artifact_type``)
    fall back to a generic title-only summary so the function is total — it always
    returns a deliverable string and never raises on shape surprises.
    """
    title_md = escape_md(_truncate(title or "(untitled)", 120))
    body = body_json if isinstance(body_json, dict) else {}
    renderer = _RENDERERS.get(str(artifact_type))
    if renderer is None:
        kind = escape_md(str(artifact_type) or "artifact")
        return f"*Staged for review:* {title_md}\n_{kind}_"
    return renderer(title_md, body)


def notify_artifact_staged(
    artifact_type: str,
    title: str,
    body_json: Any,
    *,
    bot_token: str,
    chat_id: str,
    enabled: bool = False,
    client: Any | None = None,
) -> bool:
    """Best-effort: alert the operator that an artifact is staged for review.

    No-ops (returns ``False``) when ``enabled`` is false — the default — or when
    the channel is not addressable (missing ``bot_token`` / ``chat_id``). When
    enabled and configured it renders via :func:`render_artifact` and sends
    through a :class:`TelegramChannel`, returning the channel's delivery bool.

    The message is sent with ``parse_mode=MarkdownV2`` because the templates emit
    MarkdownV2 markup. ``client`` is injected straight onto the channel so tests
    use a fake/respx client and the real network is never touched.
    """
    if not enabled or not bot_token or not chat_id:
        return False
    text = render_artifact(artifact_type, title, body_json)
    channel = TelegramChannel(bot_token=bot_token, chat_id=chat_id, client=client)
    return channel.send_text(text, parse_mode="MarkdownV2")


def notify_monitor_alert(
    title: str,
    body: str,
    *,
    bot_token: str,
    chat_id: str,
    enabled: bool = False,
    client: Any | None = None,
) -> bool:
    """Best-effort: alert the user that a watched website/monitor changed.

    Mirrors :func:`notify_artifact_staged` but for a Watch event — a plain-text
    line so the user is told "your monitor fired" without opening the dashboard.
    No-ops (returns ``False``) when disabled or unaddressable. Plain text (no
    MarkdownV2) so arbitrary page titles/URLs need no escaping.
    """
    if not enabled or not bot_token or not chat_id:
        return False
    text = f"🔔 {title}\n{body}".strip()
    channel = TelegramChannel(bot_token=bot_token, chat_id=chat_id, client=client)
    return channel.send_text(text)
