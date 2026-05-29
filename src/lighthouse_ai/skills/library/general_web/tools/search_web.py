"""search_web — general web search via SearXNG.

Searches across all categories and returns Documents.  For each result URL
attempts a full-page fetch through the broker (Tier-A static fetch); if the
host is egress-blocked or the fetch fails falls back to the SearXNG snippet
so the skill is useful even when full-page fetch is not allowed.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import lighthouse_ai.sources.searxng as _searxng
from lighthouse_ai.sources.searxng import SearXNGUnavailable

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def search_web(
    ctx: SkillContext,
    query: str,
    *,
    since: datetime | None = None,
    max_results: int = 5,
) -> list[Document]:
    """Search the open web and return broker-admitted Documents.

    Args:
        ctx: The SkillContext passed to the skill entrypoint.
        query: Search query string.
        since: Optional lower-bound timestamp (Watch / recency filtering).
            SearXNG does not accept a ``since`` parameter directly; when provided
            this function appends a date hint to the query so recency-biased
            engines rank newer results higher.
        max_results: Maximum number of documents to return.

    Returns:
        List of Documents (possibly empty if SearXNG is unavailable).
    """
    effective_query = query
    if since is not None:
        date_hint = since.strftime("%Y-%m-%d")
        effective_query = f"{query} after:{date_hint}"

    try:
        results = _searxng.search(
            effective_query, max_results=max_results * 2, categories="general"
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
                extra_meta={"title": result.title, "snippet": result.content, "engine": result.engine},
            )
        except Exception:
            # EgressBlocked, timeout, or any fetch error → fall back to snippet
            pass

        if doc is None:
            # Snippet fallback: make_document from the SearXNG metadata
            doc_id = f"searxng_web:{hash(result.url) & 0xFFFFFFFF:08x}"
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
