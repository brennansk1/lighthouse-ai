"""Wikipedia category-walk tool.

Traverses a Wikipedia category tree, returning page titles up to a depth and
result limit. Uses ``list=categorymembers`` from the Action API.

No external libraries — only ctx.fetch + stdlib json.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lighthouse_ai.skills.capabilities import SkillContext

_CATMEMBERS_URL = (
    "https://en.wikipedia.org/w/api.php"
    "?action=query&list=categorymembers&cmtitle=Category:{category}"
    "&cmtype={cmtype}&cmlimit={limit}&format=json&utf8=1"
)


def walk_category(
    ctx: SkillContext,
    category: str,
    *,
    limit: int = 20,
    include_subcategories: bool = False,
) -> list[dict]:
    """Return page titles (and optionally subcategory names) in a Wikipedia category.

    Parameters
    ----------
    ctx:
        Skill context.
    category:
        Category name without the ``Category:`` prefix (e.g. ``"Machine learning"``).
    limit:
        Maximum number of members to return.
    include_subcategories:
        When True, also include subcategory entries in the result.

    Returns
    -------
    list[dict]
        Each entry has ``{title, url, type}`` where ``type`` is ``"page"`` or
        ``"subcat"``.
    """
    cmtype = "page|subcat" if include_subcategories else "page"
    encoded_cat = _url_encode(category)
    url = _CATMEMBERS_URL.format(category=encoded_cat, cmtype=cmtype, limit=min(limit, 500))
    resp = ctx.fetch(url)
    try:
        data = json.loads(resp.content)
    except Exception:
        return []

    members = data.get("query", {}).get("categorymembers", [])
    results: list[dict] = []
    for member in members:
        title = member.get("title", "")
        ns = member.get("ns", 0)
        entry_type = "subcat" if ns == 14 else "page"
        # Subcategory titles include "Category:" prefix — strip it for display.
        display_title = title.removeprefix("Category:") if entry_type == "subcat" else title
        results.append(
            {
                "title": display_title,
                "url": f"https://en.wikipedia.org/wiki/{_url_encode(title)}",
                "type": entry_type,
            }
        )
    return results


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
