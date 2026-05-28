"""Unit tests for the intents outbox."""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given, settings, strategies as st

from lighthouse_ai.intents import (
    claim_one,
    derive_idempotency_key,
    derive_point_uuid,
    list_dead,
    mark_applied,
    mark_failed,
    outbox_depth,
    write_intent,
)


def test_write_intent_returns_row_id(migrated_paths):
    rid = write_intent(migrated_paths.intents_db, target="t", op="o",
                       payload={"v": 1}, idempotency_key="k1")
    assert isinstance(rid, int)
    assert rid >= 1


def test_write_intent_is_idempotent_by_key(migrated_paths):
    a = write_intent(migrated_paths.intents_db, target="t", op="o",
                     payload={"v": 1}, idempotency_key="k-dup")
    b = write_intent(migrated_paths.intents_db, target="t", op="o",
                     payload={"v": 2}, idempotency_key="k-dup")
    assert a == b
    assert outbox_depth(migrated_paths.intents_db) == 1


def test_claim_one_marks_in_flight_and_returns_payload(migrated_paths):
    write_intent(migrated_paths.intents_db, target="t", op="o",
                 payload={"v": 7}, idempotency_key="kclaim")
    intent = claim_one(migrated_paths.intents_db)
    assert intent is not None
    assert intent.payload == {"v": 7}
    assert intent.attempts == 1
    # Claiming again returns nothing (already in_flight, not pending).
    assert claim_one(migrated_paths.intents_db) is None


def test_claim_one_respects_target_filter(migrated_paths):
    write_intent(migrated_paths.intents_db, target="A", op="o", payload={},
                 idempotency_key="a1")
    write_intent(migrated_paths.intents_db, target="B", op="o", payload={},
                 idempotency_key="b1")
    b = claim_one(migrated_paths.intents_db, target="B")
    assert b is not None
    assert b.target == "B"


def test_mark_applied_clears_from_outbox_depth(migrated_paths):
    write_intent(migrated_paths.intents_db, target="t", op="o", payload={},
                 idempotency_key="k-applied")
    intent = claim_one(migrated_paths.intents_db)
    assert intent
    mark_applied(migrated_paths.intents_db, intent.id)
    assert outbox_depth(migrated_paths.intents_db) == 0


def test_mark_failed_requeues_by_default(migrated_paths):
    write_intent(migrated_paths.intents_db, target="t", op="o", payload={},
                 idempotency_key="k-fail")
    intent = claim_one(migrated_paths.intents_db)
    mark_failed(migrated_paths.intents_db, intent.id, "nope")
    # Re-queued → claimable again.
    again = claim_one(migrated_paths.intents_db)
    assert again is not None
    assert again.id == intent.id
    assert again.attempts == 2


def test_mark_failed_dead_moves_to_dead_intents(migrated_paths):
    write_intent(migrated_paths.intents_db, target="t", op="o", payload={"x": 1},
                 idempotency_key="k-dead")
    intent = claim_one(migrated_paths.intents_db)
    mark_failed(migrated_paths.intents_db, intent.id, "fatal", dead=True)
    deads = list_dead(migrated_paths.intents_db)
    assert len(deads) == 1
    assert deads[0]["original_id"] == intent.id
    assert deads[0]["payload"] == {"x": 1}
    # And not in outbox depth anymore.
    assert outbox_depth(migrated_paths.intents_db) == 0


def test_derive_idempotency_key_matches_design_format():
    assert derive_idempotency_key("j", "n", "w") == "j:n:w"


def test_derive_point_uuid_is_stable_and_valid():
    a = derive_point_uuid("k")
    b = derive_point_uuid("k")
    assert a == b
    uuid.UUID(a)  # parses


def test_derive_point_uuid_differs_per_key():
    assert derive_point_uuid("a") != derive_point_uuid("b")


@settings(max_examples=50, deadline=None)
@given(st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=20, unique=True))
def test_property_writing_n_unique_keys_produces_n_rows(keys):
    """Outbox depth equals number of unique idempotency keys written."""
    import tempfile
    from lighthouse_ai.paths import make_paths
    from lighthouse_ai.schema import kinds_for, migrate_all
    with tempfile.TemporaryDirectory() as td:
        paths = make_paths(td)
        paths.ensure()
        migrate_all(kinds_for(paths))
        for k in keys:
            write_intent(paths.intents_db, target="t", op="o",
                         payload={}, idempotency_key=k)
        assert outbox_depth(paths.intents_db) == len(keys)


@settings(max_examples=20, deadline=None)
@given(st.text(min_size=1, max_size=20), st.integers(min_value=1, max_value=10))
def test_property_writing_same_key_n_times_yields_one_row(key, n):
    import tempfile
    from lighthouse_ai.paths import make_paths
    from lighthouse_ai.schema import kinds_for, migrate_all
    with tempfile.TemporaryDirectory() as td:
        paths = make_paths(td)
        paths.ensure()
        migrate_all(kinds_for(paths))
        ids = [write_intent(paths.intents_db, target="t", op="o",
                            payload={"i": i}, idempotency_key=key) for i in range(n)]
        assert len(set(ids)) == 1
        assert outbox_depth(paths.intents_db) == 1
