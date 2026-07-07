"""Wikipedia search tool — use the Action API opensearch or list=search endpoint.

Returns a list of dicts: [{title, snippet, url}, ...].  The caller (skill.py)
decides whether to stop here or fetch full pages for the top hits.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lighthouse_ai.skills.capabilities import SkillContext

_SEARCH_URL = (
    "https://en.wikipedia.org/w/api.php"
    "?action=query&list=search&srlimit={limit}&srsearch={query}"
    "&srprop=snippet&format=json&utf8=1"
)


def search(ctx: SkillContext, query: str, *, limit: int = 5) -> list[dict]:
    """Search Wikipedia and return a list of {title, snippet, url} dicts.

    Uses the MediaWiki Action API ``list=search`` endpoint which requires no
    authentication and honours robots.txt.  The snippet is raw wikitext-markup
    excerpts — the caller strips it if needed.
    """
    encoded_query = _url_encode(query)
    url = _SEARCH_URL.format(query=encoded_query, limit=min(limit, 50))
    resp = ctx.fetch(url)
    try:
        data = json.loads(resp.content)
    except Exception:
        return []

    results: list[dict] = []
    for hit in data.get("query", {}).get("search", []):
        title = hit.get("title", "")
        results.append(
            {
                "title": title,
                "snippet": _strip_markup(hit.get("snippet", "")),
                "url": f"https://en.wikipedia.org/wiki/{_url_encode(title)}",
                "pageid": hit.get("pageid"),
            }
        )
    return results


def _url_encode(text: str) -> str:
    """Percent-encode a string for use in a URL query param (stdlib only)."""
    # Build a percent-encoded string without importing urllib.
    # We only need to encode characters that are unsafe in a query string.
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    encoded = []
    for ch in text.encode("utf-8"):
        c = chr(ch)
        if c in safe:
            encoded.append(c)
        elif c == " ":
            encoded.append("+")
        else:
            encoded.append(f"%{ch:02X}")
    return "".join(encoded)


def _strip_markup(text: str) -> str:
    """Strip basic HTML tags from a Wikipedia snippet (no external deps)."""
    out: list[str] = []
    in_tag = False
    for ch in text:
        if ch == "<":
            in_tag = True
        elif ch == ">":
            in_tag = False
        elif not in_tag:
            out.append(ch)
    return "".join(out)
