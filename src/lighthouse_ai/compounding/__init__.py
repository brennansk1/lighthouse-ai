"""Compounding knowledge — entity hotness, dossiers, archivist (OpenHuman §2/§8)."""

from __future__ import annotations

from .archivist import (
    ArchiveOutcome,
    archive_conversation,
    archive_report,
    clean_turns,
    compose_md,
    report_to_markdown,
)
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
    "ArchiveOutcome",
    "EntityStats",
    "HotnessBreakdown",
    "archive_conversation",
    "archive_report",
    "clean_turns",
    "compose_md",
    "hotness",
    "hotness_at",
    "hotness_breakdown",
    "recency_decay",
    "report_to_markdown",
]
