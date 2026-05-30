"""Web Monitor entrypoints — one-shot pre-flight (``run``) + watch (``run_watchable``).

Both entrypoints take URLs from the question/query string (the Watch engine
stores registered monitor URLs and passes them in ``query``). All outbound I/O
goes through ``ctx`` primitives; the two new platform modules
(:mod:`lighthouse_ai.sources.scrapability`, :mod:`lighthouse_ai.modes.web_triggers`)
supply the verdict + snapshot/trigger logic — no ``httpx`` here.

State handoff: the skill is stateless. ``run_watchable`` returns the current
:class:`Snapshot` (serialised) in each change Document's metadata under
``snapshot``; the caller persists it in ``state.db`` and, on the next tick,
passes the prior snapshot back via ``query`` context (a JSON map of
``url -> snapshot dict``) so the diff has a baseline. When no prior snapshot is
available the first tick establishes the baseline and emits nothing.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from lighthouse_ai.modes.web_triggers import Snapshot, content_diff, evaluate_trigger
from lighthouse_ai.sources.scrapability import (
    FetchResult,
    ScrapeVerdict,
    verify_scrapable,
)

if TYPE_CHECKING:
    from datetime import datetime

    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _extract_urls(text: str) -> list[str]:
    """Return all http(s) URLs in *text*, stripped of trailing punctuation."""
    out: list[str] = []
    for m in _URL_RE.findall(text):
        cleaned = m.rstrip(".,;:!?\"')")
        if cleaned:
            out.append(cleaned)
    return out


def _ctx_fetch_adapter(ctx: SkillContext) -> Any:
    """Adapt ``ctx.fetch`` into the ``(url) -> FetchResult`` shape verify wants.

    The scrapability pre-flight needs status + headers + body; ``ctx.fetch``
    returns an httpx-like response. We wrap it so verify_scrapable stays
    transport-agnostic and the skill never touches httpx.
    """

    def fetch(url: str) -> FetchResult:
        resp = ctx.fetch(url)
        return FetchResult(
            status=getattr(resp, "status_code", 200),
            headers=dict(getattr(resp, "headers", {}) or {}),
            body=getattr(resp, "content", b"") or b"",
            content_type=(getattr(resp, "headers", {}) or {}).get("content-type"),
        )

    return fetch


def _parse_prior_snapshots(query: str) -> dict[str, dict[str, Any]]:
    """Pull a ``{url: snapshot_dict}`` map out of the query if present.

    The Watch session encodes prior snapshots as a JSON object embedded in the
    query (e.g. ``"<urls> ||SNAPSHOTS|| {...}"``). Absent or malformed → empty
    map (first tick / baseline). This keeps the skill stateless while letting
    the caller round-trip persisted state.
    """
    marker = "||SNAPSHOTS||"
    if marker not in query:
        return {}
    _, _, raw = query.partition(marker)
    raw = raw.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


# ---------------------------------------------------------------------------
# run — one-shot scrapability pre-flight
# ---------------------------------------------------------------------------


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """One-shot: verify scrapability for each URL in *question*.

    Returns one Document per URL whose text is the human-readable verdict and
    whose metadata carries the full :class:`ScrapeVerdict` fields, so the Watch
    "Add source" screen can render ✓ / ◐ / ✗ with the reason.
    """
    urls = _extract_urls(question)[:max_results]
    if not urls:
        return []

    fetch = _ctx_fetch_adapter(ctx)
    allowlist = ctx.effective_domains or None
    docs: list[Document] = []
    for url in urls:
        try:
            verdict = verify_scrapable(url, fetch=fetch, allowlist=allowlist)
        except Exception:
            continue
        docs.append(_verdict_document(ctx, url, verdict))
    return docs


def _verdict_document(
    ctx: SkillContext, url: str, verdict: ScrapeVerdict
) -> Document:
    symbol = {"good": "✓", "limited": "◐", "blocked": "✗"}.get(
        verdict.verdict, "?"
    )
    text = f"{symbol} {verdict.verdict}: {verdict.reason} ({url})"
    meta: dict[str, Any] = {
        "url": url,
        "type": "scrapability_verdict",
        **verdict.as_dict(),
    }
    return ctx.make_document(
        doc_id=f"web_monitor:verdict:{abs(hash(url)) & 0xFFFFFFFF:08x}",
        text=text,
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# run_watchable — fetch, snapshot, diff against prior
# ---------------------------------------------------------------------------


def run_watchable(
    ctx: SkillContext,
    query: str,
    *,
    since: datetime | None = None,
    max_results: int = 5,
) -> list[Document]:
    """Watch each URL in *query* for change since its prior snapshot.

    For each monitored URL:
      1. fetch + broker + extract via ``ctx.fetch_and_document`` → page text;
      2. build a current :class:`Snapshot` (``fetched_at`` from ``since`` or
         the snapshot's own metadata — the module never calls a clock);
      3. evaluate the configured trigger (default ``any_change``) against the
         prior snapshot parsed from the query;
      4. on a match (or first-tick baseline), emit a Document carrying the
         current snapshot in metadata so the caller can persist it.

    On the first tick (no prior snapshot) a baseline Document is emitted with
    ``change=False`` so the session records the snapshot but does not alert.
    """
    prior = _parse_prior_snapshots(query)
    # Strip the snapshot payload before scanning for URLs.
    url_part = query.split("||SNAPSHOTS||", 1)[0]
    urls = _extract_urls(url_part)[:max_results]
    if not urls:
        return []

    criteria = _criteria_from_query(query)
    fetched_at = since.isoformat() if since is not None else ""

    docs: list[Document] = []
    for url in urls:
        doc = ctx.fetch_and_document(
            url, extra_meta={"type": "web_monitor_fetch", "url": url}
        )
        if doc is None:
            continue
        new_snap = Snapshot(text=doc.text, fetched_at=fetched_at, url=url)
        old_snap = _snapshot_for(prior, url)

        result = evaluate_trigger(old_snap, new_snap, criteria)
        if old_snap is None:
            # Baseline tick: record the snapshot, do not alert.
            docs.append(
                _change_document(
                    ctx, url, new_snap, changed=False,
                    reason="baseline snapshot captured", diff={},
                )
            )
            continue
        if result.matched:
            diff = content_diff(old_snap.text, new_snap.text)
            docs.append(
                _change_document(
                    ctx, url, new_snap, changed=True,
                    reason=result.reason, diff=diff,
                    trigger=result.as_dict(),
                )
            )
    return docs


def _snapshot_for(
    prior: dict[str, dict[str, Any]], url: str
) -> Snapshot | None:
    data = prior.get(url)
    if not data:
        return None
    try:
        return Snapshot.from_dict(data)
    except Exception:
        return None


def _criteria_from_query(query: str) -> dict[str, Any]:
    """Pull a trigger-criteria JSON out of the query, defaulting to any_change."""
    marker = "||CRITERIA||"
    if marker not in query:
        return {"kind": "any_change"}
    _, _, raw = query.partition(marker)
    raw = raw.split("||SNAPSHOTS||", 1)[0].strip()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {"kind": "any_change"}
    if isinstance(data, dict) and data.get("kind"):
        return data
    return {"kind": "any_change"}


def _change_document(
    ctx: SkillContext,
    url: str,
    snapshot: Snapshot,
    *,
    changed: bool,
    reason: str,
    diff: dict[str, Any],
    trigger: dict[str, Any] | None = None,
) -> Document:
    if changed:
        added = diff.get("added", [])
        body = "\n".join(str(x) for x in added[:20]) if added else reason
        text = f"Change detected at {url}: {reason}\n\n{body}"
    else:
        text = f"Baseline snapshot for {url} ({reason})"
    meta: dict[str, Any] = {
        "url": url,
        "type": "web_monitor_change" if changed else "web_monitor_baseline",
        "change": changed,
        "reason": reason,
        "snapshot": snapshot.as_dict(),
        "diff": diff,
    }
    if trigger is not None:
        meta["trigger"] = trigger
    return ctx.make_document(
        doc_id=f"web_monitor:{snapshot.content_hash[:16]}",
        text=text,
        metadata=meta,
    )
