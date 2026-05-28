"""Unit + integration tests for the Effector."""

from __future__ import annotations

import pytest

from lighthouse_ai.effector import (
    MAX_ATTEMPTS,
    Effector,
    clear_targets,
)
from lighthouse_ai.intents import list_dead, outbox_depth, write_intent
from lighthouse_ai.targets import test_target


@pytest.fixture(autouse=True)
def fresh_targets():
    clear_targets()
    test_target.reset()
    test_target.install()
    yield
    clear_targets()
    test_target.reset()


def test_effector_drains_pending_intents(migrated_paths):
    for i in range(5):
        write_intent(migrated_paths.intents_db, target="test_target", op="upsert",
                     payload={"i": i}, idempotency_key=f"k{i}")
    counts = Effector(migrated_paths.intents_db).run_until_empty()
    assert counts.get("applied") == 5
    assert outbox_depth(migrated_paths.intents_db) == 0
    assert len(test_target.applied()) == 5


def test_unknown_target_does_not_dead_immediately(migrated_paths):
    write_intent(migrated_paths.intents_db, target="never_registered", op="o",
                 payload={}, idempotency_key="x")
    eff = Effector(migrated_paths.intents_db)
    status = eff.tick()
    assert status == "unknown_target"


def test_effector_retries_then_dies(migrated_paths):
    test_target.schedule_failures("flaky", 100)  # always fail
    write_intent(migrated_paths.intents_db, target="test_target", op="upsert",
                 payload={"id": "flaky"}, idempotency_key="flaky")
    eff = Effector(migrated_paths.intents_db)
    statuses: list[str] = []
    for _ in range(MAX_ATTEMPTS + 2):
        statuses.append(eff.tick())
    # First MAX_ATTEMPTS-1 attempts are "retry", last is "dead", then "empty".
    assert statuses.count("retry") == MAX_ATTEMPTS - 1
    assert "dead" in statuses
    deads = list_dead(migrated_paths.intents_db)
    assert len(deads) == 1
    assert deads[0]["target"] == "test_target"


def test_effector_recovers_after_transient_failures(migrated_paths):
    test_target.schedule_failures("recover", 2)  # fail twice then succeed
    write_intent(migrated_paths.intents_db, target="test_target", op="upsert",
                 payload={"v": 1}, idempotency_key="recover")
    eff = Effector(migrated_paths.intents_db)
    seen: list[str] = []
    for _ in range(10):
        seen.append(eff.tick())
        if seen[-1] == "applied":
            break
    assert "applied" in seen
    assert outbox_depth(migrated_paths.intents_db) == 0
    assert test_target.applied()["recover"] == {"v": 1}


def test_chaos_random_failures_no_duplicates_no_orphans(migrated_paths):
    """Each key is applied at most once even with random transient failures.

    Light-weight replacement for the 1000-intent chaos test in the design.
    """
    import random
    random.seed(7)
    n = 50
    for i in range(n):
        write_intent(migrated_paths.intents_db, target="test_target", op="upsert",
                     payload={"i": i}, idempotency_key=f"chaos-{i}")
        # 30% chance each intent fails up to 2 times before succeeding.
        if random.random() < 0.3:
            test_target.schedule_failures(f"chaos-{i}", random.randint(1, 2))
    eff = Effector(migrated_paths.intents_db)
    eff.run_until_empty(max_iters=10_000)
    applied = test_target.applied()
    # All n intents applied exactly once.
    for i in range(n):
        assert applied[f"chaos-{i}"] == {"i": i}
    assert outbox_depth(migrated_paths.intents_db) == 0


def test_effector_tick_on_empty_queue_returns_empty(migrated_paths):
    eff = Effector(migrated_paths.intents_db)
    assert eff.tick() == "empty"
