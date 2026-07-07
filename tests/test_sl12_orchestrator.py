"""Offline tests for SL12 — the News Orchestrator meta-skill.

Test plan:
- Orchestrator loads (manifest parses, import guard passes, entrypoints callable).
- search_news aggregates Documents across outlets with bias tags attached.
- compare_coverage returns per-outlet grouping + bias_overlay dict.
- get_bias_overlay returns the expected AllSides rating map for all 6 outlets.
- One outlet EgressBlocked is skipped without failing the rest.
- run_watchable(since=...) filters old items.
- register_custom_outlet adds an ephemeral outlet to subsequent searches.
- discover_skills() includes "news_orchestrator".

No datetime.now() at import time.  No real network calls.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from lighthouse_ai.net import EgressBlocked
from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.skills import discover_skills, load_skill

# ---------------------------------------------------------------------------
# Canned feed bytes — two fresh items + one old item
# ---------------------------------------------------------------------------

_RSS_BYTES = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Canned News Feed</title>
    <item>
      <title>Breaking: Climate Summit Story</title>
      <link>https://example.com/climate-1</link>
      <description>Coverage of the climate summit negotiations.</description>
      <pubDate>Mon, 02 Jan 2027 10:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Analysis: Green Policy Impact</title>
      <link>https://example.com/climate-2</link>
      <description>Deep analysis of green policy changes.</description>
      <pubDate>Mon, 02 Jan 2027 11:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Old Story from Before Cutoff</title>
      <link>https://example.com/old</link>
      <description>This is an old story.</description>
      <pubDate>Sun, 01 Jun 2026 00:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""

# ---------------------------------------------------------------------------
# Shared ctx builder
# ---------------------------------------------------------------------------

SKILL_ID = "news_orchestrator"


def _make_ctx(broker, skill_id: str = SKILL_ID, rss_bytes: bytes = _RSS_BYTES):
    """Build a MagicMock SkillContext with canned fetch + make_document."""
    from lighthouse_ai.skills.capabilities import SkillContext

    class FakeResponse:
        def __init__(self, content: bytes, status_code: int = 200):
            self.content = content
            self.status_code = status_code

    def _fake_fetch(url: str, **kw) -> FakeResponse:
        return FakeResponse(rss_bytes)

    def _make_document(*, doc_id: str, text: str, metadata: dict | None = None) -> Document:
        doc = Document(id=doc_id, text=text, metadata=dict(metadata or {}))
        doc.metadata["skill_id"] = skill_id
        return doc

    ctx = MagicMock(spec=SkillContext)
    ctx.fetch.side_effect = _fake_fetch
    ctx.make_document.side_effect = _make_document
    ctx.skill_id = skill_id
    ctx.skill_version = "0.1.0"
    return ctx


# ---------------------------------------------------------------------------
# 1. Skill loads correctly
# ---------------------------------------------------------------------------


def test_orchestrator_loads():
    """Manifest parses, import guard passes, entrypoints are callable."""
    s = load_skill(SKILL_ID)
    assert s.manifest.id == SKILL_ID
    assert callable(s.entrypoint)
    assert s.watchable_entrypoint is not None, "news_orchestrator must have run_watchable"


def test_manifest_tier_signed_category():
    s = load_skill(SKILL_ID)
    m = s.manifest
    assert m.tier == "A"
    assert m.signed is True
    assert m.category == "news"


def test_manifest_output_shape_enumerable():
    s = load_skill(SKILL_ID)
    assert s.manifest.output_shape == "enumerable"


def test_manifest_watchable_true():
    s = load_skill(SKILL_ID)
    m = s.manifest
    assert m.watchable is True
    assert "search_news" in m.watchable_tools


def test_manifest_audit_tags_bias_overlay():
    """Manifest must carry bias-overlay:allsides audit tag."""
    s = load_skill(SKILL_ID)
    assert "bias-overlay:allsides" in s.manifest.audit_tags


def test_manifest_domains():
    s = load_skill(SKILL_ID)
    m = s.manifest
    for domain in ("journalism", "politics", "finance"):
        assert domain in m.topics or domain in (m.id,), (
            f"expected domain '{domain}' represented in manifest topics or domains"
        )


# ---------------------------------------------------------------------------
# 2. Import guard passes (no forbidden imports in skill.py)
# ---------------------------------------------------------------------------


def test_import_guard_passes():
    """Registry import guard must not raise SkillLoadError for news_orchestrator."""
    from lighthouse_ai.skills.registry import LIBRARY_DIR, _audit_skill_imports

    skill_dir = LIBRARY_DIR / SKILL_ID
    # Should NOT raise
    _audit_skill_imports(skill_dir)


# ---------------------------------------------------------------------------
# 3. discover_skills includes news_orchestrator
# ---------------------------------------------------------------------------


def test_discover_skills_includes_orchestrator():
    manifests = discover_skills()
    assert SKILL_ID in manifests, f"discover_skills() missing '{SKILL_ID}'"


# ---------------------------------------------------------------------------
# 4. search_news aggregates across outlets with bias tags
# ---------------------------------------------------------------------------


def test_search_news_returns_documents(monkeypatch, broker):
    """search_news fans out and returns Documents from multiple outlets."""
    from lighthouse_ai.skills.library.news_orchestrator import skill as _orch
    from lighthouse_ai.sources import news as _news

    _rss_items = _news.parse_feed_bytes(_RSS_BYTES)

    def _canned_feed(url, *, client=None, max_results=20):
        return _rss_items[:max_results]

    monkeypatch.setattr(_news, "fetch_outlet_feed", _canned_feed)

    ctx = _make_ctx(broker)
    docs = _orch.search_news(ctx, "climate", max_results=3)

    assert len(docs) > 0, "search_news returned no documents"
    for doc in docs:
        assert doc.text, "Document has empty text"
        assert "allsides_rating" in doc.metadata, (
            f"Document missing allsides_rating: {doc.metadata}"
        )
        assert "outlet" in doc.metadata or "source" in doc.metadata, (
            f"Document missing outlet/source tag: {doc.metadata}"
        )


def test_search_news_bias_tags_present(monkeypatch, broker):
    """Every returned Document must carry an allsides_rating metadata tag."""
    from lighthouse_ai.skills.library.news_orchestrator import skill as _orch
    from lighthouse_ai.sources import news as _news

    _rss_items = _news.parse_feed_bytes(_RSS_BYTES)

    def _canned_feed(url, *, client=None, max_results=20):
        return _rss_items[:max_results]

    monkeypatch.setattr(_news, "fetch_outlet_feed", _canned_feed)

    ctx = _make_ctx(broker)
    docs = _orch.search_news(ctx, "policy", max_results=2)

    ratings_seen = {doc.metadata.get("allsides_rating") for doc in docs}
    # Should include at least center (Reuters/AP) and lean_left (BBC/NPR/ProPublica/Guardian)
    assert len(ratings_seen) >= 1, "No allsides_rating values found in documents"
    valid_ratings = {"center", "lean_left", "left", "lean_right", "right", "unknown"}
    for rating in ratings_seen:
        assert rating in valid_ratings, f"Unexpected allsides_rating value: {rating!r}"


def test_search_news_multiple_outlets_represented(monkeypatch, broker):
    """Documents should come from multiple different outlets."""
    from lighthouse_ai.skills.library.news_orchestrator import skill as _orch
    from lighthouse_ai.sources import news as _news

    _rss_items = _news.parse_feed_bytes(_RSS_BYTES)

    def _canned_feed(url, *, client=None, max_results=20):
        return _rss_items[:max_results]

    monkeypatch.setattr(_news, "fetch_outlet_feed", _canned_feed)

    ctx = _make_ctx(broker)
    docs = _orch.search_news(ctx, "climate", max_results=2)

    outlets_seen = {doc.metadata.get("outlet") or doc.metadata.get("source") for doc in docs}
    assert len(outlets_seen) >= 2, f"Expected docs from ≥2 outlets, got: {outlets_seen}"


# ---------------------------------------------------------------------------
# 5. compare_coverage returns per-outlet grouping
# ---------------------------------------------------------------------------


def test_compare_coverage_structure(monkeypatch, broker):
    """compare_coverage returns the expected dict shape."""
    from lighthouse_ai.skills.library.news_orchestrator import skill as _orch
    from lighthouse_ai.sources import news as _news

    _rss_items = _news.parse_feed_bytes(_RSS_BYTES)

    def _canned_feed(url, *, client=None, max_results=20):
        return _rss_items[:max_results]

    monkeypatch.setattr(_news, "fetch_outlet_feed", _canned_feed)

    ctx = _make_ctx(broker)
    result = _orch.compare_coverage(ctx, "climate")

    assert "outlets" in result, "compare_coverage missing 'outlets' key"
    assert "bias_overlay" in result, "compare_coverage missing 'bias_overlay' key"

    outlet_ids = [entry["outlet_id"] for entry in result["outlets"]]
    for expected_id in ("reuters", "associated_press", "bbc_news", "npr", "guardian", "propublica"):
        assert expected_id in outlet_ids, (
            f"compare_coverage missing outlet '{expected_id}'; got {outlet_ids}"
        )


def test_compare_coverage_per_outlet_has_documents(monkeypatch, broker):
    """Each outlet entry in compare_coverage has a 'documents' list."""
    from lighthouse_ai.skills.library.news_orchestrator import skill as _orch
    from lighthouse_ai.sources import news as _news

    _rss_items = _news.parse_feed_bytes(_RSS_BYTES)

    def _canned_feed(url, *, client=None, max_results=20):
        return _rss_items[:max_results]

    monkeypatch.setattr(_news, "fetch_outlet_feed", _canned_feed)

    ctx = _make_ctx(broker)
    result = _orch.compare_coverage(ctx, "climate")

    for entry in result["outlets"]:
        assert "documents" in entry, f"Outlet entry missing 'documents': {entry}"
        assert isinstance(entry["documents"], list)
        assert "allsides_rating" in entry


def test_compare_coverage_bias_overlay_completeness(monkeypatch, broker):
    """bias_overlay in compare_coverage result covers all 6 default outlets."""
    from lighthouse_ai.skills.library.news_orchestrator import skill as _orch
    from lighthouse_ai.sources import news as _news

    monkeypatch.setattr(_news, "fetch_outlet_feed", lambda *a, **kw: [])

    ctx = _make_ctx(broker)
    result = _orch.compare_coverage(ctx, "test")

    overlay = result["bias_overlay"]
    for outlet_id in ("reuters", "associated_press", "bbc_news", "npr", "guardian", "propublica"):
        assert outlet_id in overlay, f"bias_overlay missing outlet '{outlet_id}'"


# ---------------------------------------------------------------------------
# 6. get_bias_overlay returns the AllSides map
# ---------------------------------------------------------------------------


def test_get_bias_overlay_returns_all_outlets():
    from lighthouse_ai.skills.library.news_orchestrator.skill import get_bias_overlay

    overlay = get_bias_overlay()
    expected = {
        "reuters": "center",
        "associated_press": "center",
        "bbc_news": "lean_left",
        "npr": "lean_left",
        "guardian": "left",
        "propublica": "lean_left",
    }
    for outlet_id, expected_rating in expected.items():
        assert outlet_id in overlay, f"bias overlay missing '{outlet_id}'"
        assert overlay[outlet_id] == expected_rating, (
            f"Expected {outlet_id}={expected_rating!r}, got {overlay[outlet_id]!r}"
        )


# ---------------------------------------------------------------------------
# 7. One outlet EgressBlocked is skipped without failing the rest
# ---------------------------------------------------------------------------


def test_egress_blocked_one_outlet_skipped(monkeypatch, broker):
    """When one outlet raises EgressBlocked the rest still return docs."""
    from lighthouse_ai.skills.library.news_orchestrator import skill as _orch
    from lighthouse_ai.sources import news as _news

    _rss_items = _news.parse_feed_bytes(_RSS_BYTES)

    blocked_outlet_feed = "https://feeds.reuters.com/reuters/topNews"

    def _selective_feed(url, *, client=None, max_results=20):
        if url == blocked_outlet_feed:
            raise EgressBlocked("Reuters blocked in test")
        return _rss_items[:max_results]

    monkeypatch.setattr(_news, "fetch_outlet_feed", _selective_feed)

    ctx = _make_ctx(broker)
    docs = _orch.search_news(ctx, "climate", max_results=3)

    # Should still get docs from the other 5 outlets
    assert len(docs) > 0, "search_news returned no docs even though 5/6 outlets are accessible"
    # Reuters outlet should not appear (it was blocked)
    reuters_docs = [d for d in docs if d.metadata.get("outlet") == "reuters"]
    assert reuters_docs == [], f"Reuters docs appeared despite EgressBlocked: {reuters_docs}"


def test_all_outlets_egress_blocked_returns_empty(monkeypatch, broker):
    """When all outlets are blocked, search_news returns []."""
    from lighthouse_ai.skills.library.news_orchestrator import skill as _orch
    from lighthouse_ai.sources import news as _news

    def _all_blocked(url, *, client=None, max_results=20):
        raise EgressBlocked("all blocked")

    monkeypatch.setattr(_news, "fetch_outlet_feed", _all_blocked)

    ctx = _make_ctx(broker)
    docs = _orch.search_news(ctx, "test", max_results=3)
    assert docs == [], f"Expected [] when all outlets blocked, got {docs}"


def test_run_degrades_on_egress_blocked(monkeypatch, broker):
    """run() (the entrypoint) also degrades to [] when all outlets blocked."""
    from lighthouse_ai.sources import news as _news

    def _all_blocked(url, *, client=None, max_results=20):
        raise EgressBlocked("all blocked")

    monkeypatch.setattr(_news, "fetch_outlet_feed", _all_blocked)

    s = load_skill(SKILL_ID)
    ctx = _make_ctx(broker)
    ctx.fetch.side_effect = EgressBlocked("blocked")

    docs = s.entrypoint(ctx, "test query", max_results=3)
    assert docs == [], f"run() must return [] on EgressBlocked, got {docs}"


# ---------------------------------------------------------------------------
# 8. run_watchable since-filtering
# ---------------------------------------------------------------------------


def test_run_watchable_filters_old_items(monkeypatch, broker):
    """run_watchable(since=cutoff) excludes items published before the cutoff."""
    from lighthouse_ai.skills.library.news_orchestrator import skill as _orch
    from lighthouse_ai.sources import news as _news

    _rss_items = _news.parse_feed_bytes(_RSS_BYTES)

    def _canned_feed(url, *, client=None, max_results=20):
        return _rss_items[:max_results]

    monkeypatch.setattr(_news, "fetch_outlet_feed", _canned_feed)

    ctx = _make_ctx(broker)
    cutoff = datetime(2026, 12, 1, 0, 0, 0)
    docs = _orch.run_watchable(ctx, "climate", since=cutoff, max_results=5)

    # "Old Story from Before Cutoff" (2026-06-01) must not appear
    old_in_docs = any("old" in doc.text.lower() for doc in docs)
    assert not old_in_docs, "run_watchable(since=cutoff) included items before the cutoff"


def test_run_watchable_since_none_returns_all(monkeypatch, broker):
    """run_watchable(since=None) returns all available items."""
    from lighthouse_ai.skills.library.news_orchestrator import skill as _orch
    from lighthouse_ai.sources import news as _news

    _rss_items = _news.parse_feed_bytes(_RSS_BYTES)

    def _canned_feed(url, *, client=None, max_results=20):
        return _rss_items[:max_results]

    monkeypatch.setattr(_news, "fetch_outlet_feed", _canned_feed)

    ctx = _make_ctx(broker)
    # Use "climate" which matches the canned items ("climate summit", "policy")
    docs = _orch.run_watchable(ctx, "climate", since=None, max_results=5)
    assert len(docs) > 0, "run_watchable(since=None) returned no docs"


# ---------------------------------------------------------------------------
# 9. register_custom_outlet adds an ephemeral outlet
# ---------------------------------------------------------------------------


def test_register_custom_outlet(monkeypatch, broker):
    """register_custom_outlet registers an outlet that appears in searches."""
    from lighthouse_ai.skills.library.news_orchestrator import skill as _orch
    from lighthouse_ai.sources import news as _news

    _rss_items = _news.parse_feed_bytes(_RSS_BYTES)

    def _canned_feed(url, *, client=None, max_results=20):
        return _rss_items[:max_results]

    monkeypatch.setattr(_news, "fetch_outlet_feed", _canned_feed)

    # Register a custom outlet
    result = _orch.register_custom_outlet(
        feed_url="https://custom.example.com/feed.rss",
        outlet_id="custom_test_outlet",
        outlet_name="Custom Test Outlet",
        allsides_rating="center",
    )
    assert result["status"] == "registered"
    assert result["outlet_id"] == "custom_test_outlet"

    # The custom outlet should appear in get_bias_overlay
    overlay = _orch.get_bias_overlay()
    assert "custom_test_outlet" in overlay
    assert overlay["custom_test_outlet"] == "center"

    # Clean up — remove the custom outlet to avoid polluting other tests
    _orch._custom_outlets[:] = [o for o in _orch._custom_outlets if o.id != "custom_test_outlet"]


# ---------------------------------------------------------------------------
# 10. validate_outlet_access runs without raising
# ---------------------------------------------------------------------------


def test_validate_outlet_access_returns_status_list(monkeypatch, broker):
    """validate_outlet_access returns a list of status dicts."""
    from lighthouse_ai.skills.library.news_orchestrator import skill as _orch
    from lighthouse_ai.sources import news as _news

    _rss_items = _news.parse_feed_bytes(_RSS_BYTES)

    def _canned_feed(url, *, client=None, max_results=20):
        return _rss_items[:max_results]

    monkeypatch.setattr(_news, "fetch_outlet_feed", _canned_feed)

    ctx = _make_ctx(broker)
    statuses = _orch.validate_outlet_access(ctx)

    assert isinstance(statuses, list), "validate_outlet_access must return a list"
    assert len(statuses) == 6, (
        f"Expected 6 status entries (one per default outlet), got {len(statuses)}"
    )
    for entry in statuses:
        assert "outlet_id" in entry
        assert "reachable" in entry
        assert entry["reachable"] is True  # canned feed returns items → reachable


# ---------------------------------------------------------------------------
# 11. run() entrypoint via load_skill works end-to-end
# ---------------------------------------------------------------------------


def test_run_entrypoint_returns_documents(monkeypatch, broker):
    """load_skill('news_orchestrator').entrypoint returns Documents."""
    from lighthouse_ai.sources import news as _news

    _rss_items = _news.parse_feed_bytes(_RSS_BYTES)

    def _canned_feed(url, *, client=None, max_results=20):
        return _rss_items[:max_results]

    monkeypatch.setattr(_news, "fetch_outlet_feed", _canned_feed)

    s = load_skill(SKILL_ID)
    ctx = _make_ctx(broker)
    docs = s.entrypoint(ctx, "climate summit", max_results=3)

    assert len(docs) > 0, "run() entrypoint returned no documents"
    for doc in docs:
        assert doc.text
        assert "allsides_rating" in doc.metadata


def test_watchable_entrypoint_callable(monkeypatch, broker):
    """load_skill('news_orchestrator').watchable_entrypoint returns Documents."""
    from lighthouse_ai.sources import news as _news

    _rss_items = _news.parse_feed_bytes(_RSS_BYTES)

    def _canned_feed(url, *, client=None, max_results=20):
        return _rss_items[:max_results]

    monkeypatch.setattr(_news, "fetch_outlet_feed", _canned_feed)

    s = load_skill(SKILL_ID)
    ctx = _make_ctx(broker)
    # Use "climate" which matches the canned items ("Breaking: Climate Summit Story")
    docs = s.watchable_entrypoint(ctx, "climate", since=None, max_results=3)

    assert len(docs) > 0, "run_watchable entrypoint returned no documents"
