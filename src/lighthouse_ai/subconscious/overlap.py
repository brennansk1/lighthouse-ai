"""Tick overlap guard — generation-counter cancellation (OpenHuman §4).

Scheduled background passes (calibration auto-resolver, Monitor sync, subconscious
ticks) can run longer than their interval and collide with the next scheduled run.
The outbox/effector handles cross-store consistency, but nothing stops a slow tick
from racing the next one and double-committing.

Each tick claims a monotonic **generation**. Before committing, it checks whether a
newer tick has started; if so, the stale tick discards its results instead of
writing. Pair with a per-task ``in_progress`` → ``cancelled`` status so a crash
mid-tick is recoverable by the existing startup recovery scan.
"""

from __future__ import annotations

import itertools
import threading
from enum import Enum

__all__ = ["GenerationGuard", "TickResult"]


class TickResult(str, Enum):
    COMMITTED = "committed"
    SUPERSEDED = "superseded"  # a newer tick started; this tick's results discarded


class GenerationGuard:
    """Monotonic generation counter shared across a recurring task's ticks.

    ``begin()`` claims the next generation and marks it current. A tick holds its
    own generation and asks ``is_current(gen)`` before committing — once a newer
    tick has called ``begin()``, the older generation is no longer current and
    must discard its writes. Thread-safe.
    """

    def __init__(self) -> None:
        self._counter = itertools.count(1)
        self._current = 0
        self._lock = threading.Lock()

    def begin(self) -> int:
        with self._lock:
            gen = next(self._counter)
            self._current = gen
            return gen

    @property
    def current(self) -> int:
        with self._lock:
            return self._current

    def is_current(self, gen: int) -> bool:
        with self._lock:
            return self._current == gen
