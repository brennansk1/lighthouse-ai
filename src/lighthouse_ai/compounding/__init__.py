"""Compounding knowledge — entity hotness, dossiers, archivist (OpenHuman §2/§8)."""

from __future__ import annotations

from .hotness import (
    TOPIC_CREATION_THRESHOLD,
    EntityStats,
    HotnessBreakdown,
    hotness,
    hotness_at,
    hotness_breakdown,
    recency_decay,
)

__all__ = [
    "TOPIC_CREATION_THRESHOLD",
    "EntityStats",
    "HotnessBreakdown",
    "hotness",
    "hotness_at",
    "hotness_breakdown",
    "recency_decay",
]
