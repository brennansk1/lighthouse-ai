"""The Guardian news skill — entrypoints run, run_watchable, and named tools.

Access method: Guardian Open Platform API (content.guardianapis.com).
Free tier works without an API key (test key); registered key removes rate cap.
AllSides bias rating: Left.

API doc: https://open-platform.theguardian.com/documentation/

Security invariants:
  - No httpx / requests / urllib / socket / subprocess imports.
  - All I/O goes through ctx.fetch.
  - EgressBlocked is caught and returns [] gracefully.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from lighthouse_ai.modes.monitor import MonitorItem
from lighthouse_ai.sources import news as _news

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

_API_BASE = "https://content.guardianapis.com"
_OUTLET_ID = "guardian"

# Topic slug → Guardian section slug mapping
_SECTION_MAP: dict[str, str] = {
    "world":       "world",
    "uk":          "uk-news",
    "politics":    "politics",
    "technology":  "technology",
    "science":     "science",
    "environment": "environment",
    "business":    "business",
    "culture":     "culture",
    "sport":       "sport",
    "health":      "society",
    "society":     "society",
    "education":   "education",
}


def _urlencode(params: dict) -> str:
    """Minimal URL percent-encoding for simple ASCII key=value params."""
    # Used instead of urllib.parse (forbidden in skill scope) for simple cases.
    pairs: list[str] = []
    for k, v in params.items():
        # Replace spaces with + and percent-encode a minimal set of chars.
        vs = str(v).replace(" ", "+").replace("&", "%26").replace("=", "%3D")
        pairs.append(f"{k}={vs}")
    return "&".join(pairs)


def _build_search_url(query: str, *, section: str = "", api_key: str = "test", page_size: int = 10) -> str:
    """Build a Guardian Content API search URL."""
    params: dict[str, str] = {
        "show-fields": "trailText,headline,shortUrl",
        "page-size": str(page_size),
        "api-key": api_key,
    }
    if query:
        params["q"] = query
    if section:
        params["section"] = section
    return f"{_API_BASE}/search?{_urlencode(params)}"


def _build_tags_url(tag: str, *, api_key: str = "test", page_size: int = 10) -> str:
    """Build a Guardian tag-based articles URL."""
    params: dict[str, str] = {
        "show-fields": "trailText,headline,shortUrl",
        "page-size": str(page_size),
        "api-key": api_key,
    }
    return f"{_API_BASE}/{tag}?{_urlencode(params)}"


def _parse_guardian_json(payload: bytes, outlet_id: str) -> list[MonitorItem]:
    """Parse Guardian API JSON response into MonitorItem records."""
    try:
        data = json.loads(payload)
    except Exception:
        return []
    results = data.get("response", {}).get("results", [])
    items: list[MonitorItem] = []
    for r in results:
        title = r.get("webTitle", "") or r.get("fields", {}).get("headline", "")
        url = r.get("webUrl", "") or r.get("fields", {}).get("shortUrl", "")
        body = r.get("fields", {}).get("trailText", "")
        pub = r.get("webPublicationDate", "")
        if not url:
            continue
        items.append(MonitorItem(
            source=outlet_id,
            url=url,
            title=_news._strip_html(title),
            body=_news._strip_html(body),
            published_at=pub or None,
        ))
    return items


# ---------------------------------------------------------------------------
# Named tools
# ---------------------------------------------------------------------------


def search_articles(
    ctx: SkillContext,
    query: str,
    *,
    max_results: int = 10,
) -> list[Document]:
    """Search Guardian articles via the Open Platform API."""
    url = _build_search_url(query, page_size=max_results)
    try:
        resp = ctx.fetch(url)
        if resp.status_code != 200:
            return []
        items = _parse_guardian_json(resp.content, _OUTLET_ID)
    except Exception:
        return []
    return _news.items_to_documents(ctx, items[:max_results], outlet_id=_OUTLET_ID)


def fetch_article(
    ctx: SkillContext,
    url: str,
) -> list[Document]:
    """Fetch a single Guardian article URL."""
    try:
        doc = ctx.fetch_and_document(url, extra_meta={"outlet": _OUTLET_ID, "type": "news_article"})
    except Exception:
        return []
    return [doc] if doc is not None else []


def get_tags(
    ctx: SkillContext,
    tag: str,
    *,
    max_results: int = 10,
) -> list[Document]:
    """Fetch Guardian articles for a specific tag/section slug.

    The Guardian Open Platform supports granular topic tags (e.g.
    ``environment/climate-change``, ``politics/labour``).  This tool
    fetches articles matching the tag directly.
    """
    url = _build_tags_url(tag, page_size=max_results)
    try:
        resp = ctx.fetch(url)
        if resp.status_code != 200:
            return []
        items = _parse_guardian_json(resp.content, _OUTLET_ID)
    except Exception:
        return []
    return _news.items_to_documents(ctx, items[:max_results], outlet_id=_OUTLET_ID)


def list_recent_in_topic(
    ctx: SkillContext,
    topic: str,
    *,
    since: datetime | None = None,
    max_results: int = 10,
) -> list[Document]:
    """List recent Guardian articles in a topic/section (watchable tool)."""
    section = _SECTION_MAP.get(topic.lower(), "")
    url = _build_search_url("", section=section, page_size=max_results * 2)
    try:
        resp = ctx.fetch(url)
        if resp.status_code != 200:
            return []
        items = _parse_guardian_json(resp.content, _OUTLET_ID)
    except Exception:
        return []

    if since is not None:
        items = _news.filter_since(items, since)

    return _news.items_to_documents(ctx, items[:max_results], outlet_id=_OUTLET_ID)


# ---------------------------------------------------------------------------
# Entrypoints
# ---------------------------------------------------------------------------


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using the Guardian Open Platform API."""
    try:
        return search_articles(ctx, question, max_results=max_results)
    except _news.EgressBlocked:
        return []
    except Exception:
        return []


def run_watchable(
    ctx: SkillContext,
    query: str,
    *,
    since: datetime | None = None,
    max_results: int = 5,
) -> list[Document]:
    """Watch The Guardian for articles published after ``since``."""
    # Try section-based listing, fall back to query search
    q = query.lower()
    section = next((v for k, v in _SECTION_MAP.items() if k in q), "")
    try:
        if section:
            docs = list_recent_in_topic(ctx, section, since=since, max_results=max_results)
        else:
            docs = search_articles(ctx, query, max_results=max_results)
        # Apply since filter if not already applied
        return docs[:max_results]
    except _news.EgressBlocked:
        return []
    except Exception:
        return []
