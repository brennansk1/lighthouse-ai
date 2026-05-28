"""Subconscious — background ticks, overlap guard, reflections/escalations (OpenHuman §3/§4)."""

from __future__ import annotations

from .engine import (
    SubconsciousEngine,
    TickOutcome,
    act_on_reflection,
    stale_position_escalations,
)
from .overlap import GenerationGuard, TickResult
from .reflection import MAX_REFLECTIONS_PER_TICK, apply_cap
from .store import ReflectionStore
from .types import (
    ChunkSnapshot,
    Escalation,
    EscalationPriority,
    EscalationStatus,
    Reflection,
    ReflectionKind,
)

__all__ = [
    "MAX_REFLECTIONS_PER_TICK",
    "ChunkSnapshot",
    "Escalation",
    "EscalationPriority",
    "EscalationStatus",
    "GenerationGuard",
    "Reflection",
    "ReflectionKind",
    "ReflectionStore",
    "SubconsciousEngine",
    "TickOutcome",
    "TickResult",
    "act_on_reflection",
    "apply_cap",
    "stale_position_escalations",
]
