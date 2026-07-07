"""Calibration metrics — proper scoring, Brier decomposition, shrinkage, temperature."""

from __future__ import annotations

import math

import pytest

from lighthouse_ai.verification import calibration as cal


# --- log score ---------------------------------------------------------------
def test_log_score_basic_and_overconfidence_penalty():
    # Confident + correct → small; confident + wrong → large (but finite).
    assert cal.log_score(0.9, True) < cal.log_score(0.6, True)
    assert cal.log_score(0.01, True) > cal.log_score(0.4, True)
    # Clipped, never infinite.
    assert math.isfinite(cal.log_score(1.0, False))
    assert math.isfinite(cal.log_score(0.0, True))
    # Log score punishes a confident miss harder than Brier (relative to a hedge).
    lo_gap = cal.log_score(0.99, False) - cal.log_score(0.5, False)
    br_gap = (0.99 - 0.0) ** 2 - (0.5 - 0.0) ** 2
    assert lo_gap > br_gap


# --- Brier decomposition (Murphy) -------------------------------------------
def test_brier_decomposition_identity_for_binned_constant_forecasts():
    # Forecasts take two distinct values that land in separate deciles, so each
    # bin's forecast is constant → the decomposition identity is exact.
    preds = (
        [(0.2, False)] * 8
        + [(0.2, True)] * 2  # bin@0.2: 20% true
        + [(0.8, True)] * 7
        + [(0.8, False)] * 3
    )  # bin@0.8: 70% true
    d = cal.brier_decomposition(preds)
    mean_brier = sum((p - (1.0 if o else 0.0)) ** 2 for p, o in preds) / len(preds)
    assert d["brier"] == pytest.approx(mean_brier, abs=1e-4)
    assert d["brier"] == pytest.approx(
        d["reliability"] - d["resolution"] + d["uncertainty"], abs=1e-4
    )
    assert d["n"] == len(preds)


def test_brier_decomposition_perfect_calibration_low_reliability():
    # Forecast exactly matches the empirical rate in each bin → reliability ≈ 0.
    preds = [(0.3, True)] * 3 + [(0.3, False)] * 7 + [(0.7, True)] * 7 + [(0.7, False)] * 3
    d = cal.brier_decomposition(preds)
    assert d["reliability"] < 1e-6
    assert d["resolution"] > 0  # the forecasts discriminate


# --- incomplete beta / quantile ---------------------------------------------
def test_incomplete_beta_and_ppf_known_values():
    # Beta(1,1) is uniform: CDF(x)=x, PPF(q)=q.
    assert cal.reg_incomplete_beta(1, 1, 0.37) == pytest.approx(0.37, abs=1e-6)
    assert cal.beta_ppf(0.5, 1, 1) == pytest.approx(0.5, abs=1e-4)
    # Symmetric Beta(3,3): median = 0.5.
    assert cal.beta_ppf(0.5, 3, 3) == pytest.approx(0.5, abs=1e-3)
    # Monotone CDF.
    assert cal.reg_incomplete_beta(2, 5, 0.2) < cal.reg_incomplete_beta(2, 5, 0.6)


def test_beta_binomial_shrinkage_pulls_small_samples_to_prior():
    # 1 of 1 hits with a prior centered at 0.5 → posterior well below 1.0.
    est = cal.beta_binomial_estimate(1, 1, prior_mean=0.5)
    assert 0.5 < est["mean"] < 0.8
    assert est["lo"] < est["mean"] < est["hi"]
    # Lots of data overwhelms the weak prior.
    est2 = cal.beta_binomial_estimate(90, 100, prior_mean=0.5)
    assert est2["mean"] == pytest.approx(0.9, abs=0.02)
    assert est2["hi"] - est2["lo"] < 0.15  # tight interval with n=100


def test_reliability_curve_bins_and_intervals():
    preds = [(0.8, True)] * 6 + [(0.8, False)] * 4 + [(0.2, False)] * 9 + [(0.2, True)]
    curve = cal.reliability_curve(preds)
    by_pred = {round(r["predicted"], 1): r for r in curve}
    assert 0.8 in by_pred and 0.2 in by_pred
    hi = by_pred[0.8]
    assert hi["n"] == 10 and hi["hits"] == 6
    assert hi["observed_lo"] <= hi["observed"] <= hi["observed_hi"]


# --- temperature scaling -----------------------------------------------------
def test_apply_temperature_monotone_and_noop_at_one():
    assert cal.apply_temperature(0.8, 1.0) == pytest.approx(0.8, abs=1e-9)
    # T>1 softens toward 0.5; T<1 sharpens away from it.
    assert 0.5 < cal.apply_temperature(0.9, 2.0) < 0.9
    assert cal.apply_temperature(0.9, 0.5) > 0.9
    # Monotonic in p.
    assert cal.apply_temperature(0.6, 2.0) < cal.apply_temperature(0.8, 2.0)


def test_fit_temperature_corrects_overconfidence():
    # Overconfident: predicts 0.95/0.05 but is right only ~70% of the time.
    preds = [(0.95, True)] * 7 + [(0.95, False)] * 3 + [(0.05, False)] * 7 + [(0.05, True)] * 3
    t = cal.fit_temperature(preds)
    assert t > 1.0  # needs softening
    before = cal.expected_calibration_error(preds)
    after = cal.expected_calibration_error([(cal.apply_temperature(p, t), o) for p, o in preds])
    assert after < before


def test_fit_temperature_degenerate_returns_one():
    assert cal.fit_temperature([(0.9, True)] * 10) == 1.0  # one-class
    assert cal.fit_temperature([(0.7, True), (0.3, False)]) == 1.0  # too few


# --- evidence strength -------------------------------------------------------
def test_evidence_strength_monotone_and_bounded():
    assert cal.evidence_strength(n_sources=0) == pytest.approx(0.0, abs=1e-6)
    a = cal.evidence_strength(n_sources=2)
    b = cal.evidence_strength(n_sources=8)
    assert 0.0 <= a < b <= 1.0
    # Optional signals fold in and stay in range.
    s = cal.evidence_strength(n_sources=5, independence=0.9, recency=0.4, agreement=1.0)
    assert 0.0 <= s <= 1.0


# --- evidence-derived probability (replaces fixed 0.75/0.5/0.7 heuristics) ----
def test_probability_from_evidence_unsourced_below_even():
    # An asserted-but-uncited claim sits just below "even chance".
    assert cal.probability_from_evidence(n_sources=0) == 0.45


def test_probability_from_evidence_monotone_in_sources():
    p1 = cal.probability_from_evidence(n_sources=1, independent_sources=1)
    p2 = cal.probability_from_evidence(n_sources=2, independent_sources=2)
    p3 = cal.probability_from_evidence(n_sources=5, independent_sources=5)
    # More (independent) sources → strictly higher confidence, with a sourced floor.
    assert 0.55 <= p1 < p2 < p3 <= 0.92
    # Sourced always beats unsourced.
    assert p1 > cal.probability_from_evidence(n_sources=0)


def test_probability_from_evidence_independence_and_entailment_help():
    # Two independent sources beat one source cited twice.
    one = cal.probability_from_evidence(n_sources=2, independent_sources=1)
    two = cal.probability_from_evidence(n_sources=2, independent_sources=2)
    assert two > one
    # Measured entailment raises confidence; absent entailment is neutral.
    with_ent = cal.probability_from_evidence(n_sources=2, independent_sources=2, entailment=1.0)
    no_ent = cal.probability_from_evidence(n_sources=2, independent_sources=2, entailment=None)
    assert with_ent >= no_ent


def test_probability_from_evidence_contradiction_caps_at_even():
    # However strong the evidence, a flagged contradiction can't read above "even".
    p = cal.probability_from_evidence(
        n_sources=5, independent_sources=5, entailment=1.0, contradicted=True
    )
    assert p <= 0.5


def test_probability_from_evidence_always_in_unit_interval():
    for n in range(0, 20):
        for indep in (None, 0, 1, 3):
            p = cal.probability_from_evidence(n_sources=n, independent_sources=indep)
            assert 0.0 <= p <= 1.0
