"""Tests for entity-hotness persistence + materialisation gate (OpenHuman §2.4)."""

from __future__ import annotations

from lighthouse_ai.compounding.hotness import TOPIC_CREATION_THRESHOLD
from lighthouse_ai.compounding.hotness_store import EntityHotnessStore

NOW = 1_000 * 86_400_000


def _store(tmp_path) -> EntityHotnessStore:
    return EntityHotnessStore(tmp_path / "hotness.db")


def test_unknown_entity_has_no_stats_and_zero_hotness(tmp_path) -> None:
    s = _store(tmp_path)
    assert s.get_stats("ghost") is None
    assert s.hotness_of("ghost", now_ms=NOW) == 0.0
    assert s.should_materialise("ghost", now_ms=NOW) is False


def test_mentions_accumulate(tmp_path) -> None:
    s = _store(tmp_path)
    s.record_mention("transformer", source="arxiv.org", now_ms=NOW)
    s.record_mention("transformer", source="arxiv.org", now_ms=NOW)  # same source
    s.record_mention("transformer", source="openalex.org", now_ms=NOW)
    stats = s.get_stats("transformer")
    assert stats.mention_count_30d == 3
    assert stats.distinct_sources == 2  # distinct independent sources, not 3


def test_query_hits_and_centrality(tmp_path) -> None:
    s = _store(tmp_path)
    s.record_mention("x", source="a", now_ms=NOW)
    s.record_query_hit("x")
    s.record_query_hit("x")
    s.set_centrality("x", 0.5)
    stats = s.get_stats("x")
    assert stats.query_hits_30d == 2
    assert stats.graph_centrality == 0.5


def test_materialisation_gate_fires_only_past_threshold(tmp_path) -> None:
    s = _store(tmp_path)
    # Below threshold: a couple of mentions from one source.
    s.record_mention("cold", source="a", now_ms=NOW)
    assert s.should_materialise("cold", now_ms=NOW) is False
    # Hot: many independent sources + query hits clears 10.0.
    # Math: ln(7)+0.5x6+recency(1.0)+2x3 ~= 1.95+3.0+1.0+6.0 = 11.95
    for src in ("a", "b", "c", "d", "e", "f"):
        s.record_mention("hot", source=src, now_ms=NOW)
    s.record_query_hit("hot")
    s.record_query_hit("hot")
    s.record_query_hit("hot")
    assert s.hotness_of("hot", now_ms=NOW) >= TOPIC_CREATION_THRESHOLD
    assert s.should_materialise("hot", now_ms=NOW) is True


def test_hot_entities_lists_only_threshold_crossers_sorted(tmp_path) -> None:
    s = _store(tmp_path)
    s.record_mention("cold", source="a", now_ms=NOW)
    for src in ("a", "b", "c", "d", "e", "f", "g"):
        s.record_mention("warm", source=src, now_ms=NOW)
    # warm: ln(8)+0.5x7+1.0+2x2 ~= 2.08+3.5+1.0+4.0 = 10.58
    s.record_query_hit("warm")
    s.record_query_hit("warm")
    for src in ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j"):
        s.record_mention("blazing", source=src, now_ms=NOW)
    # blazing: ln(11)+0.5x10+1.0+2x2 ~= 2.40+5.0+1.0+4.0 = 12.40
    s.record_query_hit("blazing")
    s.record_query_hit("blazing")
    hot = s.hot_entities(now_ms=NOW)
    ids = [eid for eid, _ in hot]
    assert "cold" not in ids
    assert ids[0] == "blazing"  # hottest first
    assert set(ids) == {"warm", "blazing"}


def test_hotness_is_cached_after_scoring(tmp_path) -> None:
    s = _store(tmp_path)
    s.record_mention("x", source="a", now_ms=NOW)
    score = s.hotness_of("x", now_ms=NOW)
    from lighthouse_ai.persistence import open_db

    conn = open_db(s.db_path)
    try:
        cached = conn.execute(
            "SELECT last_hotness FROM entity_hotness WHERE entity_id='x'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert cached == score


def test_lazy_recompute_counter(tmp_path) -> None:
    s = _store(tmp_path)
    s.RECOMPUTE_EVERY = 3
    assert s._note_write() is False
    assert s._note_write() is False
    assert s._note_write() is True  # third write triggers; counter resets
    assert s._note_write() is False


def test_persistence_survives_reopen(tmp_path) -> None:
    db = tmp_path / "hotness.db"
    s1 = EntityHotnessStore(db)
    s1.record_mention("durable", source="a", now_ms=NOW)
    s2 = EntityHotnessStore(db)
    assert s2.get_stats("durable").mention_count_30d == 1
