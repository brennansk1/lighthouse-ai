"""Unit tests for the Governor token buckets + degradation tier."""

from __future__ import annotations

import threading

import pytest
from hypothesis import given, settings, strategies as st

from lighthouse_ai.governor import (
    BUDGET_DEFAULTS,
    BudgetConfig,
    BudgetTripped,
    Governor,
    degradation_tier,
)
from lighthouse_ai.governor.mock_provider import MockProvider


@pytest.fixture
def gov(migrated_paths) -> Governor:
    return Governor(migrated_paths.state_db, BUDGET_DEFAULTS)


# --- degradation tier (pure function) ---

@pytest.mark.parametrize("pct,expected", [
    (100, "green"), (50, "green"),
    (49, "warn"), (30, "warn"),
    (29, "degrade"), (15, "degrade"),
    (14, "local_only"), (5, "local_only"),
    (4.9, "drain"), (0.1, "drain"),
    (0, "tripped"),
])
def test_degradation_tier_thresholds(pct, expected):
    assert degradation_tier(pct) == expected


# --- single-thread bucket math ---

def test_initial_remaining_matches_ceiling(gov):
    rem = gov.remaining()
    assert rem["usd"]["monthly"] == BUDGET_DEFAULTS.monthly_usd
    assert rem["tool_calls"]["daily"] == BUDGET_DEFAULTS.daily_tool_calls
    assert rem["tokens"]["weekly"] == BUDGET_DEFAULTS.weekly_tokens


def test_spend_debits_every_period(gov):
    d = gov.try_spend(usd=0.50, tool_calls=10, tokens=1000)
    assert d.allowed
    rem = gov.remaining()
    assert rem["usd"]["daily"] == pytest.approx(BUDGET_DEFAULTS.daily_usd - 0.5)
    assert rem["usd"]["weekly"] == pytest.approx(BUDGET_DEFAULTS.weekly_usd - 0.5)
    assert rem["usd"]["monthly"] == pytest.approx(BUDGET_DEFAULTS.monthly_usd - 0.5)
    assert rem["tool_calls"]["daily"] == BUDGET_DEFAULTS.daily_tool_calls - 10


def test_spend_refuses_when_any_period_underflows(gov):
    # Burn the entire daily USD bucket.
    d = gov.try_spend(usd=BUDGET_DEFAULTS.daily_usd)
    assert d.allowed
    # The next $0.01 must fail because daily is exhausted, even though monthly is fine.
    d2 = gov.try_spend(usd=0.01)
    assert not d2.allowed
    assert "daily" in d2.reason


def test_spend_is_atomic_across_dimensions(gov):
    """A request that would deplete one dim must not debit the others."""
    # Burn the daily tool_calls bucket.
    gov.try_spend(tool_calls=BUDGET_DEFAULTS.daily_tool_calls)
    before = gov.remaining()["tokens"]["daily"]
    bad = gov.try_spend(usd=0.01, tool_calls=1, tokens=1000)
    assert not bad.allowed
    after = gov.remaining()["tokens"]["daily"]
    assert before == after  # tokens not touched


def test_spend_returns_tier(gov):
    d = gov.try_spend(usd=0.001)
    assert d.tier == "green"


def test_reset_restores_ceilings(gov):
    gov.try_spend(usd=1.0, tool_calls=100, tokens=5000)
    assert gov.remaining()["usd"]["daily"] < BUDGET_DEFAULTS.daily_usd
    cleared = gov.reset()
    assert cleared > 0
    rem = gov.remaining()
    assert rem["usd"]["daily"] == BUDGET_DEFAULTS.daily_usd
    assert rem["tokens"]["monthly"] == BUDGET_DEFAULTS.monthly_tokens


def test_spend_method_raises_on_trip(gov):
    gov.try_spend(usd=BUDGET_DEFAULTS.daily_usd)
    with pytest.raises(BudgetTripped):
        gov.spend(usd=0.01)


def test_cost_report_includes_tier_and_config(gov):
    report = gov.cost_report()
    assert "tier" in report
    assert "remaining" in report
    assert report["config"]["monthly_usd"] == BUDGET_DEFAULTS.monthly_usd


def test_no_op_spend_returns_allowed(gov):
    d = gov.try_spend()
    assert d.allowed
    assert d.reason == "no-op"


# --- concurrency: many workers, math still correct ---

def test_concurrent_spend_math_correct(gov):
    """5 threads × 20 spends of $0.01 → daily reduced by exactly $1.00.

    Stays well under the $3 daily ceiling so every spend is allowed; the
    only thing under test is that concurrent BEGIN IMMEDIATE serializes
    and no debit is lost or double-counted.
    """
    errors: list[BaseException] = []

    def worker():
        try:
            for _ in range(20):
                gov.try_spend(usd=0.01)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    spent_daily = BUDGET_DEFAULTS.daily_usd - gov.remaining()["usd"]["daily"]
    assert spent_daily == pytest.approx(1.00, abs=1e-9)


# --- mock provider integration ---

def test_mock_provider_records_spend(gov):
    p = MockProvider(gov, usd_per_1k_tokens=0.001, completion_tokens=4)
    before = gov.remaining()["tool_calls"]["daily"]
    resp = p.complete("hello world test prompt")
    assert resp.completion_tokens == 4
    assert resp.prompt_tokens >= 1
    after = gov.remaining()["tool_calls"]["daily"]
    assert after == before - 1


def test_mock_provider_raises_when_tripped(gov):
    p = MockProvider(gov, usd_per_1k_tokens=10.0)  # absurdly expensive
    with pytest.raises(BudgetTripped):
        for _ in range(10_000):
            p.complete("x")


# --- property: bucket sum never goes negative ---

@settings(max_examples=30, deadline=None)
@given(st.lists(st.floats(min_value=0.0, max_value=0.1, allow_nan=False,
                          allow_infinity=False), min_size=1, max_size=50))
def test_property_remaining_never_negative(amounts):
    """Hypothesis: random USD spends never push the remaining below zero."""
    import tempfile
    from lighthouse_ai.paths import make_paths
    from lighthouse_ai.schema import kinds_for, migrate_all
    td = tempfile.mkdtemp()
    paths = make_paths(td)
    paths.ensure()
    migrate_all(kinds_for(paths))
    g = Governor(paths.state_db, BUDGET_DEFAULTS)
    for amt in amounts:
        g.try_spend(usd=amt)
    rem = g.remaining()
    for dim_map in rem.values():
        for v in dim_map.values():
            assert v >= 0.0
