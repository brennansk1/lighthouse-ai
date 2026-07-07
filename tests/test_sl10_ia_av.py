"""Offline tests for SL10 — Internet Archive audio/video skill.

Test plan
---------
Skill load + import guard
  - ``load_skill('internet_archive_av')`` succeeds: manifest parses, import
    guard passes, entrypoint callable.
  - Manifest fields match the spec: id, category, tier A, signed, output_shape,
    temporal_tools, allowed_domains, modes_natural_fit, domains.
  - Import guard passes (no forbidden httpx/requests/urllib imports).

search_av (monkeypatched ctx.fetch)
  - Returns a list of item dicts from a canned advancedsearch JSON response.
  - Handles HTTP errors gracefully (returns []).
  - Handles malformed JSON gracefully (returns []).

fetch_metadata (monkeypatched ctx.fetch)
  - Returns the parsed metadata dict for a canned response.
  - Returns {} on HTTP error.

fetch_transcript
  - Returns None gracefully when no ASR provider is registered and no caption
    file is present (the documented v1 stub path).
  - Returns transcript text when transcript.py cache is pre-populated
    (``cache_transcript`` before calling ``fetch_transcript``).
  - Fetches a caption file via ctx.fetch when the metadata files list contains
    a Closed Caption Text entry.
  - Does NOT call ctx.fetch for a caption URL when the cache already has the
    answer (cache wins).

run() (monkeypatched ctx.fetch with canned search + metadata responses)
  - Returns tagged Documents (``source="internet_archive_av"``).
  - Documents carry ``skill_id="internet_archive_av"`` from the runner.
  - Empty search result returns [].
  - max_results is respected.
  - Gracefully falls back to description text when no transcript.

load_skill via discover_skills
  - ``discover_skills()`` includes ``internet_archive_av``.

All tests are fully offline — no real HTTP traffic.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.skills import discover_skills, load_skill
from lighthouse_ai.sources import transcript as _transcript

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LIBRARY_DIR = Path(__file__).parent.parent / "src" / "lighthouse_ai" / "skills" / "library"

# ---------------------------------------------------------------------------
# Canned JSON fixtures
# ---------------------------------------------------------------------------

_CANNED_SEARCH_RESPONSE = json.dumps(
    {
        "response": {
            "numFound": 2,
            "start": 0,
            "docs": [
                {
                    "identifier": "NBC20010911",
                    "title": "NBC Nightly News 9/11 2001",
                    "description": "NBC evening news broadcast from September 11 2001.",
                    "mediatype": "movies",
                    "date": "2001-09-11",
                    "creator": "NBC",
                    "subject": ["9/11", "terrorism", "news"],
                    "collection": "tvarchive",
                },
                {
                    "identifier": "CBS20010911",
                    "title": "CBS News Special Report 9/11",
                    "description": "CBS coverage of the September 11 attacks.",
                    "mediatype": "movies",
                    "date": "2001-09-11",
                    "creator": "CBS",
                    "subject": ["9/11", "terrorism"],
                    "collection": "tvarchive",
                },
            ],
        }
    }
).encode()

_CANNED_METADATA_NBC = json.dumps(
    {
        "metadata": {
            "identifier": "NBC20010911",
            "title": "NBC Nightly News 9/11 2001",
            "description": "NBC evening news broadcast from September 11 2001.",
            "mediatype": "movies",
            "date": "2001-09-11",
            "creator": "NBC",
            "collection": "tvarchive",
        },
        "files": [
            {"name": "NBC20010911.mp4", "format": "h.264"},
            {"name": "NBC20010911.cc5.txt", "format": "Closed Caption Text"},
        ],
    }
).encode()

_CANNED_METADATA_CBS = json.dumps(
    {
        "metadata": {
            "identifier": "CBS20010911",
            "title": "CBS News Special Report 9/11",
            "description": "CBS coverage of the September 11 attacks.",
            "mediatype": "movies",
            "date": "2001-09-11",
            "creator": "CBS",
            "collection": "tvarchive",
        },
        "files": [
            {"name": "CBS20010911.mp4", "format": "h.264"},
        ],
    }
).encode()

_CANNED_CAPTION_TEXT = b"ANNOUNCER: Breaking news. Two planes have struck the World Trade Center."

_CANNED_EMPTY_SEARCH = json.dumps({"response": {"numFound": 0, "start": 0, "docs": []}}).encode()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_response(content: bytes, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=content)


def _make_ctx(broker, responses: dict[str, bytes]):
    """Build a SkillContext with a monkeypatched ctx.fetch returning canned bytes.

    ``responses`` maps URL prefix -> bytes; first matching prefix wins.
    Any unmatched URL returns a 404.
    """
    from lighthouse_ai.governor.egress_proxy import DEFAULT_ALLOWED_DOMAINS
    from lighthouse_ai.skills.capabilities import SkillContext

    ctx = SkillContext(
        skill_id="internet_archive_av",
        skill_version="0.1.0",
        effective_domains=DEFAULT_ALLOWED_DOMAINS | frozenset({"archive.org", "web.archive.org"}),
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_transcript_state():
    """Reset transcript module state before/after each test."""
    _transcript.clear_cache()
    _transcript.clear_providers()
    yield
    _transcript.clear_cache()
    _transcript.clear_providers()


@pytest.fixture()
def ia_skill():
    return load_skill("internet_archive_av", library_dir=_LIBRARY_DIR)


# ---------------------------------------------------------------------------
# Skill load + manifest
# ---------------------------------------------------------------------------


class TestSkillLoad:
    """Tests that the skill loads cleanly and its manifest matches the spec."""

    def test_load_skill_succeeds(self, ia_skill):
        assert ia_skill.manifest.id == "internet_archive_av"
        assert callable(ia_skill.entrypoint)

    def test_manifest_id(self, ia_skill):
        assert ia_skill.manifest.id == "internet_archive_av"

    def test_manifest_category(self, ia_skill):
        assert ia_skill.manifest.category == "media"

    def test_manifest_tier(self, ia_skill):
        assert ia_skill.manifest.tier == "A"

    def test_manifest_signed(self, ia_skill):
        assert ia_skill.manifest.signed is True

    def test_manifest_not_community(self, ia_skill):
        assert ia_skill.manifest.is_community is False

    def test_manifest_output_shape(self, ia_skill):
        assert ia_skill.manifest.output_shape == "enumerable"

    def test_manifest_temporal_tools(self, ia_skill):
        assert ia_skill.manifest.temporal_tools is True

    def test_manifest_watchable_false(self, ia_skill):
        assert ia_skill.manifest.watchable is False

    def test_manifest_allowed_domains(self, ia_skill):
        domains = ia_skill.manifest.allowed_domains
        assert "archive.org" in domains
        assert "web.archive.org" in domains

    def test_manifest_modes_natural_fit(self, ia_skill):
        fit = ia_skill.manifest.modes_natural_fit
        assert "investigate" in fit
        assert "reconstruct" in fit

    def test_manifest_topics_include_media_domains(self, ia_skill):
        # The manifest's `domains` TOML field is an informational tag; the
        # scoring surface exposed by the schema is `topics`.
        topics = ia_skill.manifest.topics
        assert "media" in topics
        assert "history" in topics

    def test_import_guard_passes(self, ia_skill):
        """Import guard must not flag any forbidden modules."""
        from lighthouse_ai.skills.registry import _audit_skill_imports

        _audit_skill_imports(ia_skill.path)


# ---------------------------------------------------------------------------
# search_av
# ---------------------------------------------------------------------------


class TestSearchAv:
    """Tests for the search_av tool function."""

    def test_returns_item_list(self, broker):
        """Returns a list of item dicts from a canned advancedsearch response."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/advancedsearch.php": _CANNED_SEARCH_RESPONSE,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import search_av

        results = search_av(ctx, "NBC 9/11 2001", max_results=5)
        assert len(results) == 2
        assert results[0]["identifier"] == "NBC20010911"
        assert results[0]["title"] == "NBC Nightly News 9/11 2001"
        assert results[0]["mediatype"] == "movies"
        assert "archive.org/details/NBC20010911" in results[0]["url"]

    def test_returns_empty_on_http_error(self, broker):
        """HTTP non-200 response returns empty list gracefully."""
        ctx = _make_ctx(broker, {})  # all URLs → 404
        from lighthouse_ai.skills.library.internet_archive_av.skill import search_av

        results = search_av(ctx, "anything", max_results=5)
        assert results == []

    def test_returns_empty_on_malformed_json(self, broker):
        """Malformed JSON returns empty list gracefully."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/advancedsearch.php": b"not json",
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import search_av

        results = search_av(ctx, "test", max_results=5)
        assert results == []

    def test_respects_max_results(self, broker):
        """max_results caps the number of returned items."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/advancedsearch.php": _CANNED_SEARCH_RESPONSE,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import search_av

        results = search_av(ctx, "news", max_results=1)
        assert len(results) <= 1

    def test_returns_empty_on_no_docs(self, broker):
        """Empty docs array in response returns []."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/advancedsearch.php": _CANNED_EMPTY_SEARCH,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import search_av

        results = search_av(ctx, "obscure query", max_results=5)
        assert results == []


# ---------------------------------------------------------------------------
# fetch_metadata
# ---------------------------------------------------------------------------


class TestFetchMetadata:
    """Tests for the fetch_metadata tool function."""

    def test_returns_metadata_dict(self, broker):
        """Returns parsed metadata dict from a canned response."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/metadata/NBC20010911": _CANNED_METADATA_NBC,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import fetch_metadata

        meta = fetch_metadata(ctx, "NBC20010911")
        assert "metadata" in meta
        assert meta["metadata"]["identifier"] == "NBC20010911"
        assert meta["metadata"]["date"] == "2001-09-11"
        assert "files" in meta
        assert any(f["format"] == "Closed Caption Text" for f in meta["files"])

    def test_returns_empty_dict_on_http_error(self, broker):
        """HTTP 404 returns empty dict gracefully."""
        ctx = _make_ctx(broker, {})
        from lighthouse_ai.skills.library.internet_archive_av.skill import fetch_metadata

        meta = fetch_metadata(ctx, "nonexistent_item")
        assert meta == {}

    def test_returns_empty_dict_on_malformed_json(self, broker):
        """Malformed JSON returns empty dict gracefully."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/metadata/": b"{{bad json}}",
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import fetch_metadata

        meta = fetch_metadata(ctx, "bad_item")
        assert meta == {}


# ---------------------------------------------------------------------------
# fetch_transcript
# ---------------------------------------------------------------------------


class TestFetchTranscript:
    """Tests for the fetch_transcript tool function and transcript.py integration."""

    def test_returns_none_gracefully_no_provider_no_cache(self, broker):
        """Returns None when no ASR provider is registered and no cache/caption."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/metadata/": _CANNED_METADATA_CBS,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import fetch_transcript

        result = fetch_transcript(ctx, "CBS20010911")
        assert result is None

    def test_returns_cached_transcript_from_transcript_py(self, broker):
        """When transcript.py cache is pre-populated, fetch_transcript returns it."""
        _transcript.cache_transcript("NBC20010911", "Pre-cached transcript text.")
        ctx = _make_ctx(broker, {})  # no fetch should be needed
        from lighthouse_ai.skills.library.internet_archive_av.skill import fetch_transcript

        result = fetch_transcript(ctx, "NBC20010911")
        assert result == "Pre-cached transcript text."

    def test_fetches_caption_file_when_present(self, broker):
        """Fetches caption file via ctx.fetch when metadata has a caption entry."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/metadata/NBC20010911": _CANNED_METADATA_NBC,
                "https://archive.org/download/NBC20010911/": _CANNED_CAPTION_TEXT,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import fetch_transcript

        result = fetch_transcript(ctx, "NBC20010911")
        # Caption text was found and returned.
        assert result is not None
        assert "World Trade Center" in result

    def test_caption_fetch_populates_transcript_cache(self, broker):
        """After fetching a caption file, the result is in transcript.py cache."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/metadata/NBC20010911": _CANNED_METADATA_NBC,
                "https://archive.org/download/NBC20010911/": _CANNED_CAPTION_TEXT,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import fetch_transcript

        fetch_transcript(ctx, "NBC20010911")
        # Now the cache should be populated.
        assert "NBC20010911" in _transcript._CACHE
        assert "World Trade Center" in _transcript._CACHE["NBC20010911"]

    def test_cache_wins_no_fetch_needed(self, broker):
        """When cache is pre-populated, no ctx.fetch call is needed."""
        _transcript.cache_transcript("NBC20010911", "Already cached.")
        fetch_calls = []

        from lighthouse_ai.governor.egress_proxy import DEFAULT_ALLOWED_DOMAINS
        from lighthouse_ai.skills.capabilities import SkillContext

        ctx = SkillContext(
            skill_id="internet_archive_av",
            skill_version="0.1.0",
            effective_domains=DEFAULT_ALLOWED_DOMAINS | frozenset({"archive.org"}),
            broker=build_default_broker(Path("/tmp")),
            gateway=None,
            default_grade="B",
            community=False,
            tier="A",
        )

        def _tracking_fetch(url: str, **_kwargs):
            fetch_calls.append(url)
            return _fake_response(b"should not be called", 200)

        ctx.fetch = _tracking_fetch  # type: ignore[method-assign]

        from lighthouse_ai.skills.library.internet_archive_av.skill import fetch_transcript

        result = fetch_transcript(ctx, "NBC20010911")
        assert result == "Already cached."
        # No fetch should have been called because the cache hit immediately.
        assert fetch_calls == []

    def test_returns_none_no_caption_file_in_metadata(self, broker):
        """Returns None when metadata has no caption file and no provider."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/metadata/CBS20010911": _CANNED_METADATA_CBS,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import fetch_transcript

        # CBS metadata has no caption file.
        result = fetch_transcript(ctx, "CBS20010911")
        assert result is None

    def test_registered_provider_is_used(self, broker):
        """A registered transcript provider is tried and its result returned."""

        def _mock_asr(audio_ref: str) -> str | None:
            if audio_ref == "test_audio_item":
                return "Provider-generated transcript."
            return None

        _transcript.register_provider(_mock_asr)
        ctx = _make_ctx(broker, {})  # no caption URL needed
        from lighthouse_ai.skills.library.internet_archive_av.skill import fetch_transcript

        result = fetch_transcript(ctx, "test_audio_item")
        assert result == "Provider-generated transcript."


# ---------------------------------------------------------------------------
# run() via SkillContext
# ---------------------------------------------------------------------------


class TestRun:
    """Tests for the run() entrypoint (direct call with monkeypatched ctx)."""

    def test_run_returns_documents(self, broker):
        """run() returns Documents with correct source tag."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/advancedsearch.php": _CANNED_SEARCH_RESPONSE,
                "https://archive.org/metadata/NBC20010911": _CANNED_METADATA_NBC,
                "https://archive.org/metadata/CBS20010911": _CANNED_METADATA_CBS,
                "https://archive.org/download/NBC20010911/": _CANNED_CAPTION_TEXT,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import run

        docs = run(ctx, "9/11 news broadcast", max_results=5)
        assert len(docs) >= 1
        for doc in docs:
            assert doc.metadata["source"] == "internet_archive_av"
            assert doc.metadata["skill_id"] == "internet_archive_av"

    def test_run_empty_search_returns_empty_list(self, broker):
        """Empty search result yields []."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/advancedsearch.php": _CANNED_EMPTY_SEARCH,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import run

        docs = run(ctx, "very obscure query xyz", max_results=5)
        assert docs == []

    def test_run_max_results_respected(self, broker):
        """max_results limits the number of returned Documents."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/advancedsearch.php": _CANNED_SEARCH_RESPONSE,
                "https://archive.org/metadata/NBC20010911": _CANNED_METADATA_NBC,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import run

        docs = run(ctx, "news", max_results=1)
        assert len(docs) <= 1

    def test_run_doc_has_identifier(self, broker):
        """Returned Documents have identifier in metadata."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/advancedsearch.php": _CANNED_SEARCH_RESPONSE,
                "https://archive.org/metadata/NBC20010911": _CANNED_METADATA_NBC,
                "https://archive.org/metadata/CBS20010911": _CANNED_METADATA_CBS,
                "https://archive.org/download/NBC20010911/": _CANNED_CAPTION_TEXT,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import run

        docs = run(ctx, "9/11", max_results=2)
        assert any(doc.metadata.get("identifier") == "NBC20010911" for doc in docs)

    def test_run_doc_with_transcript_uses_transcript_text(self, broker):
        """When a caption file is found, the Document text includes transcript content."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/advancedsearch.php": _CANNED_SEARCH_RESPONSE,
                "https://archive.org/metadata/NBC20010911": _CANNED_METADATA_NBC,
                "https://archive.org/metadata/CBS20010911": _CANNED_METADATA_CBS,
                "https://archive.org/download/NBC20010911/": _CANNED_CAPTION_TEXT,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import run

        docs = run(ctx, "NBC 9/11", max_results=1)
        assert len(docs) >= 1
        nbc_doc = next((d for d in docs if d.metadata.get("identifier") == "NBC20010911"), None)
        if nbc_doc is not None:
            assert "World Trade Center" in nbc_doc.text
            assert nbc_doc.metadata.get("text_type") == "transcript"

    def test_run_doc_falls_back_to_description(self, broker):
        """Without a caption file, the Document text uses the description."""
        ctx = _make_ctx(
            broker,
            {
                "https://archive.org/advancedsearch.php": _CANNED_SEARCH_RESPONSE,
                "https://archive.org/metadata/NBC20010911": _CANNED_METADATA_NBC,
                "https://archive.org/metadata/CBS20010911": _CANNED_METADATA_CBS,
            },
        )
        from lighthouse_ai.skills.library.internet_archive_av.skill import run

        docs = run(ctx, "CBS 9/11", max_results=2)
        cbs_doc = next((d for d in docs if d.metadata.get("identifier") == "CBS20010911"), None)
        if cbs_doc is not None:
            # CBS has no caption file; should fall back to description.
            assert cbs_doc.metadata.get("text_type") in ("description", "title_only")


# ---------------------------------------------------------------------------
# run_skill() integration
# ---------------------------------------------------------------------------


class TestRunSkillIntegration:
    """Tests using the full run_skill() runner path."""

    def test_run_skill_returns_tagged_docs(self, ia_skill, broker, monkeypatch):
        """run_skill tags Documents with skill_id and provenance metadata."""
        from lighthouse_ai.skills import run_skill as _run_skill
        from lighthouse_ai.skills.library.internet_archive_av import skill as _skill_mod

        # Monkeypatch search_av inside the skill module to return canned items.
        monkeypatch.setattr(
            _skill_mod,
            "search_av",
            lambda ctx, q, **kw: [
                {
                    "identifier": "NBC20010911",
                    "title": "NBC Nightly News 9/11 2001",
                    "description": "NBC evening news broadcast.",
                    "mediatype": "movies",
                    "date": "2001-09-11",
                    "creator": "NBC",
                    "subject": [],
                    "collection": "tvarchive",
                    "url": "https://archive.org/details/NBC20010911",
                }
            ],
        )
        monkeypatch.setattr(
            _skill_mod,
            "fetch_metadata",
            lambda ctx, identifier: {
                "metadata": {
                    "identifier": identifier,
                    "title": "NBC Nightly News 9/11 2001",
                    "description": "NBC evening news broadcast.",
                    "mediatype": "movies",
                    "date": "2001-09-11",
                    "creator": "NBC",
                    "collection": "tvarchive",
                },
                "files": [],
            },
        )
        monkeypatch.setattr(
            _skill_mod,
            "fetch_transcript",
            lambda ctx, identifier, **kw: None,
        )

        result = _run_skill(ia_skill, "NBC 9/11 news", broker=broker)
        assert result.ok
        assert len(result.documents) >= 1
        doc = result.documents[0]
        assert doc.metadata["skill_id"] == "internet_archive_av"
        assert doc.metadata["source"] == "internet_archive_av"
        assert "fetch_backend" in doc.metadata

    def test_run_skill_empty_returns_thin(self, ia_skill, broker, monkeypatch):
        """Empty result from search_av yields a thin run."""
        from lighthouse_ai.skills import run_skill as _run_skill
        from lighthouse_ai.skills.library.internet_archive_av import skill as _skill_mod

        monkeypatch.setattr(
            _skill_mod,
            "search_av",
            lambda ctx, q, **kw: [],
        )
        result = _run_skill(ia_skill, "nothing matches this", broker=broker)
        assert result.documents == []
        assert result.thin


# ---------------------------------------------------------------------------
# discover_skills integration
# ---------------------------------------------------------------------------


def test_discover_skills_includes_internet_archive_av():
    """discover_skills() picks up internet_archive_av from the library directory."""
    manifests = discover_skills(_LIBRARY_DIR)
    assert "internet_archive_av" in manifests, (
        f"internet_archive_av not found in discovered skills: {list(manifests.keys())}"
    )


def test_load_skill_via_default_library():
    """load_skill('internet_archive_av') works without explicit library_dir."""
    skill = load_skill("internet_archive_av")
    assert skill.manifest.id == "internet_archive_av"
    assert skill.manifest.category == "media"
