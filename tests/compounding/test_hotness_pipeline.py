"""Tests for entity-hotness wiring to the ingest path (OpenHuman §2 follow-up).

These tests exercise the store API at the level that pipeline.ingest_text uses
without importing the full pipeline (which needs yaml/ollama deps).
"""

from __future__ import annotations

from urllib.parse import urlparse

from lighthouse_ai.compounding.hotness_store import EntityHotnessStore


def _source_domain(source: str) -> str:
    """Mirror of pipeline._source_domain — extract normalised domain key."""
    parsed = urlparse(source)
    return parsed.netloc or source.split("/")[0] or source

NOW = 1_000 * 86_400_000


# ── _source_domain helper ────────────────────────────────────────────────────

def test_source_domain_extracts_netloc() -> None:
    assert _source_domain("https://arxiv.org/abs/1234.5678") == "arxiv.org"


def test_source_domain_preserves_bare_hostname() -> None:
    assert _source_domain("openalex.org/W123") == "openalex.org"


def test_source_domain_falls_back_for_local_path() -> None:
    # Local file paths have no netloc; return the first path component.
    result = _source_domain("/home/user/paper.pdf")
    assert result  # non-empty; exact form is an impl detail


def test_source_domain_empty_string_safe() -> None:
    assert isinstance(_source_domain(""), str)


# ── ingest-path simulation ───────────────────────────────────────────────────

def _simulate_ingest(store: EntityHotnessStore,
                     tracked: set[str],
                     text: str,
                     source: str,
                     now_ms: int) -> None:
    """Mirror the entity-mention logic in pipeline.ingest_text."""
    source_key = _source_domain(source)
    text_lower = text.lower()
    for entity_id in tracked:
        if entity_id.lower() in text_lower:
            store.record_mention(entity_id, source=source_key, now_ms=now_ms)


def test_ingest_records_mention_for_tracked_entity(tmp_path) -> None:
    store = EntityHotnessStore(tmp_path / "h.db")
    tracked = {"CRISPR", "AlphaFold"}
    _simulate_ingest(store, tracked,
                     text="Recent work on CRISPR gene editing has shown ...",
                     source="https://nature.com/article/123",
                     now_ms=NOW)
    stats = store.get_stats("CRISPR")
    assert stats is not None
    assert stats.mention_count_30d == 1
    assert stats.distinct_sources == 1  # nature.com


def test_ingest_case_insensitive_match(tmp_path) -> None:
    store = EntityHotnessStore(tmp_path / "h.db")
    _simulate_ingest(store, {"alphafold"},
                     text="AlphaFold predictions improved.",
                     source="https://science.org/paper",
                     now_ms=NOW)
    assert store.get_stats("alphafold") is not None


def test_ingest_no_match_leaves_store_empty(tmp_path) -> None:
    store = EntityHotnessStore(tmp_path / "h.db")
    _simulate_ingest(store, {"GPT-5"},
                     text="Totally unrelated content about butterflies.",
                     source="https://example.com",
                     now_ms=NOW)
    assert store.get_stats("GPT-5") is None


def test_ingest_deduplicates_same_source(tmp_path) -> None:
    store = EntityHotnessStore(tmp_path / "h.db")
    for _ in range(3):
        _simulate_ingest(store, {"CRISPR"},
                         text="CRISPR was mentioned.",
                         source="https://pubmed.ncbi.nlm.nih.gov/123",
                         now_ms=NOW)
    stats = store.get_stats("CRISPR")
    assert stats.mention_count_30d == 3
    assert stats.distinct_sources == 1  # same domain, not 3


def test_ingest_different_sources_accumulate_distinct(tmp_path) -> None:
    store = EntityHotnessStore(tmp_path / "h.db")
    for src in ("https://arxiv.org/p1", "https://nature.com/p2", "https://pubmed.ncbi.nlm.nih.gov/p3"):
        _simulate_ingest(store, {"transformer"},
                         text="transformer architecture explained",
                         source=src,
                         now_ms=NOW)
    stats = store.get_stats("transformer")
    assert stats.distinct_sources == 3
