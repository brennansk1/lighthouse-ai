"""Unit tests for the cross-process, RAM-aware Ollama admission queue.

The queue reserves the *new* resident RAM a call adds (``need_gb``) against
live-available memory, guarded by a brief platform-native file mutex. A
zero-need call (model already hot, or an SSD-paging MoE) is admitted instantly
with no locking; a positive-need call is admitted only while the running total
of reservations plus its own need plus a safety margin still fits.
"""

from __future__ import annotations

import json
import threading
import time

from lighthouse_ai.governor import ollama_queue as oq
from lighthouse_ai.governor.ollama_queue import AdmissionConfig, ollama_slot


def _ledger(lock):
    return oq._ledger_path(lock)


def test_zero_need_admits_immediately_without_locking(tmp_path):
    """A resident/MoE call (need=0) is admitted free — no ledger is even touched."""
    lock = tmp_path / "ollama.lock"
    with ollama_slot(lock, "m", need_gb_fn=lambda _m: 0.0) as admitted:
        assert admitted is True
    assert not lock.exists()
    assert not _ledger(lock).exists()


def test_admits_when_reservation_fits_available(tmp_path):
    lock = tmp_path / "ollama.lock"
    cfg = AdmissionConfig(enabled=True, margin_gb=1.0)
    with ollama_slot(lock, "m", need_gb_fn=lambda _m: 4.0, cfg=cfg,
                     available_gb_fn=lambda: 100.0) as admitted:
        assert admitted is True
        # While held, our reservation is recorded in the ledger.
        entries = json.loads(_ledger(lock).read_text())
        assert len(entries) == 1
        assert entries[0]["gb"] == 4.0
    # Released on exit.
    assert json.loads(_ledger(lock).read_text()) == []


def test_falls_back_when_never_enough_ram(tmp_path):
    lock = tmp_path / "ollama.lock"
    slept: list[float] = []
    cfg = AdmissionConfig(enabled=True, wait_timeout_s=1.0, poll_s=0.25)
    with ollama_slot(lock, "m", need_gb_fn=lambda _m: 50.0, cfg=cfg,
                     available_gb_fn=lambda: 8.0, sleep=slept.append) as admitted:
        assert admitted is False
    # Polled a few times before giving up, never hung.
    assert len(slept) >= 1
    # No leaked reservation (never admitted → nothing was ever booked).
    assert not _ledger(lock).exists()


def test_admits_once_headroom_appears(tmp_path):
    lock = tmp_path / "ollama.lock"
    calls = {"n": 0}

    def available() -> float:
        calls["n"] += 1
        return 100.0 if calls["n"] >= 3 else 1.0  # RAM frees up on 3rd probe

    cfg = AdmissionConfig(enabled=True, wait_timeout_s=10.0, poll_s=0.01)
    with ollama_slot(lock, "m", need_gb_fn=lambda _m: 10.0, cfg=cfg,
                     available_gb_fn=available, sleep=lambda _s: None) as admitted:
        assert admitted is True
    assert calls["n"] == 3


def test_existing_reservation_counts_against_budget(tmp_path):
    """A second cold load is refused while the first reservation still books RAM."""
    lock = tmp_path / "ollama.lock"
    cfg = AdmissionConfig(enabled=True, wait_timeout_s=0.2, poll_s=0.05, margin_gb=1.0)
    with ollama_slot(lock, "a", need_gb_fn=lambda _m: 10.0, cfg=cfg,
                     available_gb_fn=lambda: 14.0):
        # 10 (reserved) + 10 (need) + 1 margin = 21 > 14 → must time out.
        with ollama_slot(lock, "b", need_gb_fn=lambda _m: 10.0, cfg=cfg,
                         available_gb_fn=lambda: 14.0,
                         sleep=lambda _s: None) as second:
            assert second is False


def test_disabled_skips_ledger_but_still_checks_ram(tmp_path):
    lock = tmp_path / "ollama.lock"
    cfg = AdmissionConfig(enabled=False, margin_gb=1.0)
    with ollama_slot(lock, "m", need_gb_fn=lambda _m: 4.0, cfg=cfg,
                     available_gb_fn=lambda: 100.0) as admitted:
        assert admitted is True
    # No ledger/lock files when the queue is disabled.
    assert not _ledger(lock).exists()
    with ollama_slot(lock, "m", need_gb_fn=lambda _m: 50.0, cfg=cfg,
                     available_gb_fn=lambda: 8.0) as admitted:
        assert admitted is False


def test_no_file_lock_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(oq, "fcntl", None)
    monkeypatch.setattr(oq, "msvcrt", None)
    lock = tmp_path / "ollama.lock"
    with ollama_slot(lock, "m", need_gb_fn=lambda _m: 4.0,
                     available_gb_fn=lambda: 100.0) as admitted:
        assert admitted is True
    assert not _ledger(lock).exists()


def test_dead_pid_reservations_are_pruned(tmp_path, monkeypatch):
    """A reservation from a crashed process must not permanently book RAM."""
    lock = tmp_path / "ollama.lock"
    ledger = _ledger(lock)
    ledger.write_text(json.dumps([{"rid": "ghost", "pid": 999999, "gb": 99.0}]))
    monkeypatch.setattr(oq, "_pid_alive", lambda pid: pid == __import__("os").getpid())
    cfg = AdmissionConfig(enabled=True, margin_gb=1.0)
    # Ghost's 99 GB would block us, but it's pruned because its PID is dead.
    with ollama_slot(lock, "m", need_gb_fn=lambda _m: 4.0, cfg=cfg,
                     available_gb_fn=lambda: 100.0) as admitted:
        assert admitted is True


def test_concurrent_cold_loads_respect_budget(tmp_path):
    """Many threads each needing RAM never overshoot the live budget at once."""
    lock = tmp_path / "ollama.lock"
    cfg = AdmissionConfig(enabled=True, wait_timeout_s=5.0, poll_s=0.01, margin_gb=1.0)
    # Available 25 GB, each call needs 10 → at most 2 can hold concurrently
    # (2*10 + 1 margin = 21 <= 25; a 3rd would be 31 > 25).
    state = {"cur": 0, "max": 0}
    guard = threading.Lock()

    def worker() -> None:
        with ollama_slot(lock, "m", need_gb_fn=lambda _m: 10.0, cfg=cfg,
                         available_gb_fn=lambda: 25.0) as admitted:
            if not admitted:
                return
            with guard:
                state["cur"] += 1
                state["max"] = max(state["max"], state["cur"])
            time.sleep(0.05)
            with guard:
                state["cur"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Strict OOM guard: reservations never let more than 2 cold loads coexist.
    assert state["max"] <= 2
    assert state["max"] >= 1  # and we did make progress, not deadlock


def test_from_env_disable(monkeypatch):
    monkeypatch.setenv("LIGHTHOUSE_OLLAMA_QUEUE", "off")
    assert AdmissionConfig.from_env().enabled is False
    monkeypatch.setenv("LIGHTHOUSE_OLLAMA_QUEUE", "1")
    assert AdmissionConfig.from_env().enabled is True
    monkeypatch.delenv("LIGHTHOUSE_OLLAMA_QUEUE", raising=False)
    assert AdmissionConfig.from_env().enabled is True


def test_from_env_timeout_override(monkeypatch):
    monkeypatch.setenv("LIGHTHOUSE_OLLAMA_QUEUE_TIMEOUT", "2.5")
    assert AdmissionConfig.from_env().wait_timeout_s == 2.5
    monkeypatch.setenv("LIGHTHOUSE_OLLAMA_QUEUE_TIMEOUT", "garbage")
    # Invalid value ignored → default retained.
    assert AdmissionConfig.from_env().wait_timeout_s == AdmissionConfig().wait_timeout_s
