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
from .hotness_store import EntityHotnessStore
from .logseq_sync import SyncResult, pending_count, sync_drafts

__all__ = [
    "TOPIC_CREATION_THRESHOLD",
    "ArchiveOutcome",
    "EntityHotnessStore",
    "EntityStats",
    "HotnessBreakdown",
    "SyncResult",
    "archive_conversation",
    "archive_report",
    "clean_turns",
    "compose_md",
    "hotness",
    "hotness_at",
    "hotness_breakdown",
    "pending_count",
    "recency_decay",
    "report_to_markdown",
    "sync_drafts",
]
