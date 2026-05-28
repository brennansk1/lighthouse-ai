"""Effector: drains the intents outbox, applies side effects, retries with
exponential backoff (1, 4, 16, 64, 256s — then dead) per design §25.6.

The Effector is normally a child process of the supervisor; for testability
it's a small class with ``tick()`` (single iteration) and ``run_until_empty``.
A real long-running loop is ``run_forever`` with a 250ms sleep.

Target plugins are registered via :func:`register_target` — each takes an
:class:`Intent` and applies it idempotently. Failures raise; the effector
catches and counts attempts.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

from .intents import Intent, claim_one, mark_applied, mark_failed

log = logging.getLogger(__name__)

#: Per §25.6 — delays after the *first* failed attempt.
RETRY_DELAYS_S: tuple[int, ...] = (1, 4, 16, 64, 256)
#: Total apply attempts allowed; the last failure moves the intent to dead.
MAX_ATTEMPTS = len(RETRY_DELAYS_S) + 1  # 6
#: Kept for back-compat with older callers.
DEAD_AFTER_ATTEMPTS = MAX_ATTEMPTS

TargetApplier = Callable[[Intent], None]

_TARGETS: dict[str, TargetApplier] = {}


def register_target(name: str, applier: TargetApplier) -> None:
    _TARGETS[name] = applier


def unregister_target(name: str) -> None:
    _TARGETS.pop(name, None)


def clear_targets() -> None:
    _TARGETS.clear()


def known_targets() -> tuple[str, ...]:
    return tuple(_TARGETS.keys())


class Effector:
    """One Effector instance per DB. Single-writer per target by default."""

    def __init__(self, db_path: Path, *, poll_interval_s: float = 0.25):
        self.db_path = db_path
        self.poll_interval_s = poll_interval_s
        self._stop = threading.Event()

    # --- single iteration ---
    def tick(self) -> str:
        """Try to claim and apply one intent. Returns a short status code:

        ``"empty"`` — nothing to claim.
        ``"applied"`` — one intent applied successfully.
        ``"retry"`` — apply failed, intent re-queued.
        ``"dead"`` — apply failed too many times, moved to dead_intents.
        ``"unknown_target"`` — no applier registered; intent left re-queued.
        """
        intent = claim_one(self.db_path)
        if intent is None:
            return "empty"
        applier = _TARGETS.get(intent.target)
        if applier is None:
            mark_failed(self.db_path, intent.id, f"no applier for target {intent.target!r}")
            return "unknown_target"
        try:
            applier(intent)
        except Exception as exc:  # noqa: BLE001 — effector must catch
            # ``intent.attempts`` is the post-bump count from claim_one.
            should_die = intent.attempts >= MAX_ATTEMPTS
            mark_failed(self.db_path, intent.id, repr(exc), dead=should_die)
            return "dead" if should_die else "retry"
        mark_applied(self.db_path, intent.id)
        return "applied"

    # --- drain until empty (for tests) ---
    def run_until_empty(self, *, max_iters: int = 10_000) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _ in range(max_iters):
            status = self.tick()
            counts[status] = counts.get(status, 0) + 1
            if status == "empty":
                break
        return counts

    # --- long-running loop (the real supervisor child) ---
    def run_forever(self) -> None:  # pragma: no cover - exercised in tests via stop_event
        while not self._stop.is_set():
            status = self.tick()
            if status == "empty":
                time.sleep(self.poll_interval_s)

    def stop(self) -> None:
        self._stop.set()
