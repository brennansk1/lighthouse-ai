"""BBC News skill — entrypoints run, run_watchable, and named tools.

Access method: RSS feeds from feeds.bbci.co.uk (RSS only; no Open Platform).
AllSides bias rating: Lean Left.

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

# BBC public RSS feeds (no API key required)
_TOPIC_FEEDS: dict[str, str] = {
    "world":       "https://feeds.bbci.co.uk/news/world/rss.xml",
    "uk":          "https://feeds.bbci.co.uk/news/uk/rss.xml",
    "technology":  "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "science":     "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "business":    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "health":      "https://feeds.bbci.co.uk/news/health/rss.xml",
    "politics":    "https://feeds.bbci.co.uk/news/politics/rss.xml",
    "top":         "https://feeds.bbci.co.uk/news/rss.xml",
}
_DEFAULT_FEED = _TOPIC_FEEDS["top"]
_OUTLET_ID = "bbc_news"


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
    """Search BBC News articles via topic RSS feeds."""
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
    return _news.items_to_documents(ctx, items[:max_results], outlet_id=_OUTLET_ID)


def fetch_article(
    ctx: SkillContext,
    url: str,
) -> list[Document]:
    """Fetch a single BBC article URL through the broker."""
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
    """List recent BBC News articles in a topic feed (watchable tool)."""
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
    """Research a question using BBC News RSS feeds."""
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
    """Watch BBC News for articles published after ``since``."""
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
