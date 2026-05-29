"""search_videos — video search via SearXNG (hands off to youtube skill).

Searches for videos using the SearXNG 'videos' category.  Returns Documents
containing video URLs, titles, and descriptions.  Full transcript extraction
is the responsibility of the dedicated YouTube skill when available; this tool
provides discovery-level metadata only.

The planner should prefer the YouTube skill for deep transcript analysis.
Use this tool when:
- No YouTube skill is selected
- The goal is quick video discovery, not transcript analysis
- Cross-platform video search is desired (Vimeo, etc.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import lighthouse_ai.sources.searxng as _searxng
from lighthouse_ai.sources.searxng import SearXNGUnavailable

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def search_videos(
    ctx: SkillContext,
    query: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Search for videos and return Documents with URLs and descriptions.

    Returns metadata-only Documents.  For full video transcript extraction,
    use the dedicated YouTube skill.  Results from this tool are grade C and
    should not be sole citations for load-bearing claims.

    Args:
        ctx: The SkillContext passed to the skill entrypoint.
        query: Video search query string.
        max_results: Maximum number of video results to return.

    Returns:
        List of Documents with video metadata (URL, title, description).
    """
    try:
        results = _searxng.search(
            query, max_results=max_results * 2, categories="videos"
        )
    except SearXNGUnavailable:
        return []

    docs: list[Document] = []
    for result in results:
        if not result.url:
            continue
        doc_id = f"searxng_video:{hash(result.url) & 0xFFFFFFFF:08x}"
        text_parts = [result.title] if result.title else []
        if result.content:
            text_parts.append(result.content)
        text_parts.append(f"Video URL: {result.url}")
        doc = ctx.make_document(
            doc_id=doc_id,
            text="\n\n".join(text_parts),
            metadata={
                "source": result.url,
                "url": result.url,
                "title": result.title,
                "engine": result.engine,
                "media_type": "video",
                "note": "Metadata only. For transcript, use YouTube skill.",
            },
        )
        docs.append(doc)
        if len(docs) >= max_results:
            break

    return docs
