"""Offline tests for the arXiv research skill.

All network calls are monkeypatched — no real HTTP traffic.
Live / integration tests are gated by the LIGHTHOUSE_REAL_BACKEND env var.

Test plan
---------
- load_skill("arxiv") succeeds (manifest parses, import guard passes, entrypoints callable).
- run_skill returns Documents tagged with skill_id="arxiv" and grade="A".
- Exception from search_arxiv is swallowed; run returns an empty list.
- run_watchable filters out papers whose published_date <= since.
- run_watchable with since=None returns all canned documents.
- Documents from run_watchable carry skill provenance tags.
- Live smoke test (LIGHTHOUSE_REAL_BACKEND=1): real network round-trip returns at least one Document.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.skills import load_skill, run_skill, run_watchable

# ---------------------------------------------------------------------------
# Canned fixture data
# ---------------------------------------------------------------------------

_CANNED_DOCS = [
    Document(
        id="http://arxiv.org/abs/2310.00001v1",
        text="Attention Is All You Need. We propose the Transformer architecture.",
        metadata={
            "source": "arxiv",
            "url": "http://arxiv.org/abs/2310.00001v1",
            "grade": "A",
            "published_date": "2023-10-01T10:00:00Z",
            "title": "Attention Is All You Need",
        },
    ),
    Document(
        id="http://arxiv.org/abs/2310.00002v1",
        text="Scaling Laws for Language Models. We study neural scaling.",
        metadata={
            "source": "arxiv",
            "url": "http://arxiv.org/abs/2310.00002v1",
            "grade": "A",
            "published_date": "2023-10-05T08:00:00Z",
            "title": "Scaling Laws for Language Models",
        },
    ),
    Document(
        id="http://arxiv.org/abs/2309.99999v1",
        text="Old paper from before the since cutoff.",
        metadata={
            "source": "arxiv",
            "url": "http://arxiv.org/abs/2309.99999v1",
            "grade": "A",
            "published_date": "2023-09-15T00:00:00Z",
            "title": "Old Paper",
        },
    ),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def arxiv_skill():
    return load_skill("arxiv")


# ---------------------------------------------------------------------------
# Load / manifest
# ---------------------------------------------------------------------------


def test_load_skill_arxiv_succeeds(arxiv_skill):
    """The skill loads cleanly: manifest parses, import guard passes."""
    assert arxiv_skill.manifest.id == "arxiv"
    assert callable(arxiv_skill.entrypoint)
    assert arxiv_skill.watchable_entrypoint is not None  # manifest.watchable=true


def test_manifest_fields(arxiv_skill):
    m = arxiv_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.authority == "preprint"
    assert m.output_shape == "enumerable"
    assert m.signed is True
    assert "investigate" in m.modes_natural_fit
    assert "survey" in m.modes_natural_fit
    assert "decide" in m.modes_weak_fit
    assert "search_recent" in m.watchable_tools
    assert "arxiv.org" in m.allowed_domains


# ---------------------------------------------------------------------------
# run_skill — offline, monkeypatched
# ---------------------------------------------------------------------------


def test_run_skill_returns_tagged_documents(monkeypatch, arxiv_skill, broker):
    """run_skill returns Documents tagged with skill_id and grade."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.arxiv.search_arxiv",
        lambda *a, **kw: _CANNED_DOCS[:2],
    )
    result = run_skill(arxiv_skill, "attention mechanisms", broker=broker)

    assert result.ok
    assert len(result.documents) == 2
    for doc in result.documents:
        assert doc.metadata["skill_id"] == "arxiv"
        assert doc.metadata["grade"] == "A"
        assert doc.metadata["fetch_backend"] == "tier-a"


def test_run_skill_no_community_tag_for_signed_skill(monkeypatch, arxiv_skill, broker):
    """Signed skill must not carry the community downgrade tag."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.arxiv.search_arxiv",
        lambda *a, **kw: _CANNED_DOCS[:1],
    )
    result = run_skill(arxiv_skill, "test", broker=broker)

    assert result.ok
    assert "community" not in result.documents[0].metadata


def test_run_skill_swallows_search_exception(monkeypatch, arxiv_skill, broker):
    """A failing search_arxiv call must not propagate; skill returns []."""

    def _raise(*a, **kw):
        raise RuntimeError("network error")

    monkeypatch.setattr("lighthouse_ai.sources.arxiv.search_arxiv", _raise)
    result = run_skill(arxiv_skill, "transformer", broker=broker)

    # run returns [] on exception; runner sees thin=True
    assert not result.ok or result.documents == []


def test_run_skill_empty_result_is_thin(monkeypatch, arxiv_skill, broker):
    """An empty result from search_arxiv yields a thin run (no documents)."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.arxiv.search_arxiv",
        lambda *a, **kw: [],
    )
    result = run_skill(arxiv_skill, "obscure query xyz", broker=broker)
    assert result.documents == []
    assert result.thin


# ---------------------------------------------------------------------------
# run_watchable — offline, monkeypatched
# ---------------------------------------------------------------------------


def test_run_watchable_since_none_returns_all(monkeypatch, arxiv_skill, broker):
    """With since=None all canned documents are returned."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.arxiv.search_arxiv",
        lambda *a, **kw: list(_CANNED_DOCS),
    )
    result = run_watchable(arxiv_skill, "transformers", since=None, broker=broker)

    assert result.ok
    assert len(result.documents) == 3


def test_run_watchable_filters_by_since(monkeypatch, arxiv_skill, broker):
    """Documents published on or before `since` are excluded."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.arxiv.search_arxiv",
        lambda *a, **kw: list(_CANNED_DOCS),
    )
    # Cutoff: only docs published after 2023-10-01 should survive
    since = datetime(2023, 10, 1, 10, 0, 0)  # exact time of first canned doc

    result = run_watchable(arxiv_skill, "transformers", since=since, broker=broker)

    assert result.ok
    ids = {doc.id for doc in result.documents}
    # published_date == since → filtered out (<=)
    assert "http://arxiv.org/abs/2310.00001v1" not in ids
    # published_date > since → kept
    assert "http://arxiv.org/abs/2310.00002v1" in ids
    # old paper → filtered out
    assert "http://arxiv.org/abs/2309.99999v1" not in ids


def test_run_watchable_documents_tagged(monkeypatch, arxiv_skill, broker):
    """Watchable documents carry full skill provenance."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.arxiv.search_arxiv",
        lambda *a, **kw: _CANNED_DOCS[:1],
    )
    result = run_watchable(arxiv_skill, "attention", since=None, broker=broker)

    assert result.ok
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "arxiv"
    assert doc.metadata["grade"] == "A"


def test_run_watchable_swallows_exception(monkeypatch, arxiv_skill, broker):
    """A failing search_arxiv in run_watchable must not propagate."""

    def _raise(*a, **kw):
        raise ConnectionError("timeout")

    monkeypatch.setattr("lighthouse_ai.sources.arxiv.search_arxiv", _raise)
    result = run_watchable(arxiv_skill, "LLM alignment", since=None, broker=broker)
    assert result.documents == []


# ---------------------------------------------------------------------------
# Live / integration tests (opt-in)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="set LIGHTHOUSE_REAL_BACKEND=1 to run live tests",
)
def test_live_run_returns_documents(tmp_path):
    """Real network: search arXiv and verify at least one Document is returned."""
    skill = load_skill("arxiv")
    broker = build_default_broker(tmp_path)
    result = run_skill(skill, "attention mechanism transformers", broker=broker)

    assert result.ok
    assert len(result.documents) >= 1
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "arxiv"
    assert doc.metadata["grade"] == "A"
    assert doc.text  # non-empty


@pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="set LIGHTHOUSE_REAL_BACKEND=1 to run live tests",
)
def test_live_watchable_returns_documents(tmp_path):
    """Real network: run_watchable with no since filter returns at least one paper."""
    skill = load_skill("arxiv")
    broker = build_default_broker(tmp_path)
    result = run_watchable(skill, "cat:cs.LG diffusion models", since=None, broker=broker)

    assert result.ok
    assert len(result.documents) >= 1
