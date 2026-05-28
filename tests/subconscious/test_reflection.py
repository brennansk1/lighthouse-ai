"""Tests for reflection/escalation types, cap, store, and engine (OpenHuman §3)."""

from __future__ import annotations

from lighthouse_ai.schema import kinds_for
from lighthouse_ai.subconscious import (
    MAX_REFLECTIONS_PER_TICK,
    Escalation,
    EscalationPriority,
    EscalationStatus,
    GenerationGuard,
    Reflection,
    ReflectionKind,
    ReflectionStore,
    SubconsciousEngine,
    TickResult,
    act_on_reflection,
    apply_cap,
    stale_position_escalations,
)
from lighthouse_ai.subconscious.types import ChunkSnapshot
from lighthouse_ai.verification.positions import record_position

PAST = "2000-01-01T00:00:00"


def _refl(body: str = "obs", **kw) -> Reflection:
    return Reflection(kind=ReflectionKind.WHAT_CHANGED, body=body, **kw)


def _store(migrated_paths) -> ReflectionStore:
    return ReflectionStore(migrated_paths.data_dir / "subconscious.db")


# --- type invariants -------------------------------------------------------


def test_reflection_has_no_side_effect_fields() -> None:
    r = _refl()
    # A reflection carries provenance + an optional proposed_action, but no
    # status/priority (those belong to escalations).
    assert not hasattr(r, "status")
    assert not hasattr(r, "priority")


def test_escalation_always_carries_status_and_priority() -> None:
    e = Escalation(kind=ReflectionKind.STALE_POSITION, body="x",
                   priority=EscalationPriority.HIGH)
    assert e.status is EscalationStatus.OPEN  # defaults to open
    assert e.priority is EscalationPriority.HIGH


# --- cap -------------------------------------------------------------------


def test_apply_cap_keeps_at_most_max() -> None:
    refl = [_refl(f"r{i}") for i in range(10)]
    kept = apply_cap(refl)
    assert len(kept) == MAX_REFLECTIONS_PER_TICK


def test_apply_cap_under_limit_returns_all() -> None:
    refl = [_refl(f"r{i}") for i in range(3)]
    assert len(apply_cap(refl)) == 3


def test_apply_cap_prefers_higher_score() -> None:
    refl = [_refl("low"), _refl("high"), _refl("mid")]
    score = {"low": 1.0, "mid": 5.0, "high": 9.0}
    kept = apply_cap(refl, score=lambda r: score[r.body], limit=2)
    assert [r.body for r in kept] == ["high", "mid"]


def test_apply_cap_preserves_order_without_score() -> None:
    refl = [_refl(f"r{i}") for i in range(8)]
    kept = apply_cap(refl, limit=3)
    assert [r.body for r in kept] == ["r0", "r1", "r2"]


# --- store round-trip ------------------------------------------------------


def test_store_reflection_round_trip(migrated_paths) -> None:
    store = _store(migrated_paths)
    r = _refl("found something", proposed_action="dig deeper",
              source_refs=["doc:1"],
              source_chunks=[ChunkSnapshot("c1", "snippet", "arxiv.org")])
    store.add_reflection(r)
    got = store.list_reflections()
    assert len(got) == 1
    assert got[0].body == "found something"
    assert got[0].proposed_action == "dig deeper"
    assert got[0].source_chunks[0].source == "arxiv.org"


def test_store_escalation_status_filter_and_update(migrated_paths) -> None:
    store = _store(migrated_paths)
    e = store.add_escalation(Escalation(kind=ReflectionKind.STALE_POSITION,
                                        body="re-verify", priority=EscalationPriority.HIGH))
    assert len(store.list_escalations(status=EscalationStatus.OPEN)) == 1
    assert store.update_escalation_status(e.id, EscalationStatus.RESOLVED) is True
    assert store.list_escalations(status=EscalationStatus.OPEN) == []
    assert len(store.list_escalations(status=EscalationStatus.RESOLVED)) == 1


# --- engine tick -----------------------------------------------------------


def test_tick_commits_capped_reflections(migrated_paths) -> None:
    store = _store(migrated_paths)
    producer = lambda: [_refl(f"r{i}") for i in range(10)]  # noqa: E731
    engine = SubconsciousEngine(store, reflection_producers=(producer,))
    outcome = engine.tick()
    assert outcome.result is TickResult.COMMITTED
    assert outcome.reflections_committed == MAX_REFLECTIONS_PER_TICK
    assert len(store.list_reflections()) == MAX_REFLECTIONS_PER_TICK


def test_tick_superseded_discards(migrated_paths) -> None:
    store = _store(migrated_paths)
    guard = GenerationGuard()

    def producer():
        guard.begin()  # a newer tick starts while we gather → supersede
        return [_refl("late")]

    engine = SubconsciousEngine(store, guard=guard, reflection_producers=(producer,))
    outcome = engine.tick()
    assert outcome.result is TickResult.SUPERSEDED
    assert store.list_reflections() == []  # nothing committed


def test_stale_position_producer_emits_escalation(migrated_paths) -> None:
    db = kinds_for(migrated_paths)["positions"]
    record_position(db, claim="Was X approved by 2020?", probability=0.7,
                    resolve_by=PAST)
    record_position(db, claim="future claim", probability=0.6)  # not due
    escalations = stale_position_escalations(db)
    assert len(escalations) == 1
    assert escalations[0].kind is ReflectionKind.STALE_POSITION
    assert escalations[0].source_refs == ["position:1"]


def test_act_on_reflection_spawns_fresh_job() -> None:
    spawned: list[str] = []

    def spawn(question: str) -> str:
        spawned.append(question)
        return "job-123"

    r = _refl("two sources now disagree", proposed_action="re-verify Position 14")
    job_id = act_on_reflection(r, spawn=spawn)
    assert job_id == "job-123"
    assert "two sources now disagree" in spawned[0]
    assert "re-verify Position 14" in spawned[0]  # body + action seeded
