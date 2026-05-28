"""Unit tests for the saga compensator registry."""

from __future__ import annotations

from lighthouse_ai.intents import Intent
from lighthouse_ai.sagas import clear, compensate, known_targets, register


def _make_intent() -> Intent:
    return Intent(id=1, idempotency_key="k", target="X", op="o", payload={},
                  status="applied", attempts=1)


def test_register_and_compensate_runs_callback():
    clear()
    fired = []
    register("X", lambda i: fired.append(i.idempotency_key))
    compensate(_make_intent())
    assert fired == ["k"]


def test_compensate_unknown_target_is_noop():
    clear()
    compensate(_make_intent())  # no exception


def test_register_overwrites():
    clear()
    register("X", lambda i: None)
    fired = []
    register("X", lambda i: fired.append("v2"))
    compensate(_make_intent())
    assert fired == ["v2"]


def test_known_targets_lists_registrations():
    clear()
    register("A", lambda i: None)
    register("B", lambda i: None)
    assert set(known_targets()) == {"A", "B"}
