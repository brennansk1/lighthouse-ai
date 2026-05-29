"""search_scholar — shallow academic search via SearXNG.

Searches using the 'science' category and filters results to scholarly
domains (arxiv, pubmed, semanticscholar, etc.) as defined in the searxng
module's SCHOLARLY_DOMAINS constant.

Note: For deep scholarly search prefer the dedicated arXiv / OpenAlex / PubMed
skills. This tool provides orientation-level coverage when those sources are not
selected; results are grade C (inherited from the skill manifest) not grade A.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import lighthouse_ai.sources.searxng as _searxng
from lighthouse_ai.sources.searxng import SearXNGUnavailable

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def search_scholar(
    ctx: SkillContext,
    query: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Search for scholarly articles via SearXNG (shallow academic coverage).

    Filters to scholarly domains so non-academic results are excluded.
    Useful for orientation; for citation-grade evidence use dedicated skills
    (arXiv, OpenAlex, PubMed).

    Args:
        ctx: The SkillContext passed to the skill entrypoint.
        query: Search query string.
        max_results: Maximum number of documents to return.

    Returns:
        List of Documents filtered to scholarly domains.
    """
    try:
        results = _searxng.search(
            query, max_results=max_results * 3, scholarly=True, categories="science"
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
                    "scholarly": True,
                },
            )
        except Exception:
            pass

        if doc is None:
            doc_id = f"searxng_scholar:{hash(result.url) & 0xFFFFFFFF:08x}"
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
                    "scholarly": True,
                    "fallback": "snippet",
                },
            )

        docs.append(doc)
        if len(docs) >= max_results:
            break

    return docs
