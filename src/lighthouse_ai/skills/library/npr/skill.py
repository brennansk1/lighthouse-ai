"""NPR news skill — entrypoints run, run_watchable, and named tools.

Access method: RSS feeds from feeds.npr.org + web search + audio transcript
integration via lighthouse_ai.sources.transcript.

AllSides bias rating: Lean Left.

Security invariants:
  - No httpx / requests / urllib / socket / subprocess imports.
  - All network I/O goes through ctx.fetch / ctx.fetch_and_document.
  - EgressBlocked is caught and returns [] gracefully.
  - transcript module is imported from lighthouse_ai.sources (not inside skill
    scan) so its stdlib imports are not flagged by the import guard.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from lighthouse_ai.sources import news as _news
from lighthouse_ai.sources import transcript as _transcript

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

# NPR public RSS feeds (no API key required)
_TOPIC_FEEDS: dict[str, str] = {
    "top":          "https://feeds.npr.org/1001/rss.xml",
    "news":         "https://feeds.npr.org/1001/rss.xml",
    "us":           "https://feeds.npr.org/1003/rss.xml",
    "world":        "https://feeds.npr.org/1004/rss.xml",
    "politics":     "https://feeds.npr.org/1014/rss.xml",
    "business":     "https://feeds.npr.org/1006/rss.xml",
    "technology":   "https://feeds.npr.org/1019/rss.xml",
    "science":      "https://feeds.npr.org/1007/rss.xml",
    "health":       "https://feeds.npr.org/1128/rss.xml",
    "arts":         "https://feeds.npr.org/1008/rss.xml",
    "education":    "https://feeds.npr.org/1013/rss.xml",
    "culture":      "https://feeds.npr.org/1008/rss.xml",
}
_DEFAULT_FEED = _TOPIC_FEEDS["top"]
_SEARCH_BASE = "https://www.npr.org/search"
_OUTLET_ID = "npr"


def _pick_feeds(query: str) -> list[str]:
    q = query.lower()
    feeds: list[str] = []
    for topic, url in _TOPIC_FEEDS.items():
        if topic in q:
            feeds.append(url)
    seen: list[str] = []
    for f in feeds:
        if f not in seen:
            seen.append(f)
    return seen[:2] if seen else [_DEFAULT_FEED]


# ---------------------------------------------------------------------------
# Named tools
# ---------------------------------------------------------------------------


def search_articles(
    ctx: SkillContext,
    query: str,
    *,
    max_results: int = 10,
) -> list[Document]:
    """Search NPR articles via topic feeds + web search fallback."""
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
    """Fetch a single NPR article URL."""
    try:
        doc = ctx.fetch_and_document(url, extra_meta={"outlet": _OUTLET_ID, "type": "news_article"})
    except Exception:
        return []
    return [doc] if doc is not None else []


def fetch_audio_transcript(
    ctx: SkillContext,
    audio_ref: str,
) -> list[Document]:
    """Attempt to retrieve a transcript for an NPR audio segment.

    Uses ``sources.transcript.transcribe_or_fetch_captions`` (ASR stub in v1;
    returns ``None`` if no provider is registered).  Falls back to an empty
    list so callers can use metadata-only Documents instead.

    Parameters
    ----------
    audio_ref:
        An NPR audio URL or segment identifier.
    """
    text = _transcript.transcribe_or_fetch_captions(audio_ref)
    if not text:
        return []
    doc = ctx.make_document(
        doc_id=f"npr:transcript:{hash(audio_ref) & 0xFFFFFFFF:08x}",
        text=text,
        metadata={
            "source": _OUTLET_ID,
            "url": audio_ref,
            "type": "audio_transcript",
            "outlet": _OUTLET_ID,
        },
    )
    return [doc]


def list_recent_in_topic(
    ctx: SkillContext,
    topic: str,
    *,
    since: datetime | None = None,
    max_results: int = 10,
) -> list[Document]:
    """List recent NPR articles in a topic feed (watchable tool)."""
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
    """Research a question using NPR news feeds."""
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
    """Watch NPR for articles published after ``since``."""
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
