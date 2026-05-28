"""Hotness Score — deterministic, LLM-free entity-importance (OpenHuman §2).

One formula decides when an entity is important enough to materialise its own
tracked dossier, and (re)scores Monitor salience. Every term is named and
greppable, so a score always decomposes into an explainable breakdown.

    hotness = ln(mentions + 1)          # dampened high-volume bias
            + 0.5 * distinct_sources    # cross-source corroboration is valuable
            + recency_decay(last_seen)  # prefer active entities
            + graph_centrality          # 0.0 until a citation graph exists
            + 2.0 * query_hits          # retrieval-feedback loop

``distinct_sources`` MUST be the *independent*-source count (distinct domains, per
``verification.discipline.check_source_diversity`` semantics), NOT raw citation
count — otherwise citation cartels and press-release syndication inflate hotness,
contradicting the discipline layer. This term operationalises Lighthouse's
source-independence value as a ranking signal, not just a binary discipline gate.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

__all__ = [
    "TOPIC_CREATION_THRESHOLD",
    "EntityStats",
    "HotnessBreakdown",
    "hotness",
    "hotness_at",
    "hotness_breakdown",
    "recency_decay",
]

TOPIC_CREATION_THRESHOLD = 10.0
_DAY_MS = 86_400_000


@dataclass(frozen=True)
class EntityStats:
    mention_count_30d: int
    distinct_sources: int  # distinct *independent* source domains/authors
    last_seen_ms: int | None
    query_hits_30d: int = 0
    graph_centrality: float | None = None  # None → 0.0 until citation graph lands


@dataclass(frozen=True)
class HotnessBreakdown:
    """The five named terms behind a score — surface in the 'why salient' tooltip."""

    mentions: float
    sources: float
    recency: float
    centrality: float
    query_hits: float

    @property
    def total(self) -> float:
        return self.mentions + self.sources + self.recency + self.centrality + self.query_hits

    def as_dict(self) -> dict:
        return {
            "mentions": self.mentions,
            "sources": self.sources,
            "recency": self.recency,
            "centrality": self.centrality,
            "query_hits": self.query_hits,
            "total": self.total,
        }


def recency_decay(last_seen_ms: int | None, now_ms: int) -> float:
    """Piecewise-linear taper: ≤1d→1.0; 1–7d→1.0→0.5; 7–30d→0.5→0.0; >30d→0.0."""
    if last_seen_ms is None:
        return 0.0
    age = now_ms - last_seen_ms
    if age <= 0:
        return 1.0
    if age <= _DAY_MS:
        return 1.0
    if age <= 7 * _DAY_MS:
        return 1.0 - 0.5 * (age - _DAY_MS) / (6 * _DAY_MS)
    if age <= 30 * _DAY_MS:
        return 0.5 - 0.5 * (age - 7 * _DAY_MS) / (23 * _DAY_MS)
    return 0.0


def hotness_breakdown(stats: EntityStats, now_ms: int) -> HotnessBreakdown:
    return HotnessBreakdown(
        mentions=math.log(stats.mention_count_30d + 1),
        sources=0.5 * stats.distinct_sources,
        recency=recency_decay(stats.last_seen_ms, now_ms),
        centrality=(stats.graph_centrality or 0.0),
        query_hits=2.0 * stats.query_hits_30d,
    )


def hotness_at(stats: EntityStats, now_ms: int) -> float:
    return hotness_breakdown(stats, now_ms).total


def hotness(stats: EntityStats) -> float:
    return hotness_at(stats, int(time.time() * 1000))
