"""search_images — image search via SearXNG (URLs + alt-text only).

Returns Documents containing image URLs and alt-text metadata.
No image binary data is fetched through the broker — only the image URL,
thumbnail URL (if provided), and alt/title text is recorded.

This tool returns orientation metadata, not pixel data.  Use cases:
- Finding source URLs for images described in a research question
- Getting alt-text / caption metadata for accessibility or context
- Locating image provenance (which page embeds a given image)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import lighthouse_ai.sources.searxng as _searxng
from lighthouse_ai.sources.searxng import SearXNGUnavailable

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def search_images(
    ctx: SkillContext,
    query: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Search for images and return Documents with URLs and alt-text metadata.

    No binary image data is fetched.  Each Document's text contains the image
    title and any available descriptive metadata so the planner can reason about
    image provenance without loading pixel data through the broker.

    Args:
        ctx: The SkillContext passed to the skill entrypoint.
        query: Image search query string.
        max_results: Maximum number of image results to return.

    Returns:
        List of Documents with image metadata (URLs, titles, alt-text).
    """
    try:
        results = _searxng.search(
            query, max_results=max_results * 2, categories="images"
        )
    except SearXNGUnavailable:
        return []

    docs: list[Document] = []
    for result in results:
        if not result.url:
            continue
        # Images: make_document from metadata only — do NOT fetch binary content.
        doc_id = f"searxng_image:{hash(result.url) & 0xFFFFFFFF:08x}"
        text_parts = [result.title] if result.title else []
        if result.content:
            text_parts.append(result.content)
        text_parts.append(f"Image URL: {result.url}")
        doc = ctx.make_document(
            doc_id=doc_id,
            text="\n\n".join(text_parts),
            metadata={
                "source": result.url,
                "url": result.url,
                "title": result.title,
                "image_url": result.url,
                "engine": result.engine,
                "media_type": "image",
            },
        )
        docs.append(doc)
        if len(docs) >= max_results:
            break

    return docs
