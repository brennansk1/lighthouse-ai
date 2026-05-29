"""Reuters news skill — entrypoints run, run_watchable, and named tools.

Access method: RSS feeds from feeds.reuters.com (Open Platform API approach).
AllSides bias rating: Center.

Security invariants:
  - No httpx / requests / urllib / socket / subprocess imports.
  - All I/O goes through ctx.fetch (passed as client to sources/news.py helpers).
  - EgressBlocked is caught and returns [] gracefully.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from lighthouse_ai.sources import news as _news

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

# Topic → feed URL mapping for Reuters public RSS feeds
_TOPIC_FEEDS: dict[str, str] = {
    "world":      "https://feeds.reuters.com/reuters/topNews",
    "business":   "https://feeds.reuters.com/reuters/businessNews",
    "technology": "https://feeds.reuters.com/reuters/technologyNews",
    "science":    "https://feeds.reuters.com/reuters/scienceNews",
    "markets":    "https://feeds.reuters.com/reuters/marketsNews",
    "politics":   "https://feeds.reuters.com/reuters/politicsNews",
    "health":     "https://feeds.reuters.com/reuters/healthNews",
}
_DEFAULT_FEED = _TOPIC_FEEDS["world"]

_OUTLET_ID = "reuters"


def _pick_feeds(query: str) -> list[str]:
    """Heuristically pick one or two topic feeds based on query keywords."""
    q = query.lower()
    feeds: list[str] = []
    for topic, url in _TOPIC_FEEDS.items():
        if topic in q:
            feeds.append(url)
    return feeds[:2] if feeds else [_DEFAULT_FEED]


# ---------------------------------------------------------------------------
# Named tools (called by run / run_watchable)
# ---------------------------------------------------------------------------


def search_articles(
    ctx: SkillContext,
    query: str,
    *,
    max_results: int = 10,
) -> list[Document]:
    """Search Reuters articles by fetching relevant topic feeds.

    Picks topic feeds based on keywords in ``query``, fetches the RSS,
    and returns items whose title/body contains at least one query term.
    """
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
    """Fetch a single Reuters article URL and return it as a Document."""
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
    """List recent Reuters articles in a topic, optionally filtered by since.

    This is the watchable tool — called on each Watch tick.

    Parameters
    ----------
    topic:
        One of: world, business, technology, science, markets, politics, health.
        Falls back to 'world' if not recognized.
    since:
        Return only items published after this timestamp.
    max_results:
        Maximum items to return.
    """
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
    """Research a question using Reuters news feeds.

    Fetches topic-relevant RSS feeds, filters by query terms, and returns
    Documents tagged with the Reuters provenance.  Degrades gracefully to an
    empty list on EgressBlocked or network errors.
    """
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
    """Watch Reuters for articles published after ``since``.

    Calls :func:`list_recent_in_topic` for each relevant topic feed and
    returns time-filtered items for continuous Watch coverage.
    """
    feeds = _pick_feeds(query)
    docs: list[Document] = []
    for feed_url in feeds:
        if len(docs) >= max_results:
            break
        topic = next(
            (k for k, v in _TOPIC_FEEDS.items() if v == feed_url), "world"
        )
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


