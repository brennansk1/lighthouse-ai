"""Calibration metrics — honest scoring + display for the Track pipeline.

Implements the statistics the calibration-pipeline improvement memo calls for, in
**pure Python** (math only — no numpy/scipy) so the core Track feature works on a
base install, offline and deterministically:

* :func:`log_score` — logarithmic proper scoring rule (penalizes overconfidence
  harder than Brier; the dominant failure mode), with probability clipping.
* :func:`brier_decomposition` — Murphy's reliability − resolution + uncertainty,
  separating "honest about its uncertainty" (calibration) from "actually
  knowledgeable" (discrimination).
* :func:`reliability_curve` — per-band empirical outcome rate with **Beta-Binomial
  shrinkage** toward a weak prior, reported with a credible interval, so small
  samples are not over-read.
* :func:`fit_temperature` / :func:`apply_temperature` — one-parameter temperature
  scaling to correct systematic over/under-confidence (robust with small
  calibration sets; does not change answer ranking).
* :func:`evidence_strength` — combine count/independence/recency/agreement of
  citations into a [0,1] signal that feeds probability elicitation.

The incomplete-beta machinery (:func:`reg_incomplete_beta`, :func:`beta_ppf`) is a
dependency-free port of the standard continued-fraction algorithm.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

#: clip bound so log score / logit never see exactly 0 or 1.
_EPS = 1e-6

Pred = tuple[float, bool]  # (probability in [0,1], outcome)


def _clip(p: float, eps: float = _EPS) -> float:
    return min(1.0 - eps, max(eps, p))


# --------------------------------------------------------------------------- #
# Proper scoring rules
# --------------------------------------------------------------------------- #
def log_score(probability: float, outcome: bool, *, eps: float = _EPS) -> float:
    """Negative log-likelihood of the outcome under the forecast (lower = better).

    ``-(y·ln p + (1-y)·ln(1-p))``. Sharper on overconfidence than Brier. Clipped
    so a confident miss is a large-but-finite penalty rather than infinity.
    """
    p = _clip(probability, eps)
    return -(math.log(p) if outcome else math.log(1.0 - p))


def mean_log_score(preds: Sequence[Pred], *, eps: float = _EPS) -> float:
    items = list(preds)
    if not items:
        return 0.0
    return sum(log_score(p, o, eps=eps) for p, o in items) / len(items)


def brier_decomposition(preds: Sequence[Pred], *, n_bins: int = 10) -> dict:
    """Murphy's three-component decomposition of the mean Brier score.

    ``brier = reliability − resolution + uncertainty`` where, over ``n_bins``
    equal-width probability bins (k):

    * **uncertainty** = ``ō(1−ō)`` (the irreducible difficulty; ``ō`` = base rate)
    * **reliability** = ``Σ nₖ(f̄ₖ − ōₖ)² / N`` (calibration error — lower better)
    * **resolution** = ``Σ nₖ(ōₖ − ō)² / N`` (discrimination — higher better)

    Returns all four plus ``n``. With no data, returns zeros.
    """
    items = [(float(p), 1.0 if o else 0.0) for p, o in preds]
    n = len(items)
    if n == 0:
        return {"brier": 0.0, "reliability": 0.0, "resolution": 0.0, "uncertainty": 0.0, "n": 0}
    obar = sum(o for _, o in items) / n
    bins: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for p, o in items:
        idx = min(n_bins - 1, int(p * n_bins))
        bins[idx].append((p, o))
    reliability = 0.0
    resolution = 0.0
    for b in bins:
        if not b:
            continue
        nk = len(b)
        fbar = sum(p for p, _ in b) / nk
        obark = sum(o for _, o in b) / nk
        reliability += nk * (fbar - obark) ** 2
        resolution += nk * (obark - obar) ** 2
    reliability /= n
    resolution /= n
    uncertainty = obar * (1.0 - obar)
    brier = reliability - resolution + uncertainty
    return {
        "brier": round(brier, 5),
        "reliability": round(reliability, 5),
        "resolution": round(resolution, 5),
        "uncertainty": round(uncertainty, 5),
        "n": n,
    }


# --------------------------------------------------------------------------- #
# Beta-Binomial shrinkage + credible intervals (pure-python incomplete beta)
# --------------------------------------------------------------------------- #
def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta (Numerical Recipes)."""
    fpmin = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def reg_incomplete_beta(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta ``I_x(a, b)`` — the Beta(a,b) CDF at ``x``."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_ppf(q: float, a: float, b: float) -> float:
    """Quantile (inverse CDF) of Beta(a, b) via bisection on the CDF."""
    if q <= 0.0:
        return 0.0
    if q >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if reg_incomplete_beta(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def beta_binomial_estimate(
    k: int, n: int, *, prior_mean: float, prior_strength: float = 2.0, ci: float = 0.90
) -> dict:
    """Shrunk success-rate estimate for ``k`` of ``n`` with a weak Beta prior.

    The prior is ``Beta(prior_mean·s, (1-prior_mean)·s)`` with strength ``s``
    (default 2 pseudo-observations), so a band with little data is pulled toward
    its expected rate rather than reading a noisy 0/1. Returns the posterior mean
    and a central credible interval.
    """
    pm = min(1.0, max(0.0, prior_mean))
    a0 = pm * prior_strength
    b0 = (1.0 - pm) * prior_strength
    a = k + a0
    b = (n - k) + b0
    mean = a / (a + b)
    lo = beta_ppf((1.0 - ci) / 2.0, a, b)
    hi = beta_ppf(1.0 - (1.0 - ci) / 2.0, a, b)
    return {"mean": round(mean, 4), "lo": round(lo, 4), "hi": round(hi, 4), "n": n}


def reliability_curve(
    preds: Sequence[Pred],
    bins: Sequence[tuple[float, float]] | None = None,
    *,
    prior_strength: float = 2.0,
    ci: float = 0.90,
) -> list[dict]:
    """Per-bin reliability: mean forecast vs shrunk observed rate + interval.

    ``bins`` is a list of ``(lo, hi)`` probability ranges (default: deciles). Each
    returned row has the bin's mean predicted probability (x), the Beta-Binomial
    shrunk observed rate with credible interval (y, lo, hi), and the count. Empty
    bins are omitted. The shrinkage prior for each bin is centered on the bin
    midpoint (perfect calibration), so sparse bins sit on the diagonal until
    evidence moves them.
    """
    if bins is None:
        bins = [(i / 10.0, (i + 1) / 10.0) for i in range(10)]
    items = [(float(p), 1.0 if o else 0.0) for p, o in preds]
    out: list[dict] = []
    for lo, hi in bins:
        members = [(p, o) for p, o in items if (lo <= p < hi) or (hi >= 1.0 and p == 1.0)]
        if not members:
            continue
        n = len(members)
        k = round(sum(o for _, o in members))
        mean_pred = sum(p for p, _ in members) / n
        midpoint = 0.5 * (lo + hi)
        est = beta_binomial_estimate(
            k, n, prior_mean=midpoint, prior_strength=prior_strength, ci=ci
        )
        out.append(
            {
                "bin_lo": round(lo, 3),
                "bin_hi": round(hi, 3),
                "predicted": round(mean_pred, 4),
                "observed": est["mean"],
                "observed_lo": est["lo"],
                "observed_hi": est["hi"],
                "n": n,
                "hits": k,
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Temperature scaling (one-parameter recalibration)
# --------------------------------------------------------------------------- #
def _logit(p: float) -> float:
    p = _clip(p)
    return math.log(p / (1.0 - p))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def apply_temperature(probability: float, temperature: float) -> float:
    """Recalibrate a probability by scaling its logit: ``σ(logit(p)/T)``.

    ``T > 1`` softens (corrects overconfidence), ``T < 1`` sharpens, ``T == 1`` is
    a no-op. Monotonic, so it never changes the ranking of answers.
    """
    if temperature <= 0:
        return probability
    return _sigmoid(_logit(probability) / temperature)


def fit_temperature(
    preds: Sequence[Pred], *, lo: float = 0.2, hi: float = 5.0, iters: int = 60
) -> float:
    """Fit the temperature minimizing mean log loss on ``preds`` (golden-section).

    Returns 1.0 (no-op) when there's too little or degenerate data. Robust with
    small calibration sets — the whole point of one-parameter scaling.
    """
    items = [(_clip(float(p)), 1.0 if o else 0.0) for p, o in preds]
    if len(items) < 4:
        return 1.0
    # Need both outcomes present, else NLL is monotone in T and "fit" is spurious.
    s = sum(o for _, o in items)
    if s == 0 or s == len(items):
        return 1.0

    def nll(t: float) -> float:
        tot = 0.0
        for p, o in items:
            q = apply_temperature(p, t)
            q = _clip(q)
            tot += -(math.log(q) if o else math.log(1.0 - q))
        return tot / len(items)

    gr = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c = b - gr * (b - a)
    d = a + gr * (b - a)
    fc, fd = nll(c), nll(d)
    for _ in range(iters):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - gr * (b - a)
            fc = nll(c)
        else:
            a, c, fc = c, d, fd
            d = a + gr * (b - a)
            fd = nll(d)
    return round(0.5 * (a + b), 4)


def expected_calibration_error(preds: Sequence[Pred], *, n_bins: int = 10) -> float:
    """Binned ECE: |mean forecast − mean outcome| weighted by bin population."""
    items = [(float(p), 1.0 if o else 0.0) for p, o in preds]
    n = len(items)
    if n == 0:
        return 0.0
    bins: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for p, o in items:
        bins[min(n_bins - 1, int(p * n_bins))].append((p, o))
    ece = 0.0
    for b in bins:
        if not b:
            continue
        nk = len(b)
        fbar = sum(p for p, _ in b) / nk
        obar = sum(o for _, o in b) / nk
        ece += (nk / n) * abs(fbar - obar)
    return round(ece, 5)


# --------------------------------------------------------------------------- #
# Evidence strength → input to probability elicitation
# --------------------------------------------------------------------------- #
def evidence_strength(
    *,
    n_sources: int = 0,
    independence: float | None = None,
    recency: float | None = None,
    agreement: float | None = None,
) -> float:
    """Combine evidence features into a [0,1] strength signal.

    ``n_sources`` is mapped through a saturating curve (more sources help with
    diminishing returns). ``independence`` (distinct authors/domains), ``recency``
    (how fresh), and ``agreement`` (do sources concur) are optional [0,1] signals,
    averaged in when present. Returns 0..1; higher = stronger evidence.
    """
    src = 1.0 - math.exp(-max(0, n_sources) / 3.0)  # ~0 at 0, ~0.95 at 9
    parts = [src]
    for v in (independence, recency, agreement):
        if v is not None:
            parts.append(min(1.0, max(0.0, float(v))))
    return round(sum(parts) / len(parts), 4)


#: probability floors/ceilings for an evidence-derived claim confidence.
_UNSOURCED_P = 0.45  # an asserted-but-uncited claim sits just below "even"
_SOURCED_FLOOR = 0.55  # a single cited source starts in "even/likely"
_SOURCED_SPAN = 0.37  # strongest evidence reaches ~0.92 ("almost certain" floor)
_CONTRADICTED_CAP = 0.5  # a flagged contradiction can't read above "even chance"


def probability_from_evidence(
    *,
    n_sources: int,
    independent_sources: int | None = None,
    entailment: float | None = None,
    contradicted: bool = False,
) -> float:
    """Derive *the probability a claim is true* from its evidence (not a constant).

    This replaces the old fixed heuristics (Investigate's 0.75/0.5, Survey's 0.7)
    that made calibration close to vacuous — there was no probability variation to
    calibrate. The mapping is:

    * **unsourced** assertion → ``0.45`` (just below "even chance" — we said it but
      can't ground it);
    * **sourced** → ``0.55 + 0.37 · evidence_strength`` where strength rises with
      source count (diminishing returns), independence (distinct sources, target 2),
      and entailment/faithfulness when measured — reaching ~0.92 for strong,
      triangulated, entailed evidence;
    * a **flagged contradiction** caps the result at ``0.5`` regardless.

    Monotone non-decreasing in evidence, deterministic, in ``[0, 1]``. Keeps the
    binary true/false claim as the cheap base case (the probability is *of* truth).
    """
    if n_sources <= 0:
        p = _UNSOURCED_P
    else:
        indep = n_sources if independent_sources is None else max(0, independent_sources)
        independence = min(1.0, indep / 2.0)  # 1 distinct → 0.5, ≥2 → 1.0
        s = evidence_strength(n_sources=n_sources, independence=independence, agreement=entailment)
        p = _SOURCED_FLOOR + _SOURCED_SPAN * s
    if contradicted:
        p = min(p, _CONTRADICTED_CAP)
    return round(p, 3)
