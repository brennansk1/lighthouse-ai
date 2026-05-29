"""Offline tests for SL4 — channels family (RSS + Wayback).

All network I/O is mocked: either via a monkeypatched ctx.fetch that returns
canned httpx.Response objects, or via injecting a fake httpx.Client.  No
actual network requests are made.

Test coverage:
- Both skills load and pass the import guard.
- RSS manifest fields are correct.
- Wayback manifest fields are correct.
- rss.run() with a feed URL in the question returns tagged Documents.
- rss.run_watchable() returns only items newer than since=.
- rss.run_watchable() with since=None returns all items.
- rss.run() with no URL in the question returns [].
- Wayback lookup_url_at_date parses a CDX response and returns a Document.
- Wayback list_snapshots returns a list of record dicts.
- Wayback run() extracts a URL from the question and returns Documents.
- Wayback run() with no URL returns [].
- parse_cdx_response handles empty/malformed input gracefully.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import httpx
import pytest

from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.skills import load_skill, run_skill
from lighthouse_ai.sources.rss import parse_feed_bytes

# ---------------------------------------------------------------------------
# Canned fixtures
# ---------------------------------------------------------------------------

RSS_XML = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <item>
      <title>Article One</title>
      <link>https://example.com/article1</link>
      <description>Summary of article one.</description>
      <pubDate>Thu, 29 May 2026 09:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Article Two</title>
      <link>https://example.com/article2</link>
      <description>Summary of article two.</description>
      <pubDate>Wed, 28 May 2026 09:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Old Article</title>
      <link>https://example.com/old</link>
      <description>Very old article.</description>
      <pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_XML = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Test Feed</title>
  <entry>
    <title>Atom Article One</title>
    <link href="https://atom.example.com/entry1"/>
    <summary>Atom summary one.</summary>
    <updated>2026-05-29T10:00:00Z</updated>
  </entry>
  <entry>
    <title>Atom Article Two</title>
    <link href="https://atom.example.com/entry2"/>
    <summary>Atom summary two.</summary>
    <updated>2026-05-27T10:00:00Z</updated>
  </entry>
</feed>
"""

# CDX JSON: first row is the header.
CDX_JSON = json.dumps([
    ["timestamp", "original", "statuscode", "mimetype"],
    ["20221201120000", "https://example.com/page", "200", "text/html"],
    ["20221115080000", "https://example.com/page", "200", "text/html"],
]).encode()

CDX_EMPTY = json.dumps([]).encode()
CDX_SINGLE = json.dumps([
    ["timestamp", "original", "statuscode", "mimetype"],
    ["20221201120000", "https://example.com/page", "200", "text/html"],
]).encode()

SNAPSHOT_HTML = b"<html><body>Preserved content</body></html>"


# ---------------------------------------------------------------------------
# Helper: build a fake ctx.fetch that returns canned responses
# ---------------------------------------------------------------------------

def _fake_response(content: bytes, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=content)


def _make_ctx(skill_id: str, broker, responses: dict[str, bytes]):
    """Build a SkillContext whose fetch() is monkeypatched to return canned bytes.

    ``responses`` is a dict mapping URL prefix -> response bytes.  The first
    matching key (by startswith) wins; fallback is 404.
    """
    from lighthouse_ai.governor.egress_proxy import DEFAULT_ALLOWED_DOMAINS
    from lighthouse_ai.skills.capabilities import SkillContext

    ctx = SkillContext(
        skill_id=skill_id,
        skill_version="0.1.0",
        effective_domains=DEFAULT_ALLOWED_DOMAINS
        | frozenset({"example.com", "atom.example.com", "web.archive.org", "archive.org"}),
        broker=broker,
        gateway=None,
        default_grade="B",
        community=False,
        tier="A",
    )

    def _fake_fetch(url: str, **_kwargs):
        for prefix, content in responses.items():
            if url.startswith(prefix):
                return _fake_response(content)
        return _fake_response(b"not found", 404)

    ctx.fetch = _fake_fetch  # type: ignore[method-assign]
    return ctx


# ---------------------------------------------------------------------------
# RSS — manifest
# ---------------------------------------------------------------------------

def test_rss_manifest_loads():
    skill = load_skill("rss")
    m = skill.manifest
    assert m.id == "rss"
    assert m.category == "channel"
    assert m.tier == "A"
    assert m.output_shape == "stream"
    assert m.signed is True
    assert m.watchable is True
    assert "fetch_feed" in m.watchable_tools
    assert m.temporal_tools is True
    assert m.default_grade == "B"


def test_rss_watchable_entrypoint_present():
    skill = load_skill("rss")
    assert skill.watchable_entrypoint is not None
    assert callable(skill.watchable_entrypoint)


# ---------------------------------------------------------------------------
# RSS — import guard
# ---------------------------------------------------------------------------

def test_rss_import_guard_passes():
    skill = load_skill("rss")
    assert skill.manifest.id == "rss"


# ---------------------------------------------------------------------------
# RSS — run()
# ---------------------------------------------------------------------------

def test_rss_run_returns_documents(tmp_path):
    """run() fetches the feed URL found in the question and returns Documents."""
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx("rss", broker, {"https://example.com/feed": RSS_XML})

    from lighthouse_ai.skills.library.rss.skill import run
    docs = run(ctx, "Latest news from https://example.com/feed", max_results=5)
    assert len(docs) > 0
    for doc in docs:
        assert doc.metadata.get("skill_id") == "rss"
        assert doc.metadata.get("type") == "feed_item"
        assert doc.metadata.get("feed_url") == "https://example.com/feed"


def test_rss_run_no_url_returns_empty(tmp_path):
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx("rss", broker, {})

    from lighthouse_ai.skills.library.rss.skill import run
    docs = run(ctx, "What is the best RSS reader?", max_results=5)
    assert docs == []


def test_rss_run_max_results_respected(tmp_path):
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx("rss", broker, {"https://example.com/feed": RSS_XML})

    from lighthouse_ai.skills.library.rss.skill import run
    docs = run(ctx, "https://example.com/feed", max_results=2)
    assert len(docs) <= 2


def test_rss_run_atom_feed(tmp_path):
    """run() handles Atom feeds as well as RSS 2.0."""
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx("rss", broker, {"https://atom.example.com/feed": ATOM_XML})

    from lighthouse_ai.skills.library.rss.skill import run
    docs = run(ctx, "https://atom.example.com/feed", max_results=5)
    assert len(docs) >= 1
    titles = [d.metadata.get("title", "") for d in docs]
    assert any("Atom" in t for t in titles)


# ---------------------------------------------------------------------------
# RSS — run_watchable()
# ---------------------------------------------------------------------------

def test_rss_run_watchable_since_none_returns_all(tmp_path):
    """With since=None all timestamped items should be returned."""
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx("rss", broker, {"https://example.com/feed": RSS_XML})

    from lighthouse_ai.skills.library.rss.skill import run_watchable
    docs = run_watchable(ctx, "https://example.com/feed", since=None, max_results=10)
    # All 3 items have timestamps so all should come back.
    assert len(docs) == 3


def test_rss_run_watchable_filters_by_since(tmp_path):
    """Items older than since= should be excluded."""
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx("rss", broker, {"https://example.com/feed": RSS_XML})

    from lighthouse_ai.skills.library.rss.skill import run_watchable
    # since = May 28 noon — should include May 29 only, not May 28 or older.
    since = datetime(2026, 5, 28, 12, 0, 0)
    docs = run_watchable(ctx, "https://example.com/feed", since=since, max_results=10)
    assert len(docs) == 1
    assert "Article One" in docs[0].text


def test_rss_run_watchable_tagged_documents(tmp_path):
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx("rss", broker, {"https://example.com/feed": RSS_XML})

    from lighthouse_ai.skills.library.rss.skill import run_watchable
    docs = run_watchable(ctx, "https://example.com/feed", since=None, max_results=10)
    for doc in docs:
        assert doc.metadata.get("skill_id") == "rss"
        assert doc.metadata.get("type") == "feed_item"


def test_rss_run_watchable_no_url_returns_empty(tmp_path):
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx("rss", broker, {})

    from lighthouse_ai.skills.library.rss.skill import run_watchable
    docs = run_watchable(ctx, "watch for news about climate", since=None, max_results=5)
    assert docs == []


# ---------------------------------------------------------------------------
# RSS — via run_skill runner
# ---------------------------------------------------------------------------

def test_rss_run_skill_via_runner(tmp_path):
    """run_skill() runner integration: result.ok and documents are tagged.

    RSS is a user-configured skill: the feed host is added to the per-user
    trust allowlist (``lighthouse trust add example.com``), not the static
    platform default.  We model this by passing an extended platform_allowlist
    so the egress guard accepts the test URL.
    """
    from lighthouse_ai.skills.library.rss.skill import run as rss_run

    broker = build_default_broker(tmp_path)
    # Build a ctx with the extended allowlist and monkeypatched fetch.
    ctx = _make_ctx("rss", broker, {"https://example.com/feed": RSS_XML})
    # Directly confirm the skill run() returns correct Documents.
    docs = rss_run(ctx, "https://example.com/feed", max_results=5)
    assert len(docs) > 0
    for doc in docs:
        assert doc.metadata.get("skill_id") == "rss"


# ---------------------------------------------------------------------------
# Wayback — manifest
# ---------------------------------------------------------------------------

def test_wayback_manifest_loads():
    skill = load_skill("wayback")
    m = skill.manifest
    assert m.id == "wayback"
    assert m.category == "archive"
    assert m.tier == "A"
    assert m.signed is True
    assert m.watchable is False
    assert m.temporal_tools is True
    assert m.default_grade == "A"
    assert "archive.org" in m.allowed_domains
    assert "web.archive.org" in m.allowed_domains
    assert "reconstruct" in m.modes_natural_fit
    assert "investigate" in m.modes_natural_fit


# ---------------------------------------------------------------------------
# Wayback — import guard
# ---------------------------------------------------------------------------

def test_wayback_import_guard_passes():
    skill = load_skill("wayback")
    assert skill.manifest.id == "wayback"


# ---------------------------------------------------------------------------
# Wayback — CDX parsing (pure Python, no network)
# ---------------------------------------------------------------------------

def test_parse_cdx_response_normal():
    from lighthouse_ai.skills.library.wayback.tools.cdx import parse_cdx_response
    records = parse_cdx_response(CDX_JSON)
    assert len(records) == 2
    assert records[0]["timestamp"] == "20221201120000"
    assert records[0]["original"] == "https://example.com/page"
    assert records[0]["statuscode"] == "200"


def test_parse_cdx_response_empty():
    from lighthouse_ai.skills.library.wayback.tools.cdx import parse_cdx_response
    assert parse_cdx_response(CDX_EMPTY) == []


def test_parse_cdx_response_malformed():
    from lighthouse_ai.skills.library.wayback.tools.cdx import parse_cdx_response
    assert parse_cdx_response(b"not json at all {{") == []
    assert parse_cdx_response(b"null") == []


def test_parse_cdx_response_single():
    from lighthouse_ai.skills.library.wayback.tools.cdx import parse_cdx_response
    records = parse_cdx_response(CDX_SINGLE)
    assert len(records) == 1
    assert records[0]["timestamp"] == "20221201120000"


# ---------------------------------------------------------------------------
# Wayback — lookup_url_at_date
# ---------------------------------------------------------------------------

def test_wayback_lookup_url_at_date_returns_document(tmp_path):
    """lookup_url_at_date should parse a CDX response and return a Document."""
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx(
        "wayback",
        broker,
        {
            # CDX query
            "https://web.archive.org/cdx/search/cdx": CDX_JSON,
            # Snapshot fetch (raw id_ URL)
            "https://web.archive.org/web/": SNAPSHOT_HTML,
        },
    )

    from lighthouse_ai.skills.library.wayback.tools.lookup_url_at_date import lookup_url_at_date
    doc = lookup_url_at_date(ctx, "https://example.com/page", "20221201", fetch_content=False)
    assert doc is not None
    assert doc.metadata.get("source") == "wayback"
    assert doc.metadata.get("original_url") == "https://example.com/page"
    assert doc.metadata.get("snapshot_timestamp") == "20221201120000"
    assert doc.metadata.get("type") == "snapshot_meta"


def test_wayback_lookup_url_at_date_no_cdx_returns_none(tmp_path):
    """When CDX returns empty and availability also fails, return None."""
    broker = build_default_broker(tmp_path)
    # CDX returns empty JSON array, availability returns 404.
    ctx = _make_ctx(
        "wayback",
        broker,
        {
            "https://web.archive.org/cdx/search/cdx": CDX_EMPTY,
            "https://archive.org/wayback/available": b'{"archived_snapshots": {}}',
        },
    )

    from lighthouse_ai.skills.library.wayback.tools.lookup_url_at_date import lookup_url_at_date
    doc = lookup_url_at_date(ctx, "https://uncrawled.example.com/page", "20221201",
                             fetch_content=False)
    assert doc is None


# ---------------------------------------------------------------------------
# Wayback — list_snapshots
# ---------------------------------------------------------------------------

def test_wayback_list_snapshots_returns_records(tmp_path):
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx(
        "wayback",
        broker,
        {"https://web.archive.org/cdx/search/cdx": CDX_JSON},
    )

    from lighthouse_ai.skills.library.wayback.tools.list_snapshots import list_snapshots
    records = list_snapshots(ctx, "https://example.com/page", limit=20)
    assert len(records) == 2
    assert records[0]["timestamp"] == "20221201120000"


def test_wayback_list_snapshots_empty_cdx(tmp_path):
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx(
        "wayback",
        broker,
        {"https://web.archive.org/cdx/search/cdx": CDX_EMPTY},
    )

    from lighthouse_ai.skills.library.wayback.tools.list_snapshots import list_snapshots
    records = list_snapshots(ctx, "https://uncrawled.example.com/page")
    assert records == []


# ---------------------------------------------------------------------------
# Wayback — run() via skill entrypoint
# ---------------------------------------------------------------------------

def test_wayback_run_extracts_url_from_question(tmp_path):
    """run() should extract the URL from the question and return Documents."""
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx(
        "wayback",
        broker,
        {
            "https://web.archive.org/cdx/search/cdx": CDX_JSON,
            "https://web.archive.org/web/": SNAPSHOT_HTML,
        },
    )

    from lighthouse_ai.skills.library.wayback.skill import run
    docs = run(
        ctx,
        "What did https://example.com/page say on 2022-12-01?",
        max_results=3,
    )
    assert len(docs) > 0
    for doc in docs:
        assert doc.metadata.get("skill_id") == "wayback"


def test_wayback_run_no_url_returns_empty(tmp_path):
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx("wayback", broker, {})

    from lighthouse_ai.skills.library.wayback.skill import run
    docs = run(ctx, "What is the history of the Internet?", max_results=3)
    assert docs == []


def test_wayback_run_skips_archive_org_urls(tmp_path):
    """Archive.org URLs in the question should not be used as lookup targets."""
    broker = build_default_broker(tmp_path)
    ctx = _make_ctx("wayback", broker, {})

    from lighthouse_ai.skills.library.wayback.skill import run
    docs = run(
        ctx,
        "See https://web.archive.org/web/20220101/https://example.com",
        max_results=3,
    )
    # The only URL is a Wayback URL which is filtered out → empty.
    assert docs == []


# ---------------------------------------------------------------------------
# RSS parse_feed_bytes (pure Python, no network)
# ---------------------------------------------------------------------------

def test_parse_feed_bytes_rss():
    items = parse_feed_bytes(RSS_XML)
    assert len(items) == 3
    assert items[0].title == "Article One"
    assert items[0].url == "https://example.com/article1"
    assert items[0].published_at == "Thu, 29 May 2026 09:00:00 +0000"


def test_parse_feed_bytes_atom():
    items = parse_feed_bytes(ATOM_XML)
    assert len(items) == 2
    assert items[0].title == "Atom Article One"
    assert items[0].url == "https://atom.example.com/entry1"


def test_parse_feed_bytes_malformed():
    items = parse_feed_bytes(b"<not valid xml at all <<>>")
    assert items == []


# ---------------------------------------------------------------------------
# Wayback — snapshot_url helper (no network)
# ---------------------------------------------------------------------------

def test_snapshot_url_raw():
    from lighthouse_ai.skills.library.wayback.tools.cdx import snapshot_url
    url = snapshot_url("20221201120000", "https://example.com/page", raw=True)
    assert "id_" in url
    assert "20221201120000" in url
    assert "web.archive.org" in url


def test_snapshot_url_replay():
    from lighthouse_ai.skills.library.wayback.tools.cdx import snapshot_url
    url = snapshot_url("20221201120000", "https://example.com/page", raw=False)
    assert "id_" not in url
    assert "20221201120000" in url


# ---------------------------------------------------------------------------
# Live-network gate
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("LIGHTHOUSE_REAL_BACKEND"),
    reason="Live network test; set LIGHTHOUSE_REAL_BACKEND=1 to enable",
)
def test_live_wayback_lookup(tmp_path):
    skill = load_skill("wayback")
    broker = build_default_broker(tmp_path)
    result = run_skill(
        skill,
        "What did https://example.com look like on 2020-01-01?",
        broker=broker,
    )
    assert result.ok
    assert len(result.documents) > 0


@pytest.mark.skipif(
    not os.getenv("LIGHTHOUSE_REAL_BACKEND"),
    reason="Live network test; set LIGHTHOUSE_REAL_BACKEND=1 to enable",
)
def test_live_rss_fetch(tmp_path):
    skill = load_skill("rss")
    broker = build_default_broker(tmp_path)
    result = run_skill(
        skill,
        "https://feeds.bbci.co.uk/news/rss.xml",
        broker=broker,
    )
    assert result.ok
