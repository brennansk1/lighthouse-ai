"""Wikipedia fetch-page tool — retrieve a page summary or full extract.

Two strategies are offered:

1. **REST summary** (fast, 1 request): ``/api/rest_v1/page/summary/<title>``
   — returns the lead paragraph + thumbnail metadata as JSON.  Good for Ask /
   quick orientation.

2. **Action API extract** (full text, 1 request):
   ``action=query&prop=extracts&titles=<title>&explaintext=1``
   — returns plain-text sections.  Good for Investigate / Reconstruct.

Returns a :class:`Document` (via ``ctx.make_document``) or ``None`` when the
page does not exist.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_EXTRACT_URL = (
    "https://en.wikipedia.org/w/api.php"
    "?action=query&prop=extracts&titles={title}"
    "&exintro=0&explaintext=1&format=json&utf8=1"
)


def fetch_page(
    ctx: SkillContext,
    title: str,
    *,
    full_extract: bool = False,
) -> Document | None:
    """Fetch a Wikipedia page and return a Document.

    Parameters
    ----------
    ctx:
        The skill context (provides ``fetch`` + ``make_document``).
    title:
        Wikipedia page title (spaces or underscores, ASCII or Unicode).
    full_extract:
        When ``True`` use the Action API ``prop=extracts`` to get the full
        plain-text body; otherwise use the REST summary endpoint (lead only).
    """
    encoded = _url_encode(title)
    if full_extract:
        return _fetch_extract(ctx, title, encoded)
    return _fetch_summary(ctx, title, encoded)


def _fetch_summary(ctx: SkillContext, title: str, encoded: str) -> Document | None:
    url = _SUMMARY_URL.format(title=encoded)
    resp = ctx.fetch(url)
    if resp.status_code == 404:
        return None
    try:
        data = json.loads(resp.content)
    except Exception:
        return None
    if data.get("type") == "disambiguation":
        # Return a minimal document noting the disambiguation.
        return ctx.make_document(
            doc_id=f"wikipedia:{encoded}:summary",
            text=data.get("extract", f"{title} is a disambiguation page."),
            metadata={
                "source": "wikipedia",
                "title": data.get("title", title),
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                "type": "disambiguation",
            },
        )
    text = data.get("extract", "")
    if not text:
        return None
    return ctx.make_document(
        doc_id=f"wikipedia:{encoded}:summary",
        text=text,
        metadata={
            "source": "wikipedia",
            "title": data.get("title", title),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            "description": data.get("description", ""),
            "type": "summary",
        },
    )


def _fetch_extract(ctx: SkillContext, title: str, encoded: str) -> Document | None:
    url = _EXTRACT_URL.format(title=encoded)
    resp = ctx.fetch(url)
    try:
        data = json.loads(resp.content)
    except Exception:
        return None
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return None
    page = next(iter(pages.values()))
    if page.get("pageid", -1) == -1:
        return None  # missing page
    text = page.get("extract", "")
    if not text:
        return None
    page_title = page.get("title", title)
    return ctx.make_document(
        doc_id=f"wikipedia:{encoded}:extract",
        text=text,
        metadata={
            "source": "wikipedia",
            "title": page_title,
            "url": f"https://en.wikipedia.org/wiki/{_url_encode(page_title)}",
            "pageid": page.get("pageid"),
            "type": "extract",
        },
    )


def _url_encode(text: str) -> str:
    """Percent-encode a title for a URL path segment (stdlib only)."""
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~:@!$&'()*+,;="
    encoded = []
    for ch in text.encode("utf-8"):
        c = chr(ch)
        if c in safe:
            encoded.append(c)
        elif c == " ":
            encoded.append("_")
        else:
            encoded.append(f"%{ch:02X}")
    return "".join(encoded)
