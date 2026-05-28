"""Reflection / Escalation primitives (OpenHuman §3).

Two distinct background-tick outputs, deliberately kept apart:

* **Reflection** — an *observation with no side effect*. Browsable on the
  Intelligence surface; never auto-posts into a conversation. May carry a
  ``proposed_action`` that, when tapped, spawns a **fresh** job (never bloats an
  existing session). Carries provenance: ``source_refs`` + resolved
  ``ChunkSnapshot``s.
* **Escalation** — an observation that *does* carry an actionable side effect,
  with a status and priority (e.g. a retracted source underpinning a Position →
  re-verify).

This split replaces Monitor's salience-threshold alert/digest cut, which
conflates "noticed something" with "needs your decision".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

__all__ = [
    "ChunkSnapshot",
    "Escalation",
    "EscalationPriority",
    "EscalationStatus",
    "Reflection",
    "ReflectionKind",
    "new_id",
    "now_iso",
]


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ReflectionKind(str, Enum):
    CITATION_SURGE = "citation_surge"
    SOURCE_DISAGREEMENT = "source_disagreement"
    STALE_POSITION = "stale_position"
    NEW_CORROBORATION = "new_corroboration"
    WHAT_CHANGED = "what_changed"


class EscalationStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class EscalationPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ChunkSnapshot:
    """Frozen provenance copy of a source chunk at the time of the observation."""

    chunk_id: str
    text: str
    source: str | None = None


@dataclass(frozen=True)
class Reflection:
    """Passive observation. Never carries an executable side effect."""

    kind: ReflectionKind
    body: str  # markdown
    proposed_action: str | None = None
    source_refs: list[str] = field(default_factory=list)
    source_chunks: list[ChunkSnapshot] = field(default_factory=list)
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class Escalation:
    """Actionable observation. Always carries status + priority."""

    kind: ReflectionKind
    body: str
    priority: EscalationPriority
    status: EscalationStatus = EscalationStatus.OPEN
    source_refs: list[str] = field(default_factory=list)
    id: str = field(default_factory=new_id)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
