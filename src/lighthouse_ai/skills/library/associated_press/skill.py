"""Associated Press news skill — entrypoints run, run_watchable, and named tools.

Access method: RSS feeds from apnews.com + web search fallback.
AllSides bias rating: Center.

Security invariants:
  - No httpx / requests / urllib / socket / subprocess imports.
  - All I/O goes through ctx.fetch / ctx.fetch_and_document.
  - EgressBlocked is caught and returns [] gracefully.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from lighthouse_ai.sources import news as _news

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

# AP RSS feed URLs (public, no key required)
_TOPIC_FEEDS: dict[str, str] = {
    "top": "https://feeds.apnews.com/apnews/us-politics",
    "politics": "https://feeds.apnews.com/apnews/us-politics",
    "technology": "https://feeds.apnews.com/apnews/technology",
    "business": "https://feeds.apnews.com/apnews/business",
    "sports": "https://feeds.apnews.com/apnews/sports",
    "science": "https://feeds.apnews.com/apnews/science",
    "health": "https://feeds.apnews.com/apnews/health",
    "entertainment": "https://feeds.apnews.com/apnews/entertainment",
    "world": "https://feeds.apnews.com/apnews/worldnews",
}
_DEFAULT_FEED = _TOPIC_FEEDS["top"]
_SEARCH_BASE = "https://apnews.com/search"
_OUTLET_ID = "associated_press"


def _pick_feeds(query: str) -> list[str]:
    q = query.lower()
    feeds: list[str] = []
    for topic, url in _TOPIC_FEEDS.items():
        if topic in q:
            feeds.append(url)
    return feeds[:2] if feeds else [_DEFAULT_FEED]


# ---------------------------------------------------------------------------
# Named tools
# ---------------------------------------------------------------------------


def search_articles(
    ctx: SkillContext,
    query: str,
    *,
    max_results: int = 10,
) -> list[Document]:
    """Search AP articles via topic feeds and web search fallback."""
    feeds = _pick_feeds(query)
    items: list = []
    terms = [t for t in query.lower().split() if len(t) > 3]
    for feed_url in feeds:
        try:
            raw = _news.fetch_outlet_feed(feed_url, client=ctx.fetch, max_results=max_results * 2)
        except Exception:
            continue
        for item in raw:
            text = ((item.title or "") + " " + (item.body or "")).lower()
            if not terms or any(t in text for t in terms):
                items.append(item)
            if len(items) >= max_results:
                break
        if len(items) >= max_results:
            break

    # Web search fallback if feed didn't return enough
    if len(items) < max_results // 2:
        try:
            web_items = _news.search_outlet(
                _SEARCH_BASE, query, client=ctx.fetch, max_results=max_results
            )
            items.extend(web_items[: max_results - len(items)])
        except Exception:
            pass

    return _news.items_to_documents(ctx, items[:max_results], outlet_id=_OUTLET_ID)


def fetch_article(
    ctx: SkillContext,
    url: str,
) -> list[Document]:
    """Fetch a single AP article URL."""
    try:
        doc = ctx.fetch_and_document(url, extra_meta={"outlet": _OUTLET_ID, "type": "news_article"})
    except Exception:
        return []
    return [doc] if doc is not None else []


def list_recent_in_topic(
    ctx: SkillContext,
    topic: str,
    *,
    since: datetime | None = None,
    max_results: int = 10,
) -> list[Document]:
    """List recent AP articles in a topic feed (watchable tool)."""
    feed_url = _TOPIC_FEEDS.get(topic.lower(), _DEFAULT_FEED)
    try:
        raw = _news.fetch_outlet_feed(feed_url, client=ctx.fetch, max_results=max_results * 3)
    except Exception:
        return []

    if since is not None:
        raw = _news.filter_since(raw, since)

    return _news.items_to_documents(ctx, raw[:max_results], outlet_id=_OUTLET_ID, feed_url=feed_url)


# ---------------------------------------------------------------------------
# Entrypoints
# ---------------------------------------------------------------------------


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using Associated Press news feeds."""
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
    """Watch AP for articles published after ``since``."""
    feeds = _pick_feeds(query)
    docs: list[Document] = []
    for feed_url in feeds:
        if len(docs) >= max_results:
            break
        topic = next((k for k, v in _TOPIC_FEEDS.items() if v == feed_url), "top")
        try:
            new_docs = list_recent_in_topic(
                ctx, topic, since=since, max_results=max_results - len(docs)
            )
        except _news.EgressBlocked:
            continue
        except Exception:
            continue
        docs.extend(new_docs)
    return docs[:max_results]
