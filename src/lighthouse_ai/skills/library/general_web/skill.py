"""General Web skill — entrypoint for open-web retrieval via SearXNG.

This is the universal fallback skill.  It is always available and searches
the open web through a self-hosted SearXNG meta-search instance.

Entrypoint contract (SKILL_FRAMEWORK.md §2):
  run(ctx, question, *, max_results=5) -> list[Document]
  run_watchable(ctx, query, *, since=None, max_results=5) -> list[Document]

Security invariants:
  - No httpx / requests / urllib / socket / subprocess imports anywhere in
    this package.  All outbound I/O goes through ctx primitives or the vetted
    lighthouse_ai.sources.searxng module.
  - fetch_and_document calls are the preferred path; snippet fallback via
    ctx.make_document is used when the host is egress-blocked or fetch fails.
  - SearXNGUnavailable is caught and returns [] gracefully.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import lighthouse_ai.sources.searxng as _searxng
from lighthouse_ai.sources.searxng import SearXNGUnavailable

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Search the open web for evidence bearing on ``question``.

    Queries SearXNG with the question text, then for each result URL attempts
    a full-page fetch through the broker (``ctx.fetch_and_document``).  If the
    host is egress-blocked or the fetch fails, falls back to ``ctx.make_document``
    using the SearXNG snippet + title as the document text.

    If SearXNG is unreachable returns an empty list — the dispatcher treats
    this as a thin result (``run.thin = True``) and may try another source.

    Args:
        ctx: Capability-restricted context; only ctx primitives may be called.
        question: The research question or query string.
        max_results: Maximum number of Documents to return.

    Returns:
        List of broker-admitted Documents tagged with skill_id="general_web".
        May be empty if SearXNG is unavailable or all fetches fail.
    """
    try:
        results = _searxng.search(
            question, max_results=max_results * 2, categories="general"
        )
    except SearXNGUnavailable:
        return []

    docs: list[Document] = []
    for result in results:
        if not result.url:
            continue

        doc = None
        try:
            doc = ctx.fetch_and_document(
                result.url,
                extra_meta={
                    "title": result.title,
                    "snippet": result.content,
                    "engine": result.engine,
                },
            )
        except Exception:
            # EgressBlocked, network error, or broker rejection — fall through.
            pass

        if doc is None:
            # Snippet fallback: useful even when full fetch is blocked.
            doc_id = f"searxng:{hash(result.url) & 0xFFFFFFFF:08x}"
            text = f"{result.title}\n\n{result.content}" if result.content else result.title
            doc = ctx.make_document(
                doc_id=doc_id,
                text=text,
                metadata={
                    "source": result.url,
                    "url": result.url,
                    "title": result.title,
                    "snippet": result.content,
                    "engine": result.engine,
                    "fallback": "snippet",
                },
            )

        docs.append(doc)
        if len(docs) >= max_results:
            break

    return docs


def run_watchable(
    ctx: SkillContext,
    query: str,
    *,
    since: datetime | None = None,
    max_results: int = 5,
) -> list[Document]:
    """Watch-mode entrypoint — search news for recent articles about ``query``.

    Called on each Watch tick with ``since=last_tick_at``.  Uses the SearXNG
    news category so engines are primed for recency.  Returns Documents in the
    order SearXNG delivers them (typically time-ordered by the news engines).

    Documents are tagged with ``role="recency"`` — per the downgrade rules in
    MODE_SKILL_INTEGRATION.md §5.4 they must not be the sole citation for a
    load-bearing claim.

    Args:
        ctx: Capability-restricted context.
        query: Watch topic query string.
        since: Lower-bound datetime for recency filtering.  A date hint is
            appended to the query string; SearXNG does not natively support
            ISO date filters but recency-biased news engines rank newer results
            first when the query contains a date fragment.
        max_results: Maximum Documents to return per tick.

    Returns:
        Time-ordered list of Documents; empty if SearXNG is unavailable.
    """
    effective_query = query
    if since is not None:
        date_hint = since.strftime("%Y-%m-%d")
        effective_query = f"{query} after:{date_hint}"

    try:
        results = _searxng.search(
            effective_query, max_results=max_results * 2, categories="news"
        )
    except SearXNGUnavailable:
        return []

    docs: list[Document] = []
    for result in results:
        if not result.url:
            continue

        doc = None
        try:
            doc = ctx.fetch_and_document(
                result.url,
                extra_meta={
                    "title": result.title,
                    "snippet": result.content,
                    "engine": result.engine,
                    "role": "recency",
                    "since": since.isoformat() if since else None,
                },
            )
        except Exception:
            pass

        if doc is None:
            doc_id = f"searxng_news:{hash(result.url) & 0xFFFFFFFF:08x}"
            text = f"{result.title}\n\n{result.content}" if result.content else result.title
            doc = ctx.make_document(
                doc_id=doc_id,
                text=text,
                metadata={
                    "source": result.url,
                    "url": result.url,
                    "title": result.title,
                    "snippet": result.content,
                    "engine": result.engine,
                    "role": "recency",
                    "since": since.isoformat() if since else None,
                    "fallback": "snippet",
                },
            )

        docs.append(doc)
        if len(docs) >= max_results:
            break

    return docs
