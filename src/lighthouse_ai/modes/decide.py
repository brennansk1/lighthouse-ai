"""Mode — Decide: score options against weighted criteria, name the crux.

A Decide run takes a set of options and a set of weighted criteria, scores
every option on every criterion, computes a weighted total, and reports the
winner plus a *sensitivity sweep* that identifies which single criterion is
decisive — the crux.  That crux is phrased so it can be handed straight to
Adjudicate (``run_debate``) for a structured argument.

The engine is deterministic when ``gateway=None``: cell scores come from a
stable hash of (option, criterion) so tests and dry runs reproduce exactly.
With a gateway the same structure is filled by the model.

Sensitivity sweep
-----------------
For each criterion we re-run the weighted total with that criterion *removed*
and record whether the winner changes (``decisive=True``).  We also record the
new runner-up score delta so callers know how close the margin is after the
perturbation.

Crux phrasing
-------------
When at least one criterion is decisive, the crux names *all* decisive criteria
and frames the outcome as a falsifiable claim suitable for Adjudicate:

    "The choice of <winner> over <runner_up> is decided by <crit1> (and
    <crit2>): if those weights are wrong, <swing_to> wins instead."

When the lead is robust (no single criterion flip), the crux acknowledges the
robustness and still names the highest-weighted criterion as the primary driver.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..gateway import Gateway
from ..governor.scheduler_gate import SchedulerGate
from ._gate import gate_ctx


@dataclass(frozen=True)
class Option:
    label: str
    notes: str = ""


@dataclass(frozen=True)
class Criterion:
    label: str
    weight: float
    higher_is_better: bool = True


@dataclass(frozen=True)
class ScoredCell:
    option: str
    criterion: str
    score: float           # raw rating in [0, 1] of how well option meets criterion
    contribution: float    # weight-normalised contribution to the option's total
    rationale: str = ""


@dataclass(frozen=True)
class SensitivityResult:
    criterion: str
    decisive: bool          # zeroing this criterion flips the winner
    swing_to: str | None    # who wins if this criterion is removed
    # Additive field: how much the winner's margin changes after removal.
    # Positive = winner's lead grows (criterion was actually helping runner-up);
    # Negative = winner's lead shrinks (criterion was helping the winner).
    margin_delta: float = 0.0


@dataclass(frozen=True)
class DecideReport:
    question: str
    options: list[Option]
    criteria: list[Criterion]
    cells: list[ScoredCell]
    totals: dict[str, float]
    winner: str
    runner_up: str | None
    margin: float
    sensitivity: list[SensitivityResult]
    crux: str
    claims: list[str] = field(default_factory=list)
    # Additive fields — safe to add; frontend ignores unknown keys.
    decisive_criteria: list[str] = field(default_factory=list)
    primary_driver: str | None = None   # highest-weighted criterion


def _coerce_options(options: Sequence[Option | str]) -> list[Option]:
    out: list[Option] = []
    for o in options:
        out.append(o if isinstance(o, Option) else Option(label=str(o)))
    return out


def _coerce_criteria(criteria: Sequence[Criterion | dict]) -> list[Criterion]:
    out: list[Criterion] = []
    for c in criteria:
        if isinstance(c, Criterion):
            out.append(c)
        else:
            out.append(Criterion(
                label=str(c["label"]),
                weight=float(c.get("weight", 0.0)),
                higher_is_better=bool(c.get("higher_is_better", True)),
            ))
    return out


def _stub_score(option: str, criterion: str) -> float:
    """Deterministic pseudo-rating in [0, 1] derived from a stable SHA-256 hash.

    The hash covers both the option label and the criterion label separated by a
    null byte so that transpositions (same labels, swapped roles) produce
    different scores.
    """
    h = hashlib.sha256(f"{option}\x00{criterion}".encode()).digest()
    return (int.from_bytes(h[:4], "big") % 1000) / 999.0


def _llm_score(gateway: Gateway, question: str, option: str, criterion: str,
               *, job_id: str | None, gate: SchedulerGate | None) -> float:
    prompt = (
        f"Decision question: {question}\n"
        f"Option: {option}\n"
        f"Criterion: {criterion}\n\n"
        "On a scale of 0.0 to 1.0, how well does this option satisfy this "
        "criterion? Reply with only the number."
    )
    try:
        with gate_ctx(gate):
            resp = gateway.complete("researcher", prompt, job_id=job_id)
        for token in resp.text.replace(",", " ").split():
            try:
                val = float(token)
            except ValueError:
                continue
            return max(0.0, min(1.0, val))
    except Exception:
        pass
    return _stub_score(option, criterion)


def _compute_totals(
    options: list[Option],
    criteria: list[Criterion],
    score_fn,
) -> tuple[list[ScoredCell], dict[str, float]]:
    """Score every (option, criterion) pair and return cells + weighted totals.

    Each cell's *contribution* is ``(w_i / sum_w) * effective_score`` where
    ``effective_score = raw`` when ``higher_is_better`` and ``1 - raw``
    otherwise, so the total always lives in [0, 1] and a higher total is always
    better regardless of individual criterion polarity.
    """
    weight_sum = sum(c.weight for c in criteria) or 1.0
    cells: list[ScoredCell] = []
    totals: dict[str, float] = {o.label: 0.0 for o in options}
    for o in options:
        for c in criteria:
            raw = score_fn(o.label, c.label)
            effective = raw if c.higher_is_better else (1.0 - raw)
            contribution = (c.weight / weight_sum) * effective
            totals[o.label] += contribution
            cells.append(ScoredCell(
                option=o.label,
                criterion=c.label,
                score=round(raw, 3),
                contribution=round(contribution, 4),
            ))
    return cells, {k: round(v, 4) for k, v in totals.items()}


def _rank(totals: dict[str, float]) -> tuple[str, str | None, float]:
    """Return (winner, runner_up, margin) from a totals dict."""
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    winner = ranked[0][0]
    runner_up = ranked[1][0] if len(ranked) > 1 else None
    margin = (
        round(ranked[0][1] - ranked[1][1], 4) if len(ranked) > 1
        else round(ranked[0][1], 4)
    )
    return winner, runner_up, margin


def _sensitivity(
    options: list[Option],
    criteria: list[Criterion],
    score_fn,
    baseline_winner: str,
    baseline_margin: float,
) -> list[SensitivityResult]:
    """Drop each criterion in turn and record whether the winner changes."""
    results: list[SensitivityResult] = []
    for c in criteria:
        remaining = [x for x in criteria if x.label != c.label]
        if not remaining:
            # Only one criterion; removing it leaves nothing to decide.
            results.append(SensitivityResult(
                criterion=c.label,
                decisive=True,
                swing_to=None,
                margin_delta=0.0,
            ))
            continue
        _, sub_totals = _compute_totals(options, remaining, score_fn)
        sub_winner, _, sub_margin = _rank(sub_totals)
        decisive = sub_winner != baseline_winner
        margin_delta = round(sub_margin - baseline_margin, 4)
        results.append(SensitivityResult(
            criterion=c.label,
            decisive=decisive,
            swing_to=sub_winner if decisive else None,
            margin_delta=margin_delta,
        ))
    return results


def _build_crux(
    winner: str,
    runner_up: str | None,
    decisive_crits: list[str],
    sensitivity: list[SensitivityResult],
    primary_driver: str,
) -> str:
    """Produce a falsifiable, Adjudicate-ready crux statement.

    The statement names the specific criterion/criteria that decide the outcome
    and frames the comparison explicitly so it can seed a debate.
    """
    if runner_up is None:
        return f"{winner} is the only option under evaluation."

    if not decisive_crits:
        # No single criterion flip — lead is robust.
        return (
            f"{winner} beats {runner_up} across all weighting scenarios: "
            f"no single criterion flip reverses the outcome. "
            f"The primary driver is {primary_driver}."
        )

    # Build a concise list of decisive criteria.
    if len(decisive_crits) == 1:
        crits_phrase = decisive_crits[0]
    elif len(decisive_crits) == 2:
        crits_phrase = f"{decisive_crits[0]} and {decisive_crits[1]}"
    else:
        crits_phrase = (
            ", ".join(decisive_crits[:-1]) + f", and {decisive_crits[-1]}"
        )

    # Collect the set of alternatives that would win if decisive criteria
    # were removed (may be more than one if different criteria point to
    # different alternatives).
    swing_targets = sorted({
        s.swing_to for s in sensitivity
        if s.decisive and s.swing_to is not None
    })
    if swing_targets:
        swing_phrase = " or ".join(swing_targets)
        return (
            f"The choice of {winner} over {runner_up} is decided by "
            f"{crits_phrase}: downweighting those criteria causes "
            f"{swing_phrase} to win instead. "
            f"Adjudicate: is {crits_phrase} the right basis for this decision?"
        )

    return (
        f"The choice of {winner} over {runner_up} is decided by "
        f"{crits_phrase}. "
        f"Adjudicate: is {crits_phrase} the right basis for this decision?"
    )


def run_decide(
    question: str,
    options: Sequence[Option | str],
    criteria: Sequence[Criterion | dict],
    *,
    gateway: Gateway | None = None,
    job_id: str | None = None,
    gate: SchedulerGate | None = None,
    positions_db=None,
) -> DecideReport:
    """Score ``options`` against weighted ``criteria`` and surface the crux.

    Parameters
    ----------
    question:
        The decision being made.  Passed to the LLM (if a gateway is provided)
        as context for each score.
    options:
        At least two ``Option`` objects (or plain strings that are coerced).
    criteria:
        At least one ``Criterion`` object (or dict with ``label``, ``weight``,
        and optionally ``higher_is_better``).  All weights must be positive.
    gateway:
        When ``None`` (default) the engine uses a deterministic stub score so
        the entire run is offline and reproducible.  Pass a ``Gateway`` to have
        each cell scored by the local LLM.
    job_id:
        Forwarded to the gateway for logging/throttling.
    gate:
        Scheduler gate — limits concurrent LLM calls under the governor.
    positions_db:
        If supplied, the winner claim is recorded via
        ``verification.positions.record_position``.

    Returns
    -------
    DecideReport
        Contains the full decision matrix (cells + totals), the winner and
        runner-up, a sensitivity sweep across all criteria, and a crux
        statement ready for Adjudicate.

    Raises
    ------
    ValueError
        If there are fewer than two distinct options, no criteria are provided,
        or any criterion has a non-positive weight.  Each message names the
        offending element so callers can surface actionable errors.
    """
    opts = _coerce_options(options)
    crits = _coerce_criteria(criteria)

    if len(opts) < 2:
        raise ValueError(
            f"Decide requires at least 2 options; got {len(opts)}. "
            "Add a second option to compare against."
        )
    if not crits:
        raise ValueError(
            "Decide requires at least one criterion with a positive weight. "
            "Provide criteria so the options can be scored."
        )
    bad = [c.label for c in crits if c.weight <= 0]
    if bad:
        joined = ", ".join(repr(b) for b in bad)
        raise ValueError(
            f"Every criterion needs a positive weight; "
            f"the following have non-positive weights: {joined}."
        )

    if gateway is None:
        def score_fn(o: str, c: str) -> float:
            return _stub_score(o, c)
    else:
        def score_fn(o: str, c: str) -> float:
            return _llm_score(gateway, question, o, c, job_id=job_id, gate=gate)

    cells, totals = _compute_totals(opts, crits, score_fn)
    winner, runner_up, margin = _rank(totals)

    sensitivity = _sensitivity(opts, crits, score_fn, winner, margin)

    decisive_crits = [s.criterion for s in sensitivity if s.decisive]

    # Primary driver: the criterion with the highest weight (most influential
    # by construction regardless of sensitivity).
    primary_driver = max(crits, key=lambda c: c.weight).label

    crux = _build_crux(winner, runner_up, decisive_crits, sensitivity, primary_driver)

    claims = [f"{winner} is the best option for: {question}"]
    if positions_db is not None:
        try:
            from ..verification.positions import record_position
            # Confidence scales with margin; a thin margin is a weak claim.
            prob = max(0.5, min(0.95, 0.5 + margin))
            record_position(positions_db, claim=claims[0], probability=round(prob, 3))
        except Exception:
            pass

    return DecideReport(
        question=question,
        options=opts,
        criteria=crits,
        cells=cells,
        totals=totals,
        winner=winner,
        runner_up=runner_up,
        margin=margin,
        sensitivity=sensitivity,
        crux=crux,
        claims=claims,
        decisive_criteria=decisive_crits,
        primary_driver=primary_driver,
    )
