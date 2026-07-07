"""search_news — news-category search via SearXNG.

Uses the SearXNG 'news' category which routes to news-specific engines
(Google News, Bing News, etc.) and returns time-ordered Documents.

This tool is watchable: it accepts a ``since`` parameter and is the primary
Watch-mode tool for this skill.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import lighthouse_ai.sources.searxng as _searxng
from lighthouse_ai.sources.searxng import SearXNGUnavailable

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def search_news(
    ctx: SkillContext,
    query: str,
    *,
    since: datetime | None = None,
    max_results: int = 5,
) -> list[Document]:
    """Search for news articles and return time-ordered Documents.

    Uses SearXNG's news category.  When ``since`` is provided appends a date
    hint to the query so engines return articles published after that date.
    Results are returned in the order SearXNG delivers them (typically
    recency-ranked by the news engines).

    Args:
        ctx: The SkillContext passed to the skill entrypoint.
        query: Search query string.
        since: Optional lower-bound datetime for news recency filtering.
        max_results: Maximum number of documents to return.

    Returns:
        List of Documents (possibly empty if SearXNG is unavailable).
        Tagged with role="recency" — not the sole citation for load-bearing claims.
    """
    effective_query = query
    if since is not None:
        date_hint = since.strftime("%Y-%m-%d")
        effective_query = f"{query} after:{date_hint}"

    try:
        results = _searxng.search(effective_query, max_results=max_results * 2, categories="news")
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
                    "fallback": "snippet",
                },
            )

        docs.append(doc)
        if len(docs) >= max_results:
            break

    return docs
