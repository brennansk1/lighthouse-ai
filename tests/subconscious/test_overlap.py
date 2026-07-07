"""Tests for the tick overlap guard (OpenHuman §4 integration)."""

from __future__ import annotations

import threading
from pathlib import Path

from lighthouse_ai.schema import kinds_for
from lighthouse_ai.subconscious.overlap import GenerationGuard, TickResult
from lighthouse_ai.verification.positions import record_position
from lighthouse_ai.verification.resolver import run_resolver_pass

PAST = "2000-01-01T00:00:00"


# --- primitive --------------------------------------------------------------


def test_begin_is_monotonic() -> None:
    g = GenerationGuard()
    a = g.begin()
    b = g.begin()
    assert b > a


def test_latest_generation_is_current() -> None:
    g = GenerationGuard()
    first = g.begin()
    second = g.begin()
    assert g.is_current(second) is True
    assert g.is_current(first) is False  # superseded


def test_current_property_tracks_latest() -> None:
    g = GenerationGuard()
    g.begin()
    latest = g.begin()
    assert g.current == latest


def test_begin_is_thread_safe_unique() -> None:
    g = GenerationGuard()
    seen: list[int] = []
    lock = threading.Lock()

    def worker():
        gen = g.begin()
        with lock:
            seen.append(gen)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(seen)) == 50  # no duplicate generations handed out


def test_tickresult_values() -> None:
    assert TickResult.COMMITTED != TickResult.SUPERSEDED


# --- resolver integration ---------------------------------------------------


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _ResolvingGateway:
    """Always resolves TRUE with high confidence."""

    def complete(self, role, prompt, **kw):
        return _FakeResp("TRUE: 0.95 — confirmed by record")


class _SupersedingGateway(_ResolvingGateway):
    """Simulates a newer tick starting mid-pass by bumping the guard."""

    def __init__(self, guard: GenerationGuard) -> None:
        self._guard = guard

    def complete(self, role, prompt, **kw):
        self._guard.begin()  # a newer generation claims the counter
        return super().complete(role, prompt, **kw)


# Evidence retriever for the new resolver contract: supplies grounded evidence so
# the guard's commit/discard logic is exercised (the resolver no longer self-grades).
def _RETRIEVER(claim, criterion, as_of):
    return ("Registry shows drug X received approval in 2019.", "registry-1")


def _seed_position(paths) -> Path:
    db = kinds_for(paths)["positions"]
    record_position(
        db,
        claim="Was drug X approved by 2020?",  # machine-resolvable
        probability=0.75,
        resolve_by=PAST,
        resolution_criterion="An official approval record exists",
    )
    return db


def _outcome(db) -> object:
    from lighthouse_ai.persistence import open_db

    conn = open_db(db)
    try:
        return conn.execute("SELECT outcome FROM positions LIMIT 1").fetchone()[0]
    finally:
        conn.close()


def test_resolver_commits_when_not_superseded(migrated_paths) -> None:
    db = _seed_position(migrated_paths)
    guard = GenerationGuard()
    results = run_resolver_pass(db, gateway=_ResolvingGateway(), retriever=_RETRIEVER, guard=guard)
    assert results and results[0].auto_resolved
    assert _outcome(db) == 1  # committed


def test_resolver_discards_when_superseded(migrated_paths) -> None:
    db = _seed_position(migrated_paths)
    guard = GenerationGuard()
    gw = _SupersedingGateway(guard)
    results = run_resolver_pass(db, gateway=gw, retriever=_RETRIEVER, guard=guard)
    # The pass still researched the position, but a newer generation started, so
    # the write is discarded — the outcome stays NULL.
    assert results and results[0].auto_resolved
    assert _outcome(db) is None


def test_resolver_without_guard_still_commits(migrated_paths) -> None:
    db = _seed_position(migrated_paths)
    results = run_resolver_pass(db, gateway=_ResolvingGateway(), retriever=_RETRIEVER)
    assert results and results[0].auto_resolved
    assert _outcome(db) == 1
