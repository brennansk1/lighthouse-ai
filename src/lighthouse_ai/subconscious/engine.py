"""Subconscious tick engine (OpenHuman §3 + §4).

Each ``tick()`` gathers candidate reflections/escalations from injected producers,
caps reflections, and commits to the store — gated by the Scheduler Gate (§1, host
courtesy) and protected by the generation guard (§4, no double-commit if a slower
tick is overtaken by the next scheduled one).

Producers are injected so the engine is decoupled from any specific signal source
and testable without live feeds. One concrete producer ships here:
:func:`stale_position_escalations` (resolve-by-due → escalation).

Acting on a reflection spawns a **fresh** job seeded with its body + proposed
action; it never mutates an existing session transcript (context-window discipline).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from .overlap import GenerationGuard, TickResult
from .reflection import apply_cap
from .store import ReflectionStore
from .types import (
    Escalation,
    EscalationPriority,
    Reflection,
    ReflectionKind,
)

__all__ = [
    "SubconsciousEngine",
    "TickOutcome",
    "act_on_reflection",
    "stale_position_escalations",
]

ReflectionProducer = Callable[[], list[Reflection]]
EscalationProducer = Callable[[], list[Escalation]]


@dataclass(frozen=True)
class TickOutcome:
    result: TickResult
    reflections_committed: int
    escalations_committed: int


def _gate_ctx(gate):
    return gate.permit() if gate is not None else nullcontext()


class SubconsciousEngine:
    def __init__(
        self,
        store: ReflectionStore,
        *,
        gate=None,
        guard: GenerationGuard | None = None,
        reflection_producers: tuple[ReflectionProducer, ...] = (),
        escalation_producers: tuple[EscalationProducer, ...] = (),
        reflection_score: Callable[[Reflection], float] | None = None,
    ) -> None:
        self._store = store
        self._gate = gate
        self._guard = guard or GenerationGuard()
        self._reflection_producers = reflection_producers
        self._escalation_producers = escalation_producers
        self._reflection_score = reflection_score

    def tick(self) -> TickOutcome:
        my_gen = self._guard.begin()

        reflections: list[Reflection] = []
        escalations: list[Escalation] = []
        # Producers may be LLM-bound, so each runs under a host-courtesy permit.
        for r_produce in self._reflection_producers:
            with _gate_ctx(self._gate):
                reflections.extend(r_produce())
        for e_produce in self._escalation_producers:
            with _gate_ctx(self._gate):
                escalations.extend(e_produce())

        reflections = apply_cap(reflections, score=self._reflection_score)

        # A newer tick started while we were gathering → discard (no double-commit).
        if not self._guard.is_current(my_gen):
            return TickOutcome(TickResult.SUPERSEDED, 0, 0)

        for r in reflections:
            self._store.add_reflection(r)
        for e in escalations:
            self._store.add_escalation(e)
        return TickOutcome(TickResult.COMMITTED, len(reflections), len(escalations))


def stale_position_escalations(positions_db: Path) -> list[Escalation]:
    """Resolve-by-due → escalation: every unresolved past-deadline position."""
    from ..persistence import open_db
    from ..verification.positions import _ensure_extras
    from ..verification.resolver import is_past_deadline

    # On a fresh install the DB file may not exist yet; nothing to escalate.
    if not positions_db.exists():
        return []

    _ensure_extras(positions_db)
    conn = open_db(positions_db)
    try:
        # Guard against a DB that exists but has no positions table yet.
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='positions'"
        ).fetchone()
        if not has_table:
            return []
        rows = conn.execute(
            "SELECT id, claim, resolve_by FROM positions WHERE outcome IS NULL"
        ).fetchall()
    finally:
        conn.close()

    out: list[Escalation] = []
    for pos_id, claim, resolve_by in rows:
        if not is_past_deadline(resolve_by):
            continue
        out.append(
            Escalation(
                kind=ReflectionKind.STALE_POSITION,
                body=f"Position #{pos_id} hit its resolve-by date: {claim}",
                priority=EscalationPriority.MEDIUM,
                source_refs=[f"position:{pos_id}"],
            )
        )
    return out


def act_on_reflection(
    reflection: Reflection,
    *,
    spawn: Callable[[str], str],
) -> str:
    """Spawn a fresh job seeded with the reflection's body + proposed action.

    ``spawn`` takes the seed question text and returns a new job id. By design
    this creates a new thread and touches no existing session transcript.
    """
    seed = reflection.body
    if reflection.proposed_action:
        seed = f"{seed}\n\nProposed action: {reflection.proposed_action}"
    return spawn(seed)
