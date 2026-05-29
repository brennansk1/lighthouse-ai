"""Offline tests for sources/news.py — the shared news adapter.

Tests cover:
- fetch_outlet_feed via a canned client (no network)
- parse_feed_bytes re-export
- items_to_documents via a mock SkillContext
- filter_since timestamp filtering
- parse_iso_timestamp parsing
- search_outlet HTML link extraction

No datetime.now() at import time.  No real network calls.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from lighthouse_ai.modes.monitor import MonitorItem
from lighthouse_ai.sources import news as _news

# ---------------------------------------------------------------------------
# Canned RSS/Atom bytes
# ---------------------------------------------------------------------------

_RSS_BYTES = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Article One</title>
      <link>https://example.com/article-1</link>
      <description>Summary of article one.</description>
      <pubDate>Fri, 01 Jan 2027 12:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Article Two</title>
      <link>https://example.com/article-2</link>
      <description>Summary of article two.</description>
      <pubDate>Sat, 02 Jan 2027 08:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Old Article</title>
      <link>https://example.com/old-article</link>
      <description>An older piece.</description>
      <pubDate>Mon, 01 Jun 2026 00:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""

_ATOM_BYTES = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Test Feed</title>
  <entry>
    <title>Atom Entry One</title>
    <link href="https://example.com/atom-1"/>
    <summary>Atom summary one.</summary>
    <updated>2027-01-10T09:00:00Z</updated>
  </entry>
</feed>"""

_EMPTY_BYTES = b"""<?xml version="1.0"?><notarss/>"""


# ---------------------------------------------------------------------------
# Fake HTTP response
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code


# ---------------------------------------------------------------------------
# parse_feed_bytes re-export
# ---------------------------------------------------------------------------


def test_parse_feed_bytes_rss():
    """parse_feed_bytes re-export works on valid RSS."""
    items = _news.parse_feed_bytes(_RSS_BYTES)
    assert len(items) == 3
    assert items[0].title == "Article One"
    assert items[0].url == "https://example.com/article-1"


def test_parse_feed_bytes_atom():
    """parse_feed_bytes re-export works on valid Atom."""
    items = _news.parse_feed_bytes(_ATOM_BYTES)
    assert len(items) == 1
    assert items[0].title == "Atom Entry One"


def test_parse_feed_bytes_malformed():
    """Malformed XML returns empty list, never raises."""
    items = _news.parse_feed_bytes(b"<not valid xml>>>")
    assert items == []


def test_parse_feed_bytes_unknown_root():
    """Unknown root element returns empty list."""
    items = _news.parse_feed_bytes(_EMPTY_BYTES)
    assert items == []


# ---------------------------------------------------------------------------
# fetch_outlet_feed via canned client
# ---------------------------------------------------------------------------


def test_fetch_outlet_feed_rss_via_client():
    """fetch_outlet_feed with a canned client returns parsed items."""
    def canned_client(url: str) -> FakeResponse:
        return FakeResponse(_RSS_BYTES)

    items = _news.fetch_outlet_feed("https://example.com/feed", client=canned_client, max_results=5)
    assert len(items) == 3  # RSS has 3 items, all within max_results


def test_fetch_outlet_feed_max_results_respected():
    """max_results caps the returned items."""
    def canned_client(url: str) -> FakeResponse:
        return FakeResponse(_RSS_BYTES)

    items = _news.fetch_outlet_feed("https://example.com/feed", client=canned_client, max_results=2)
    assert len(items) == 2


def test_fetch_outlet_feed_non_200_returns_empty():
    """Non-200 response returns empty list."""
    def canned_client(url: str) -> FakeResponse:
        return FakeResponse(b"", status_code=404)

    items = _news.fetch_outlet_feed("https://example.com/feed", client=canned_client)
    assert items == []


def test_fetch_outlet_feed_client_exception_returns_empty():
    """Client exception returns empty list gracefully."""
    def bad_client(url: str):
        raise ConnectionError("timeout")

    items = _news.fetch_outlet_feed("https://example.com/feed", client=bad_client)
    assert items == []


# ---------------------------------------------------------------------------
# filter_since
# ---------------------------------------------------------------------------


def test_filter_since_removes_old_items():
    """Items published before since are removed."""
    items = _news.parse_feed_bytes(_RSS_BYTES)
    assert len(items) == 3

    cutoff = datetime(2026, 12, 31, 0, 0, 0)  # before the Jan 2027 items
    filtered = _news.filter_since(items, cutoff)
    urls = {i.url for i in filtered}
    assert "https://example.com/article-1" in urls
    assert "https://example.com/article-2" in urls
    assert "https://example.com/old-article" not in urls


def test_filter_since_none_returns_all():
    """filter_since with no since parameter does not exist; passing a 2000 cutoff returns all recent items."""
    items = _news.parse_feed_bytes(_RSS_BYTES)
    very_old = datetime(2000, 1, 1)
    filtered = _news.filter_since(items, very_old)
    assert len(filtered) == 3


def test_filter_since_no_published_at_excluded():
    """Items without published_at are excluded on incremental ticks."""
    items = [
        MonitorItem(source="test", url="https://example.com/1", title="T1", body="", published_at=None),
        MonitorItem(source="test", url="https://example.com/2", title="T2", body="", published_at="2027-01-01T12:00:00Z"),
    ]
    cutoff = datetime(2026, 1, 1)
    filtered = _news.filter_since(items, cutoff)
    assert len(filtered) == 1
    assert filtered[0].url == "https://example.com/2"


# ---------------------------------------------------------------------------
# parse_iso_timestamp
# ---------------------------------------------------------------------------


def test_parse_iso_timestamp_iso_z():
    dt = _news.parse_iso_timestamp("2027-01-15T09:30:00Z")
    assert dt is not None
    assert dt.year == 2027
    assert dt.month == 1
    assert dt.day == 15


def test_parse_iso_timestamp_date_only():
    dt = _news.parse_iso_timestamp("2027-03-20")
    assert dt is not None
    assert dt.year == 2027
    assert dt.month == 3


def test_parse_iso_timestamp_rfc2822():
    dt = _news.parse_iso_timestamp("Thu, 01 Jan 2027 12:00:00 +0000")
    assert dt is not None
    assert dt.year == 2027


def test_parse_iso_timestamp_empty_returns_none():
    assert _news.parse_iso_timestamp("") is None


def test_parse_iso_timestamp_garbage_returns_none():
    assert _news.parse_iso_timestamp("not-a-date") is None


# ---------------------------------------------------------------------------
# items_to_documents via mock SkillContext
# ---------------------------------------------------------------------------


def _make_mock_ctx(outlet_id: str = "test_outlet") -> Any:
    """Build a minimal mock SkillContext that records make_document calls."""
    from lighthouse_ai.rag.chunker import Document

    docs_made: list[Document] = []

    def _make_document(*, doc_id: str, text: str, metadata: dict | None = None) -> Document:
        doc = Document(id=doc_id, text=text, metadata=dict(metadata or {}))
        doc.metadata["skill_id"] = outlet_id
        docs_made.append(doc)
        return doc

    ctx = MagicMock()
    ctx.make_document.side_effect = _make_document
    ctx._docs = docs_made
    return ctx


def test_items_to_documents_basic():
    """items_to_documents converts MonitorItems to Documents via ctx."""
    items = _news.parse_feed_bytes(_RSS_BYTES)
    ctx = _make_mock_ctx("reuters")
    docs = _news.items_to_documents(ctx, items, outlet_id="reuters")
    assert len(docs) == 3
    for doc in docs:
        assert doc.metadata["outlet"] == "reuters"
        assert doc.metadata["type"] == "news_article"
        assert doc.text


def test_items_to_documents_skips_empty_text():
    """Items with no title and no body are skipped."""
    items = [
        MonitorItem(source="test", url="https://example.com/x", title="", body="", published_at=None),
        MonitorItem(source="test", url="https://example.com/y", title="Has title", body="", published_at=None),
    ]
    ctx = _make_mock_ctx("bbc_news")
    docs = _news.items_to_documents(ctx, items, outlet_id="bbc_news")
    assert len(docs) == 1
    assert docs[0].text == "Has title"


def test_items_to_documents_feed_url_in_metadata():
    """feed_url is propagated to metadata."""
    items = _news.parse_feed_bytes(_RSS_BYTES)[:1]
    ctx = _make_mock_ctx("npr")
    docs = _news.items_to_documents(ctx, items, outlet_id="npr", feed_url="https://feeds.example.com/rss")
    assert docs[0].metadata["feed_url"] == "https://feeds.example.com/rss"


# ---------------------------------------------------------------------------
# search_outlet HTML fallback
# ---------------------------------------------------------------------------


def test_search_outlet_returns_empty_on_non_200():
    """Non-200 response from all param variants returns empty list."""
    def client(url: str) -> FakeResponse:
        return FakeResponse(b"<html><body>Not found</body></html>", status_code=404)

    result = _news.search_outlet("https://example.com/search", "test query", client=client)
    assert result == []


def test_search_outlet_extracts_links():
    """search_outlet extracts link items from HTML when response is 200."""
    html = b"""<html><body>
    <a href="/article/test-story-one">This is a substantial article title</a>
    <a href="/article/test-story-two">Another article about something important here</a>
    </body></html>"""

    def client(url: str) -> FakeResponse:
        return FakeResponse(html, status_code=200)

    result = _news.search_outlet("https://example.com/search", "test", client=client)
    assert len(result) >= 1
    assert any("test-story" in item.url for item in result)
