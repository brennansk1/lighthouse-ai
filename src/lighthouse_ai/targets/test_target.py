"""In-memory test target — proves the effector framework end-to-end.

Captures all applied intents in a per-target dict so tests can assert on
ordering, idempotency, and replay behavior.
"""

from __future__ import annotations

from threading import Lock
from typing import Any

from ..effector import register_target, unregister_target
from ..intents import Intent
from ..sagas import register as register_compensator

NAME = "test_target"

_LOCK = Lock()
_APPLIED: dict[str, dict[str, Any]] = {}
_COMPENSATED: set[str] = set()
_FAILURES_REMAINING: dict[str, int] = {}


def applier(intent: Intent) -> None:
    """Apply by key. If a failure budget remains, decrement and raise."""
    with _LOCK:
        remaining = _FAILURES_REMAINING.get(intent.idempotency_key, 0)
        if remaining > 0:
            _FAILURES_REMAINING[intent.idempotency_key] = remaining - 1
            raise RuntimeError(f"simulated failure (remaining={remaining-1})")
        _APPLIED[intent.idempotency_key] = dict(intent.payload)


def compensator(intent: Intent) -> None:
    with _LOCK:
        _APPLIED.pop(intent.idempotency_key, None)
        _COMPENSATED.add(intent.idempotency_key)


def applied() -> dict[str, dict[str, Any]]:
    with _LOCK:
        return dict(_APPLIED)


def was_compensated(key: str) -> bool:
    with _LOCK:
        return key in _COMPENSATED


def schedule_failures(key: str, n: int) -> None:
    """Make the next ``n`` applies of ``key`` fail before succeeding."""
    with _LOCK:
        _FAILURES_REMAINING[key] = n


def reset() -> None:
    with _LOCK:
        _APPLIED.clear()
        _COMPENSATED.clear()
        _FAILURES_REMAINING.clear()


def install() -> None:
    register_target(NAME, applier)
    register_compensator(NAME, compensator)


def uninstall() -> None:
    unregister_target(NAME)
