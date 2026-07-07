"""Tests for the general_web skill.

All tests are offline-deterministic: the SearXNG search function is
monkeypatched at ``lighthouse_ai.sources.searxng.search`` so no network
requests happen.  Live integration tests are gated by LIGHTHOUSE_REAL_BACKEND=1.

Fixture style mirrors tests/test_skills_framework.py.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.skills import load_skill, run_skill, run_watchable
from lighthouse_ai.skills.capabilities import build_context
from lighthouse_ai.sources.searxng import SearXNGUnavailable, SearxResult

# ---------------------------------------------------------------------------
# Fake SearXNG results
# ---------------------------------------------------------------------------


def _fake_results(n: int = 3, *, category: str = "general") -> list[SearxResult]:
    return [
        SearxResult(
            url=f"https://example.com/article-{i}",
            title=f"Article {i} about the topic",
            content=f"Snippet text for article {i}, category={category}.",
            engine="mock_engine",
            score=float(10 - i),
        )
        for i in range(1, n + 1)
    ]


def _fake_search(
    query: str,
    *,
    max_results: int = 10,
    scholarly: bool = False,
    categories: str = "general",
    url: str | None = None,
    timeout: float = 10.0,
) -> list[SearxResult]:
    """Drop-in replacement for lighthouse_ai.sources.searxng.search."""
    return _fake_results(min(max_results, 3), category=categories)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SKILL_ID = "general_web"


def _load(tmp_path: Path):
    """Load the in-tree general_web skill."""
    # No library_dir override needed — LIBRARY_DIR points at the real library.
    return load_skill(SKILL_ID)


def _broker(tmp_path: Path):
    return build_default_broker(tmp_path)


# ---------------------------------------------------------------------------
# Import guard / manifest
# ---------------------------------------------------------------------------


def test_skill_loads_without_import_guard_error():
    """The skill passes the static import guard (no forbidden imports)."""
    skill = load_skill(SKILL_ID)
    assert skill.manifest.id == SKILL_ID


def test_manifest_fields():
    skill = load_skill(SKILL_ID)
    m = skill.manifest
    assert m.category == "web"
    assert m.tier == "A"
    assert m.default_grade == "C"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert m.watchable is True
    assert "search_news" in m.watchable_tools
    assert "search_web" in m.watchable_tools


def test_manifest_modes_natural_fit_covers_all_modes():
    skill = load_skill(SKILL_ID)
    expected = {"investigate", "survey", "reconstruct", "decide", "adjudicate", "watch", "ask"}
    assert expected.issubset(set(skill.manifest.modes_natural_fit))


def test_watchable_entrypoint_present():
    skill = load_skill(SKILL_ID)
    assert skill.watchable_entrypoint is not None
    assert callable(skill.watchable_entrypoint)


# ---------------------------------------------------------------------------
# run() — happy path with snippet fallback
# ---------------------------------------------------------------------------


def test_run_returns_snippet_fallback_documents(tmp_path):
    """When fetch_and_document fails (egress-blocked), run() returns snippet documents."""
    skill = load_skill(SKILL_ID)
    broker = _broker(tmp_path)

    with patch("lighthouse_ai.sources.searxng.search", side_effect=_fake_search):
        run = run_skill(skill, "what is the capital of France", broker=broker)

    assert run.ok, f"run failed: {run.error}"
    assert len(run.documents) > 0

    # All documents are tagged with skill_id
    for doc in run.documents:
        assert doc.metadata.get("skill_id") == SKILL_ID

    # Snippet fallback: example.com is not on the platform allowlist,
    # so fetch_and_document raises EgressBlocked → make_document path.
    assert any(doc.metadata.get("fallback") == "snippet" for doc in run.documents), (
        "Expected at least one snippet-fallback document when hosts are egress-blocked"
    )


def test_run_documents_have_text(tmp_path):
    """Each returned document has non-empty text."""
    skill = load_skill(SKILL_ID)
    broker = _broker(tmp_path)

    with patch("lighthouse_ai.sources.searxng.search", side_effect=_fake_search):
        run = run_skill(skill, "test question", broker=broker)

    for doc in run.documents:
        assert doc.text and len(doc.text.strip()) > 0, f"Empty text in doc {doc.id}"


def test_run_respects_max_results(tmp_path):
    """run() returns no more than max_results documents."""
    skill = load_skill(SKILL_ID)
    broker = _broker(tmp_path)
    ctx = build_context(skill.manifest, broker=broker)

    with patch("lighthouse_ai.sources.searxng.search", side_effect=_fake_search):
        docs = skill.entrypoint(ctx, "anything", max_results=2)

    assert len(docs) <= 2


# ---------------------------------------------------------------------------
# run() — SearXNGUnavailable degrades gracefully
# ---------------------------------------------------------------------------


def test_run_returns_empty_when_searxng_unavailable(tmp_path):
    """SearXNGUnavailable is caught; run() returns [] rather than raising."""
    skill = load_skill(SKILL_ID)
    broker = _broker(tmp_path)

    def _unavailable(*args, **kwargs):
        raise SearXNGUnavailable("not reachable")

    with patch("lighthouse_ai.sources.searxng.search", side_effect=_unavailable):
        run = run_skill(skill, "anything", broker=broker)

    # run.ok is False only if the skill raises — returning [] is ok.
    # An empty corpus is still ok; the dispatcher marks it as thin.
    assert run.documents == []


# ---------------------------------------------------------------------------
# run_watchable() — news category, since= support
# ---------------------------------------------------------------------------


def test_run_watchable_returns_documents(tmp_path):
    skill = load_skill(SKILL_ID)
    broker = _broker(tmp_path)

    with patch("lighthouse_ai.sources.searxng.search", side_effect=_fake_search):
        run = run_watchable(skill, "AI news", since=None, broker=broker)

    assert run.ok
    assert len(run.documents) > 0
    for doc in run.documents:
        assert doc.metadata.get("skill_id") == SKILL_ID


def test_run_watchable_passes_since_hint(tmp_path):
    """When since= is provided, the query sent to SearXNG includes a date hint."""
    skill = load_skill(SKILL_ID)
    broker = _broker(tmp_path)
    since = datetime(2024, 3, 14, 9, 0, tzinfo=UTC)
    captured_queries: list[str] = []

    def _capture(query: str, **kwargs):
        captured_queries.append(query)
        return _fake_results(2, category=kwargs.get("categories", "news"))

    with patch("lighthouse_ai.sources.searxng.search", side_effect=_capture):
        run = run_watchable(skill, "AI news", since=since, broker=broker)

    assert run.ok
    assert captured_queries, "SearXNG search was never called"
    assert "2024-03-14" in captured_queries[0], (
        f"Expected date hint in query, got: {captured_queries[0]!r}"
    )


def test_run_watchable_documents_tagged_recency(tmp_path):
    """Watch Documents get role='recency' in metadata."""
    skill = load_skill(SKILL_ID)
    broker = _broker(tmp_path)

    with patch("lighthouse_ai.sources.searxng.search", side_effect=_fake_search):
        run = run_watchable(skill, "topic", since=None, broker=broker)

    assert run.ok
    # All docs should have role=recency (snippet fallback path sets it explicitly)
    for doc in run.documents:
        assert doc.metadata.get("role") == "recency", (
            f"Expected role='recency', got {doc.metadata.get('role')!r}"
        )


def test_run_watchable_empty_when_unavailable(tmp_path):
    skill = load_skill(SKILL_ID)
    broker = _broker(tmp_path)

    def _unavailable(*args, **kwargs):
        raise SearXNGUnavailable("offline")

    with patch("lighthouse_ai.sources.searxng.search", side_effect=_unavailable):
        run = run_watchable(skill, "topic", since=None, broker=broker)

    assert run.documents == []


# ---------------------------------------------------------------------------
# Tool imports (verify tools/ package is importable)
# ---------------------------------------------------------------------------


def test_tools_importable():
    """All nine tools are importable without triggering the import guard."""
    from lighthouse_ai.skills.library.general_web.tools import (  # noqa: F401
        expand_query,
        fetch_url,
        fetch_url_js,
        follow_chain,
        search_images,
        search_news,
        search_scholar,
        search_videos,
        search_web,
    )


# ---------------------------------------------------------------------------
# expand_query tool
# ---------------------------------------------------------------------------


def test_expand_query_returns_original_first(tmp_path):
    from lighthouse_ai.skills.library.general_web.tools.expand_query import expand_query

    skill = load_skill(SKILL_ID)
    broker = _broker(tmp_path)
    ctx = build_context(skill.manifest, broker=broker)

    with patch("lighthouse_ai.sources.searxng.search", side_effect=_fake_search):
        variants = expand_query(ctx, "climate change", max_variants=5)

    assert len(variants) >= 1
    assert variants[0] == "climate change"


def test_expand_query_graceful_on_unavailable(tmp_path):
    from lighthouse_ai.skills.library.general_web.tools.expand_query import expand_query

    skill = load_skill(SKILL_ID)
    broker = _broker(tmp_path)
    ctx = build_context(skill.manifest, broker=broker)

    def _unavailable(*args, **kwargs):
        raise SearXNGUnavailable("offline")

    with patch("lighthouse_ai.sources.searxng.search", side_effect=_unavailable):
        variants = expand_query(ctx, "my query")

    assert variants == ["my query"]


# ---------------------------------------------------------------------------
# fetch_url tool
# ---------------------------------------------------------------------------


def test_fetch_url_returns_none_on_blocked_host(tmp_path):
    """fetch_url returns None when host is egress-blocked (not on platform allowlist)."""
    from lighthouse_ai.skills.library.general_web.tools.fetch_url import fetch_url

    skill = load_skill(SKILL_ID)
    broker = _broker(tmp_path)
    ctx = build_context(skill.manifest, broker=broker)

    # example.com is not on the platform allowlist → EgressBlocked → None
    result = fetch_url(ctx, "https://example.com/page")
    assert result is None


# ---------------------------------------------------------------------------
# Live backend gate
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="Live test; set LIGHTHOUSE_REAL_BACKEND=1 to run",
)
def test_run_live(tmp_path):
    """Integration test against a real SearXNG instance."""
    skill = load_skill(SKILL_ID)
    broker = _broker(tmp_path)
    run = run_skill(skill, "Python programming language", broker=broker)
    # Just check the plumbing works; result count depends on live SearXNG.
    assert isinstance(run.documents, list)
