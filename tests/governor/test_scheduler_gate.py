"""Tests for the Scheduler Gate (OpenHuman §1 integration).

Covers env-override parsing, the policy truth table, totality of
``current_policy``, and the cooperative permit's throttle/pause/concurrency
behaviour — all with injected signals and fake sleeps so nothing touches real
host hardware or wall-clock time.
"""

from __future__ import annotations

import threading
import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lighthouse_ai.governor.scheduler_gate import (
    PauseReason,
    Policy,
    SchedulerGate,
    SchedulerGateConfig,
    Signals,
    _env_bool,
    _env_float,
    current_policy,
    sample_signals,
)

CFG = SchedulerGateConfig()  # defaults: floor 80%, ceiling 70%


def _sig(*, ac=True, batt=None, cpu=10.0, server=False) -> Signals:
    return Signals(on_ac_power=ac, battery_charge=batt, cpu_usage_pct=cpu,
                   server_mode=server)


# --- env override parsing (truthy / falsy / garbage→None) ------------------


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("YES", True), ("On", True),
    ("0", False), ("false", False), ("no", False), ("OFF", False),
    ("maybe", None), ("", None), ("  ", None), ("2", None),
])
def test_env_bool_parsing(monkeypatch, raw, expected) -> None:
    monkeypatch.setenv("LIGHTHOUSE_TEST_BOOL", raw)
    assert _env_bool("LIGHTHOUSE_TEST_BOOL") is expected


def test_env_bool_absent_is_none(monkeypatch) -> None:
    monkeypatch.delenv("LIGHTHOUSE_TEST_BOOL", raising=False)
    assert _env_bool("LIGHTHOUSE_TEST_BOOL") is None


@pytest.mark.parametrize("raw,expected", [
    ("0.8", 0.8), ("80", 80.0), ("  0.5 ", 0.5), ("garbage", None), ("", None),
])
def test_env_float_parsing(monkeypatch, raw, expected) -> None:
    monkeypatch.setenv("LIGHTHOUSE_TEST_FLOAT", raw)
    assert _env_float("LIGHTHOUSE_TEST_FLOAT") == expected


def test_env_override_wins_over_probe(monkeypatch) -> None:
    monkeypatch.setenv("LIGHTHOUSE_ON_AC_POWER", "false")
    monkeypatch.setenv("LIGHTHOUSE_BATTERY_CHARGE", "0.5")
    monkeypatch.setenv("LIGHTHOUSE_CPU_USAGE", "12")
    monkeypatch.delenv("LIGHTHOUSE_SERVER_MODE", raising=False)
    sig = sample_signals(CFG)
    assert sig.on_ac_power is False
    assert sig.battery_charge == 0.5
    assert sig.cpu_usage_pct == 12.0


def test_garbage_env_falls_through_to_probe(monkeypatch) -> None:
    # Garbage CPU value must not coerce to 0; the real probe answers instead.
    monkeypatch.setenv("LIGHTHOUSE_CPU_USAGE", "not-a-number")
    monkeypatch.setenv("LIGHTHOUSE_ON_AC_POWER", "true")
    monkeypatch.setenv("LIGHTHOUSE_BATTERY_CHARGE", "1.0")
    sig = sample_signals(CFG)
    assert 0.0 <= sig.cpu_usage_pct <= 100.0  # came from psutil, not the garbage


# --- policy truth table ----------------------------------------------------


def test_mode_off_is_paused_user_disabled() -> None:
    cfg = SchedulerGateConfig(mode="off")
    assert current_policy(cfg, _sig()) == (Policy.PAUSED, PauseReason.USER_DISABLED)


def test_mode_aggressive_bypasses() -> None:
    cfg = SchedulerGateConfig(mode="aggressive")
    # Even on a drained battery with pegged CPU, aggressive bypasses.
    assert current_policy(cfg, _sig(ac=False, batt=0.1, cpu=99))[0] == Policy.AGGRESSIVE


def test_server_mode_bypasses() -> None:
    assert current_policy(CFG, _sig(server=True, cpu=99))[0] == Policy.AGGRESSIVE


@pytest.mark.parametrize("batt,expected", [
    (0.79, Policy.THROTTLED),  # below floor
    (0.80, Policy.NORMAL),     # at floor → not throttled
    (0.81, Policy.NORMAL),     # above floor
])
def test_battery_floor_boundary(batt, expected) -> None:
    policy, reason = current_policy(CFG, _sig(ac=False, batt=batt, cpu=10))
    assert policy == expected
    if expected is Policy.THROTTLED:
        assert reason is PauseReason.ON_BATTERY


@pytest.mark.parametrize("cpu,expected", [
    (69.0, Policy.NORMAL),
    (70.0, Policy.NORMAL),     # at ceiling → not throttled
    (71.0, Policy.THROTTLED),  # above ceiling
])
def test_cpu_ceiling_boundary(cpu, expected) -> None:
    policy, reason = current_policy(CFG, _sig(ac=True, cpu=cpu))
    assert policy == expected
    if expected is Policy.THROTTLED:
        assert reason is PauseReason.CPU_PRESSURE


def test_on_ac_ignores_battery_floor() -> None:
    # Plugged in with a low battery reading should not throttle on battery.
    assert current_policy(CFG, _sig(ac=True, batt=0.1, cpu=10))[0] == Policy.NORMAL


# --- totality (property) ---------------------------------------------------


@given(
    ac=st.booleans(),
    batt=st.one_of(st.none(), st.floats(min_value=0, max_value=1)),
    cpu=st.floats(min_value=0, max_value=100),
    server=st.booleans(),
    mode=st.sampled_from(["auto", "aggressive", "off"]),
)
def test_current_policy_is_total(ac, batt, cpu, server, mode) -> None:
    cfg = SchedulerGateConfig(mode=mode)
    policy, reason = current_policy(cfg, _sig(ac=ac, batt=batt, cpu=cpu, server=server))
    assert isinstance(policy, Policy)
    assert reason is None or isinstance(reason, PauseReason)


# --- cooperative permit behaviour ------------------------------------------


def test_normal_acquires_immediately_without_sleep() -> None:
    slept: list[float] = []
    gate = SchedulerGate(CFG, signals_provider=lambda: _sig(cpu=10),
                         sleep=slept.append)
    with gate.permit():
        pass
    assert slept == []  # NORMAL never sleeps


def test_throttled_sleeps_backoff_before_permit() -> None:
    slept: list[float] = []
    gate = SchedulerGate(SchedulerGateConfig(throttled_backoff_ms=2000),
                         signals_provider=lambda: _sig(cpu=99),
                         sleep=slept.append)
    with gate.permit():
        pass
    assert slept == [2.0]  # throttled_backoff_ms / 1000


def test_paused_repolls_then_resumes_on_flip() -> None:
    # First poll PAUSED, then flips to NORMAL; permit resumes after exactly one
    # paused_poll sleep.
    flips = {"n": 0}
    gate = SchedulerGate(SchedulerGateConfig(paused_poll_ms=5000),
                         signals_provider=lambda: _sig(cpu=10),
                         sleep=lambda s: None)

    seq = [(Policy.PAUSED, PauseReason.USER_DISABLED), (Policy.NORMAL, None)]
    sleeps: list[float] = []

    def sleep(s):
        sleeps.append(s)
        flips["n"] += 1

    gate._sleep = sleep
    gate.policy = lambda: seq[min(flips["n"], len(seq) - 1)]  # type: ignore[method-assign]
    with gate.permit():
        pass
    assert sleeps == [5.0]  # one paused_poll re-poll, then resumed


def test_max_concurrent_one_serialises() -> None:
    # With one slot, two threads cannot hold permits simultaneously.
    gate = SchedulerGate(SchedulerGateConfig(max_concurrent_llm=1),
                         signals_provider=lambda: _sig(cpu=10),
                         sleep=lambda s: None)
    concurrent = 0
    max_seen = 0
    lock = threading.Lock()
    started = threading.Event()

    def worker():
        nonlocal concurrent, max_seen
        with gate.permit():
            with lock:
                concurrent += 1
                max_seen = max(max_seen, concurrent)
            started.set()
            time.sleep(0.02)
            with lock:
                concurrent -= 1

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)
    assert max_seen == 1


def test_throttled_serialises_even_with_multi_slot_config() -> None:
    """THROTTLED policy must force concurrency to 1 even when max_concurrent_llm > 1.

    Regression test for the audit finding: previously THROTTLED only slept the
    backoff but still acquired one of the N semaphore slots, so N calls could
    run concurrently under THROTTLED on T3+ configs.
    """
    # max_concurrent_llm=4 (T3+ tier) but policy is THROTTLED (high CPU).
    gate = SchedulerGate(
        SchedulerGateConfig(max_concurrent_llm=4, throttled_backoff_ms=0),
        signals_provider=lambda: _sig(cpu=99),  # forces THROTTLED
        sleep=lambda s: None,
    )
    concurrent = 0
    max_seen = 0
    results_lock = threading.Lock()
    ready = threading.Barrier(2, timeout=2)

    def worker():
        nonlocal concurrent, max_seen
        with gate.permit():
            with results_lock:
                concurrent += 1
                max_seen = max(max_seen, concurrent)
            # Rendezvous: if both are inside simultaneously, max_seen will be 2.
            try:
                ready.wait()
            except threading.BrokenBarrierError:
                pass
            with results_lock:
                concurrent -= 1

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)
    # THROTTLED must serialise: max concurrent inside permit() is 1
    assert max_seen == 1, (
        f"THROTTLED with max_concurrent_llm=4 allowed {max_seen} concurrent holders"
    )


def test_two_slots_allow_two_holders() -> None:
    gate = SchedulerGate(SchedulerGateConfig(max_concurrent_llm=2),
                         signals_provider=lambda: _sig(cpu=10),
                         sleep=lambda s: None)
    barrier = threading.Barrier(2, timeout=2)
    ok: list[bool] = []

    def worker():
        with gate.permit():
            try:
                barrier.wait()  # both must be inside simultaneously
                ok.append(True)
            except threading.BrokenBarrierError:
                ok.append(False)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3)
    assert ok == [True, True]


# --- config loading --------------------------------------------------------


def test_config_from_mapping_ignores_unknown_keys() -> None:
    cfg = SchedulerGateConfig.from_mapping({"mode": "off", "bogus": 123,
                                            "battery_floor_pct": 50})
    assert cfg.mode == "off"
    assert cfg.battery_floor_pct == 50


def test_config_from_missing_file_is_defaults(tmp_path) -> None:
    cfg = SchedulerGateConfig.from_config_file(tmp_path / "nope.toml")
    assert cfg == SchedulerGateConfig()


def test_config_from_file_reads_table(tmp_path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        "[governor.scheduler_gate]\nmode = \"aggressive\"\n"
        "max_concurrent_llm = 4\n"
    )
    cfg = SchedulerGateConfig.from_config_file(p)
    assert cfg.mode == "aggressive"
    assert cfg.max_concurrent_llm == 4
