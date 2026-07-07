"""Wikipedia infobox extraction tool.

Retrieves the raw wikitext for a page via the Action API
(``action=query&prop=revisions&rvprop=content``) then delegates to
:mod:`~lighthouse_ai.skills.library.wikipedia.parsers.infobox` for parsing.

Returns a dict of ``{field: value}`` or an empty dict when no infobox is found.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..parsers.infobox import parse_infobox

if TYPE_CHECKING:
    from lighthouse_ai.skills.capabilities import SkillContext

_WIKITEXT_URL = (
    "https://en.wikipedia.org/w/api.php"
    "?action=query&prop=revisions&rvprop=content&rvslots=main"
    "&titles={title}&format=json&utf8=1&formatversion=2"
)


def extract_infobox(ctx: SkillContext, title: str) -> dict[str, str]:
    """Return the infobox fields for a Wikipedia page as a plain dict.

    Parameters
    ----------
    ctx:
        The skill context.
    title:
        Wikipedia page title.

    Returns
    -------
    dict[str, str]
        Parsed infobox fields; empty dict when no infobox is present or the
        fetch fails.
    """
    encoded = _url_encode(title)
    url = _WIKITEXT_URL.format(title=encoded)
    resp = ctx.fetch(url)
    try:
        data = json.loads(resp.content)
    except Exception:
        return {}

    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return {}
    page = pages[0] if isinstance(pages, list) else next(iter(pages.values()))
    revisions = page.get("revisions", [])
    if not revisions:
        return {}
    rev = revisions[0]
    # formatversion=2 nests under slots.main.content; fallback to legacy *
    wikitext: str = ""
    if isinstance(rev, dict):
        slots = rev.get("slots", {})
        if slots:
            wikitext = slots.get("main", {}).get("content", "")
        elif "*" in rev:
            wikitext = rev["*"]
    if not wikitext:
        return {}
    return parse_infobox(wikitext)


def _url_encode(text: str) -> str:
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
