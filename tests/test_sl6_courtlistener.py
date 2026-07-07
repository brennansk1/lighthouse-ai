"""Offline tests for SL6 — the CourtListener skill + shared audio-transcript infra.

Test plan
---------
transcript.py
  - ``transcribe_or_fetch_captions`` returns ``None`` gracefully when no provider
    is registered and the cache is empty.
  - ``cache_transcript`` / ``transcribe_or_fetch_captions`` round-trip works.
  - A registered provider is called and its return value is cached.
  - ``clear_providers`` + ``clear_cache`` reset state between tests.

CourtListener skill — load
  - ``load_skill("courtlistener")`` succeeds (manifest parses, import guard passes,
    entrypoints callable).
  - Manifest fields match the spec: tier A, signed, watchable=true, legal category,
    correct allowed_domains, modes_natural_fit, output_shape, temporal_tools.

CourtListener skill — run (offline, monkeypatched)
  - ``run_skill`` returns tagged Documents with skill_id="courtlistener".
  - Documents carry grade="B" and fetch_backend="tier-a".
  - Exception from ``search_courtlistener`` is swallowed; returns empty list.
  - Empty result yields a thin run (no documents).

CourtListener skill — run_watchable (offline, monkeypatched)
  - ``since=None`` returns all canned documents.
  - Documents with ``published_date`` on or before ``since`` are filtered out.
  - Documents with ``published_date`` after ``since`` are retained.
  - Watchable documents carry the ``watchable_tool="track_docket"`` metadata tag.
  - Exception from ``search_courtlistener`` in watchable is swallowed.

All tests are fully offline — no real HTTP traffic.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.skills import load_skill, run_skill, run_watchable
from lighthouse_ai.sources import transcript as _transcript

# ---------------------------------------------------------------------------
# Canned fixture data
# ---------------------------------------------------------------------------

_CANNED_DOCS = [
    Document(
        id="cl:1234567",
        text="Roe v. Wade. A landmark decision on privacy and reproductive rights.",
        metadata={
            "source": "courtlistener",
            "url": "https://www.courtlistener.com/opinion/1234567/roe-v-wade/",
            "grade": "B",
            "published_date": "1973-01-22",
            "title": "Roe v. Wade",
            "court": "scotus",
        },
    ),
    Document(
        id="cl:7654321",
        text="Dobbs v. Jackson Women's Health Organization. Overruling Roe v. Wade.",
        metadata={
            "source": "courtlistener",
            "url": "https://www.courtlistener.com/opinion/7654321/dobbs-v-jackson/",
            "grade": "B",
            "published_date": "2022-06-24",
            "title": "Dobbs v. Jackson Women's Health Organization",
            "court": "scotus",
        },
    ),
    Document(
        id="cl:9999999",
        text="Old pre-cutoff opinion.",
        metadata={
            "source": "courtlistener",
            "url": "https://www.courtlistener.com/opinion/9999999/old-case/",
            "grade": "B",
            "published_date": "2020-01-15",
            "title": "Old Pre-Cutoff Opinion",
            "court": "ca9",
        },
    ),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_transcript_state():
    """Reset transcript module state before each test to avoid cross-test contamination."""
    _transcript.clear_cache()
    _transcript.clear_providers()
    yield
    _transcript.clear_cache()
    _transcript.clear_providers()


@pytest.fixture()
def cl_skill():
    return load_skill("courtlistener")


# ---------------------------------------------------------------------------
# transcript.py — interface tests
# ---------------------------------------------------------------------------


class TestTranscriptModule:
    """Tests for the shared audio-transcript helper (sources/transcript.py)."""

    def test_returns_none_when_no_provider_and_no_cache(self):
        """transcribe_or_fetch_captions returns None gracefully with no setup."""
        result = _transcript.transcribe_or_fetch_captions("https://www.courtlistener.com/audio/42/")
        assert result is None

    def test_cache_roundtrip(self):
        """cache_transcript followed by transcribe_or_fetch_captions returns cached text."""
        ref = "cl_audio_test_ref_001"
        text = "The court will come to order."
        _transcript.cache_transcript(ref, text)
        result = _transcript.transcribe_or_fetch_captions(ref)
        assert result == text

    def test_returns_none_for_unknown_ref_after_cache_set(self):
        """An unrelated ref is not affected by a cache entry for a different ref."""
        _transcript.cache_transcript("ref_A", "some transcript")
        result = _transcript.transcribe_or_fetch_captions("ref_B")
        assert result is None

    def test_registered_provider_is_called(self):
        """A registered provider is invoked and its value is returned."""
        calls = []

        def my_provider(audio_ref: str) -> str | None:
            calls.append(audio_ref)
            if audio_ref.startswith("test://"):
                return "Provider transcript text."
            return None

        _transcript.register_provider(my_provider)
        result = _transcript.transcribe_or_fetch_captions("test://audio/123")
        assert result == "Provider transcript text."
        assert "test://audio/123" in calls

    def test_provider_result_is_cached(self):
        """After a provider returns a result, subsequent calls use the cache."""
        call_count = [0]

        def counting_provider(audio_ref: str) -> str | None:
            call_count[0] += 1
            return "cached result"

        _transcript.register_provider(counting_provider)
        result1 = _transcript.transcribe_or_fetch_captions("some_ref")
        result2 = _transcript.transcribe_or_fetch_captions("some_ref")
        assert result1 == result2 == "cached result"
        # Provider should only be called once; second call hits cache.
        assert call_count[0] == 1

    def test_provider_returning_none_does_not_cache(self):
        """A provider returning None does not populate the cache."""
        _transcript.register_provider(lambda ref: None)
        result = _transcript.transcribe_or_fetch_captions("null_ref")
        assert result is None
        # Cache should still be empty for this ref.
        assert "null_ref" not in _transcript._CACHE

    def test_register_provider_is_idempotent(self):
        """Registering the same provider twice does not add it twice."""
        fn = lambda ref: None  # noqa: E731
        _transcript.register_provider(fn)
        _transcript.register_provider(fn)
        assert _transcript._PROVIDERS.count(fn) == 1

    def test_clear_cache_removes_all_entries(self):
        """clear_cache empties the in-process cache."""
        _transcript.cache_transcript("a", "text a")
        _transcript.cache_transcript("b", "text b")
        _transcript.clear_cache()
        assert _transcript._CACHE == {}

    def test_clear_providers_removes_all_providers(self):
        """clear_providers empties the provider list."""
        _transcript.register_provider(lambda ref: "x")
        _transcript.clear_providers()
        assert _transcript._PROVIDERS == []

    def test_courtlistener_audio_ref_returns_none_by_default(self):
        """A realistic CourtListener audio URL returns None with no ASR backend."""
        cl_audio_url = "https://www.courtlistener.com/audio/99887/united-states-v-smith/"
        result = _transcript.transcribe_or_fetch_captions(cl_audio_url)
        assert result is None


# ---------------------------------------------------------------------------
# CourtListener skill — load / manifest
# ---------------------------------------------------------------------------


class TestCourtListenerSkillLoad:
    """Tests that the skill loads cleanly and its manifest matches the spec."""

    def test_load_skill_succeeds(self, cl_skill):
        """load_skill('courtlistener') succeeds: manifest parses, import guard passes."""
        assert cl_skill.manifest.id == "courtlistener"
        assert callable(cl_skill.entrypoint)

    def test_watchable_entrypoint_present(self, cl_skill):
        """Manifest declares watchable=true; run_watchable must be callable."""
        assert cl_skill.watchable_entrypoint is not None
        assert callable(cl_skill.watchable_entrypoint)

    def test_manifest_tier(self, cl_skill):
        assert cl_skill.manifest.tier == "A"

    def test_manifest_signed(self, cl_skill):
        assert cl_skill.manifest.signed is True

    def test_manifest_not_community(self, cl_skill):
        assert cl_skill.manifest.is_community is False

    def test_manifest_category(self, cl_skill):
        assert cl_skill.manifest.category == "legal"

    def test_manifest_default_grade(self, cl_skill):
        assert cl_skill.manifest.default_grade == "B"

    def test_manifest_output_shape(self, cl_skill):
        assert cl_skill.manifest.output_shape == "enumerable"

    def test_manifest_temporal_tools(self, cl_skill):
        assert cl_skill.manifest.temporal_tools is True

    def test_manifest_watchable(self, cl_skill):
        assert cl_skill.manifest.watchable is True

    def test_manifest_watchable_tools(self, cl_skill):
        assert "track_docket" in cl_skill.manifest.watchable_tools

    def test_manifest_modes_natural_fit(self, cl_skill):
        fit = cl_skill.manifest.modes_natural_fit
        assert "investigate" in fit
        assert "reconstruct" in fit
        assert "survey" in fit

    def test_manifest_allowed_domains(self, cl_skill):
        domains = cl_skill.manifest.allowed_domains
        assert "courtlistener.com" in domains
        assert "www.courtlistener.com" in domains

    def test_import_guard_passes(self, cl_skill):
        """Import guard must not flag any forbidden modules in the skill files."""
        # load_skill() already ran the guard; if we got here it passed.
        # Verify explicitly by re-running the guard function.
        from lighthouse_ai.skills.registry import _audit_skill_imports

        # Should raise nothing.
        _audit_skill_imports(cl_skill.path)


# ---------------------------------------------------------------------------
# CourtListener skill — run (offline, monkeypatched)
# ---------------------------------------------------------------------------


class TestCourtListenerRun:
    """Tests for the Pattern-1 run entrypoint."""

    def test_run_returns_tagged_documents(self, monkeypatch, cl_skill, broker):
        """run_skill returns Documents tagged with skill_id and grade."""
        monkeypatch.setattr(
            "lighthouse_ai.sources.courtlistener.search_courtlistener",
            lambda *a, **kw: _CANNED_DOCS[:2],
        )
        result = run_skill(cl_skill, "Fourth Amendment privacy", broker=broker)

        assert result.ok
        assert len(result.documents) == 2
        for doc in result.documents:
            assert doc.metadata["skill_id"] == "courtlistener"
            assert doc.metadata["grade"] == "B"
            assert doc.metadata["fetch_backend"] == "tier-a"

    def test_run_no_community_tag_for_signed_skill(self, monkeypatch, cl_skill, broker):
        """Signed skill must not carry the community downgrade tag."""
        monkeypatch.setattr(
            "lighthouse_ai.sources.courtlistener.search_courtlistener",
            lambda *a, **kw: _CANNED_DOCS[:1],
        )
        result = run_skill(cl_skill, "test", broker=broker)
        assert result.ok
        assert "community" not in result.documents[0].metadata

    def test_run_swallows_exception(self, monkeypatch, cl_skill, broker):
        """A failing search_courtlistener call must not propagate; returns []."""

        def _raise(*a, **kw):
            raise RuntimeError("network error")

        monkeypatch.setattr("lighthouse_ai.sources.courtlistener.search_courtlistener", _raise)
        result = run_skill(cl_skill, "antitrust", broker=broker)
        assert not result.ok or result.documents == []

    def test_run_empty_result_is_thin(self, monkeypatch, cl_skill, broker):
        """An empty result from search_courtlistener yields a thin run."""
        monkeypatch.setattr(
            "lighthouse_ai.sources.courtlistener.search_courtlistener",
            lambda *a, **kw: [],
        )
        result = run_skill(cl_skill, "obscure case xyz", broker=broker)
        assert result.documents == []
        assert result.thin

    def test_run_document_source_tag(self, monkeypatch, cl_skill, broker):
        """Each returned Document carries source='courtlistener'."""
        monkeypatch.setattr(
            "lighthouse_ai.sources.courtlistener.search_courtlistener",
            lambda *a, **kw: _CANNED_DOCS[:1],
        )
        result = run_skill(cl_skill, "Roe v. Wade", broker=broker)
        assert result.ok
        assert result.documents[0].metadata["source"] == "courtlistener"

    def test_run_document_ids_preserved(self, monkeypatch, cl_skill, broker):
        """Document IDs from the adapter are preserved through the skill."""
        monkeypatch.setattr(
            "lighthouse_ai.sources.courtlistener.search_courtlistener",
            lambda *a, **kw: _CANNED_DOCS[:2],
        )
        result = run_skill(cl_skill, "abortion rights", broker=broker)
        assert result.ok
        ids = {doc.id for doc in result.documents}
        assert "cl:1234567" in ids
        assert "cl:7654321" in ids


# ---------------------------------------------------------------------------
# CourtListener skill — run_watchable (offline, monkeypatched)
# ---------------------------------------------------------------------------


class TestCourtListenerWatchable:
    """Tests for the Pattern-2 run_watchable entrypoint (track_docket tool)."""

    def test_watchable_since_none_returns_all(self, monkeypatch, cl_skill, broker):
        """With since=None all canned documents are returned."""
        monkeypatch.setattr(
            "lighthouse_ai.sources.courtlistener.search_courtlistener",
            lambda *a, **kw: list(_CANNED_DOCS),
        )
        result = run_watchable(cl_skill, "constitutional law", since=None, broker=broker)
        assert result.ok
        assert len(result.documents) == 3

    def test_watchable_filters_by_since(self, monkeypatch, cl_skill, broker):
        """Documents with published_date on or before 'since' are excluded."""
        monkeypatch.setattr(
            "lighthouse_ai.sources.courtlistener.search_courtlistener",
            lambda *a, **kw: list(_CANNED_DOCS),
        )
        # Cutoff: only docs filed after 2021-01-01 should survive.
        # _CANNED_DOCS[0] → 1973-01-22 → excluded
        # _CANNED_DOCS[1] → 2022-06-24 → included
        # _CANNED_DOCS[2] → 2020-01-15 → excluded
        since = datetime(2021, 1, 1)
        result = run_watchable(cl_skill, "Roe v. Wade overruling", since=since, broker=broker)
        assert result.ok
        ids = {doc.id for doc in result.documents}
        assert "cl:7654321" in ids  # 2022, after cutoff → included
        assert "cl:1234567" not in ids  # 1973, before cutoff → excluded
        assert "cl:9999999" not in ids  # 2020, before cutoff → excluded

    def test_watchable_documents_carry_track_docket_tag(self, monkeypatch, cl_skill, broker):
        """Watchable documents carry watchable_tool='track_docket' metadata."""
        monkeypatch.setattr(
            "lighthouse_ai.sources.courtlistener.search_courtlistener",
            lambda *a, **kw: _CANNED_DOCS[:1],
        )
        result = run_watchable(cl_skill, "privacy", since=None, broker=broker)
        assert result.ok
        assert result.documents[0].metadata.get("watchable_tool") == "track_docket"

    def test_watchable_tagged_documents(self, monkeypatch, cl_skill, broker):
        """Watchable documents carry full skill provenance."""
        monkeypatch.setattr(
            "lighthouse_ai.sources.courtlistener.search_courtlistener",
            lambda *a, **kw: _CANNED_DOCS[:1],
        )
        result = run_watchable(cl_skill, "Fourth Amendment", since=None, broker=broker)
        assert result.ok
        doc = result.documents[0]
        assert doc.metadata["skill_id"] == "courtlistener"
        assert doc.metadata["grade"] == "B"

    def test_watchable_swallows_exception(self, monkeypatch, cl_skill, broker):
        """A failing search_courtlistener in run_watchable must not propagate."""

        def _raise(*a, **kw):
            raise ConnectionError("timeout")

        monkeypatch.setattr("lighthouse_ai.sources.courtlistener.search_courtlistener", _raise)
        result = run_watchable(cl_skill, "antitrust", since=None, broker=broker)
        assert result.documents == []

    def test_watchable_boundary_date_is_exclusive(self, monkeypatch, cl_skill, broker):
        """Documents whose published_date == since (boundary) are excluded."""
        monkeypatch.setattr(
            "lighthouse_ai.sources.courtlistener.search_courtlistener",
            lambda *a, **kw: list(_CANNED_DOCS),
        )
        # Exact boundary: the 2022 Dobbs opinion date.
        # Since filtering is <=, so Dobbs itself should be excluded.
        since = datetime(2022, 6, 24)
        result = run_watchable(cl_skill, "abortion", since=since, broker=broker)
        ids = {doc.id for doc in result.documents}
        assert "cl:7654321" not in ids  # boundary date → excluded


# ---------------------------------------------------------------------------
# load_skill integration check
# ---------------------------------------------------------------------------


def test_load_skill_courtlistener_via_module():
    """Confirm load_skill('courtlistener') works from a clean import path."""
    from lighthouse_ai.skills import load_skill as _ls

    skill = _ls("courtlistener")
    assert skill.manifest.id == "courtlistener"
    assert skill.manifest.category == "legal"


# ---------------------------------------------------------------------------
# Live / integration tests (opt-in)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="set LIGHTHOUSE_REAL_BACKEND=1 to run live tests",
)
def test_live_run_returns_documents(tmp_path):
    """Real network: search CourtListener and verify at least one Document is returned."""
    skill = load_skill("courtlistener")
    broker = build_default_broker(tmp_path)
    result = run_skill(skill, "Fourth Amendment unreasonable search seizure", broker=broker)

    assert result.ok
    assert len(result.documents) >= 1
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "courtlistener"
    assert doc.metadata["grade"] == "B"
    assert doc.text
