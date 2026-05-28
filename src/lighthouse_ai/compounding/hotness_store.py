"""Persistence + materialisation gate for entity hotness (OpenHuman §2.4).

The pure formula lives in :mod:`hotness`; this is its durable home. A side-table
accumulates the per-entity signals (mentions, distinct independent sources,
last-seen, query hits, graph centrality), and the materialisation gate decides
when an entity is hot enough to earn a tracked dossier.

Follows the project's lazy-ensure / ``open_db`` pattern (§26.1 PRAGMA discipline).
``distinct_sources`` is derived from a stored *set* of independent source keys —
never a raw mention count — so syndication can't inflate it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..persistence import open_db
from .hotness import TOPIC_CREATION_THRESHOLD, EntityStats, hotness_at

__all__ = ["EntityHotnessStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entity_hotness (
    entity_id TEXT PRIMARY KEY,
    mention_count_30d INTEGER NOT NULL DEFAULT 0,
    distinct_sources_json TEXT NOT NULL DEFAULT '[]',
    last_seen_ms INTEGER,
    query_hits_30d INTEGER NOT NULL DEFAULT 0,
    graph_centrality REAL,
    last_hotness REAL,
    last_updated_ms INTEGER
)
"""


def _now_ms() -> int:
    return int(time.time() * 1000)


class EntityHotnessStore:
    # Recompute cached hotness every N signal-writes (OpenHuman's lazy counter).
    RECOMPUTE_EVERY = 20

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._ingests_since_check = 0
        conn = open_db(db_path)
        try:
            conn.execute(_SCHEMA)
        finally:
            conn.close()

    # --- signal writes -----------------------------------------------------

    def record_mention(
        self, entity_id: str, *, source: str | None = None, now_ms: int | None = None
    ) -> None:
        """One mention of the entity, optionally from an independent ``source``."""
        now = now_ms if now_ms is not None else _now_ms()
        conn = open_db(self.db_path)
        try:
            row = conn.execute(
                "SELECT mention_count_30d, distinct_sources_json FROM entity_hotness "
                "WHERE entity_id=?", (entity_id,),
            ).fetchone()
            if row is None:
                sources = [source] if source else []
                conn.execute(
                    "INSERT INTO entity_hotness (entity_id, mention_count_30d, "
                    "distinct_sources_json, last_seen_ms, last_updated_ms) "
                    "VALUES (?, 1, ?, ?, ?)",
                    (entity_id, json.dumps(sources), now, now),
                )
            else:
                count = row[0] + 1
                sources = set(json.loads(row[1]))
                if source:
                    sources.add(source)
                conn.execute(
                    "UPDATE entity_hotness SET mention_count_30d=?, "
                    "distinct_sources_json=?, last_seen_ms=?, last_updated_ms=? "
                    "WHERE entity_id=?",
                    (count, json.dumps(sorted(sources)), now, now, entity_id),
                )
        finally:
            conn.close()
        self._note_write()

    def record_query_hit(self, entity_id: str) -> None:
        conn = open_db(self.db_path)
        try:
            conn.execute(
                "INSERT INTO entity_hotness (entity_id, query_hits_30d, last_updated_ms) "
                "VALUES (?, 1, ?) ON CONFLICT(entity_id) DO UPDATE SET "
                "query_hits_30d = query_hits_30d + 1, last_updated_ms=excluded.last_updated_ms",
                (entity_id, _now_ms()),
            )
        finally:
            conn.close()
        self._note_write()

    def set_centrality(self, entity_id: str, value: float) -> None:
        conn = open_db(self.db_path)
        try:
            conn.execute(
                "INSERT INTO entity_hotness (entity_id, graph_centrality, last_updated_ms) "
                "VALUES (?, ?, ?) ON CONFLICT(entity_id) DO UPDATE SET "
                "graph_centrality=excluded.graph_centrality, "
                "last_updated_ms=excluded.last_updated_ms",
                (entity_id, value, _now_ms()),
            )
        finally:
            conn.close()

    # --- reads / scoring ---------------------------------------------------

    def get_stats(self, entity_id: str) -> EntityStats | None:
        conn = open_db(self.db_path)
        try:
            row = conn.execute(
                "SELECT mention_count_30d, distinct_sources_json, last_seen_ms, "
                "query_hits_30d, graph_centrality FROM entity_hotness WHERE entity_id=?",
                (entity_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return EntityStats(
            mention_count_30d=row[0],
            distinct_sources=len(json.loads(row[1])),
            last_seen_ms=row[2],
            query_hits_30d=row[3],
            graph_centrality=row[4],
        )

    def hotness_of(self, entity_id: str, *, now_ms: int | None = None) -> float:
        stats = self.get_stats(entity_id)
        if stats is None:
            return 0.0
        now = now_ms if now_ms is not None else _now_ms()
        score = hotness_at(stats, now)
        self._cache_hotness(entity_id, score, now)
        return score

    def should_materialise(self, entity_id: str, *, now_ms: int | None = None) -> bool:
        """The dossier gate: is this entity hot enough to earn a tracked page?"""
        return self.hotness_of(entity_id, now_ms=now_ms) >= TOPIC_CREATION_THRESHOLD

    def hot_entities(self, *, now_ms: int | None = None) -> list[tuple[str, float]]:
        """All entities at/over the materialisation threshold, hottest first."""
        now = now_ms if now_ms is not None else _now_ms()
        conn = open_db(self.db_path)
        try:
            ids = [r[0] for r in conn.execute("SELECT entity_id FROM entity_hotness")]
        finally:
            conn.close()
        scored = [(eid, self.hotness_of(eid, now_ms=now)) for eid in ids]
        hot = [(eid, s) for eid, s in scored if s >= TOPIC_CREATION_THRESHOLD]
        hot.sort(key=lambda t: t[1], reverse=True)
        return hot

    # --- internals ---------------------------------------------------------

    def _cache_hotness(self, entity_id: str, score: float, now: int) -> None:
        conn = open_db(self.db_path)
        try:
            conn.execute(
                "UPDATE entity_hotness SET last_hotness=?, last_updated_ms=? "
                "WHERE entity_id=?", (score, now, entity_id),
            )
        finally:
            conn.close()

    def _note_write(self) -> bool:
        """Increment the lazy-recompute counter; True when a recompute is due."""
        self._ingests_since_check += 1
        if self._ingests_since_check >= self.RECOMPUTE_EVERY:
            self._ingests_since_check = 0
            return True
        return False
