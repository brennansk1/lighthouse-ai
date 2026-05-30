"""Offline-deterministic tests for the Decide engine.

All tests run without a gateway and without any real LLM calls.
The gateway=None stub path is fully deterministic from (option, criterion) pairs.
"""

from __future__ import annotations

import pytest

from lighthouse_ai.modes.decide import (
    Criterion,
    DecideReport,
    Option,
    run_decide,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _two_option_run(**kw) -> DecideReport:
    """Standard two-option, two-criterion run used by many tests."""
    return run_decide(
        "Which database?",
        options=[Option("Postgres"), Option("SQLite")],
        criteria=[
            Criterion("scalability", weight=2.0),
            Criterion("simplicity", weight=1.0),
        ],
        **kw,
    )


def _controlled_run(
    *,
    scores: dict[tuple[str, str], float],
    criteria: list[Criterion],
    options: list[str] | None = None,
) -> DecideReport:
    """Run decide with a monkey-patched score function for predictable results.

    ``scores`` maps (option_label, criterion_label) -> float.
    Missing pairs default to 0.5.
    """
    import lighthouse_ai.modes.decide as _mod

    opts = options or ["A", "B"]
    original_stub = _mod._stub_score

    def fake_stub(opt: str, crit: str) -> float:
        return scores.get((opt, crit), 0.5)

    _mod._stub_score = fake_stub
    try:
        return run_decide("test question", options=opts, criteria=criteria)
    finally:
        _mod._stub_score = original_stub


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

def test_requires_two_options_message():
    with pytest.raises(ValueError, match="at least 2 options"):
        run_decide("q", options=["only"], criteria=[Criterion("c", 1.0)])


def test_requires_a_criterion_message():
    with pytest.raises(ValueError, match="at least one criterion"):
        run_decide("q", options=["a", "b"], criteria=[])


def test_rejects_duplicate_option_labels():
    """Two options with the same label collapse to one totals key, producing a
    nonsensical single-option report (runner_up=None, margin>1.0). Reject them:
    the docstring promises 'at least two DISTINCT options'."""
    with pytest.raises(ValueError, match="distinct"):
        run_decide("q", options=["A", "A"], criteria=[Criterion("c", 1.0)])


def test_rejects_zero_weight_names_offender():
    with pytest.raises(ValueError, match="non-positive weights"):
        run_decide(
            "q", options=["a", "b"],
            criteria=[Criterion("good", 1.0), Criterion("bad", 0.0)],
        )


def test_rejects_negative_weight():
    with pytest.raises(ValueError, match="non-positive weights"):
        run_decide("q", options=["a", "b"], criteria=[Criterion("c", -1.0)])


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_deterministic_winner_and_totals():
    r1 = _two_option_run()
    r2 = _two_option_run()
    assert r1.winner == r2.winner
    assert r1.totals == r2.totals


def test_totals_in_unit_interval():
    r = _two_option_run()
    assert set(r.totals) == {"Postgres", "SQLite"}
    assert all(0.0 <= v <= 1.0 for v in r.totals.values())


# ---------------------------------------------------------------------------
# Weighted argmax correctness
# ---------------------------------------------------------------------------

def test_weighted_argmax_picks_correct_winner():
    """A wins on scalability (weight 3); B wins on cost (weight 1) — A should win."""
    crits = [
        Criterion("scalability", weight=3.0),
        Criterion("cost", weight=1.0),
    ]
    scores = {
        ("A", "scalability"): 0.9,
        ("A", "cost"): 0.1,
        ("B", "scalability"): 0.2,
        ("B", "cost"): 0.9,
    }
    r = _controlled_run(scores=scores, criteria=crits)
    assert r.winner == "A", f"Expected A but got {r.winner}"


def test_weighted_argmax_with_equal_weights():
    """Equal weights — the option with higher average score should win."""
    crits = [
        Criterion("x", weight=1.0),
        Criterion("y", weight=1.0),
    ]
    scores = {
        ("A", "x"): 0.8,
        ("A", "y"): 0.6,
        ("B", "x"): 0.4,
        ("B", "y"): 0.4,
    }
    r = _controlled_run(scores=scores, criteria=crits)
    assert r.winner == "A"


def test_total_equals_weighted_sum():
    """Verify totals match the manual weighted calculation."""
    crits = [
        Criterion("p", weight=1.0),
        Criterion("q", weight=3.0),
    ]
    scores = {
        ("X", "p"): 0.8,
        ("X", "q"): 0.6,
        ("Y", "p"): 0.2,
        ("Y", "q"): 0.4,
    }
    r = _controlled_run(scores=scores, criteria=crits, options=["X", "Y"])
    # weight_sum = 4; X total = (1/4)*0.8 + (3/4)*0.6 = 0.2 + 0.45 = 0.65
    assert abs(r.totals["X"] - 0.65) < 0.001, f"X total = {r.totals['X']}"
    # Y total = (1/4)*0.2 + (3/4)*0.4 = 0.05 + 0.30 = 0.35
    assert abs(r.totals["Y"] - 0.35) < 0.001, f"Y total = {r.totals['Y']}"


# ---------------------------------------------------------------------------
# higher_is_better=False handling
# ---------------------------------------------------------------------------

def test_lower_is_better_flips_score():
    """lower_is_better criterion: the option with low raw score should win."""
    crits = [Criterion("cost", weight=1.0, higher_is_better=False)]
    scores = {
        ("Cheap", "cost"): 0.2,   # effective = 1-0.2 = 0.8
        ("Expensive", "cost"): 0.9,  # effective = 1-0.9 = 0.1
    }
    r = _controlled_run(
        scores=scores, criteria=crits, options=["Cheap", "Expensive"]
    )
    assert r.winner == "Cheap"


def test_lower_is_better_contribution_matches_effective():
    """Contribution for lower_is_better cell should use 1-raw, not raw."""
    crits = [Criterion("latency", weight=1.0, higher_is_better=False)]
    scores = {("Fast", "latency"): 0.1, ("Slow", "latency"): 0.9}
    r = _controlled_run(scores=scores, criteria=crits, options=["Fast", "Slow"])
    fast_cell = next(c for c in r.cells if c.option == "Fast")
    # score == raw; contribution == 1 - raw (since only criterion, weight_sum=1)
    assert abs(fast_cell.score - 0.1) < 0.001
    assert abs(fast_cell.contribution - 0.9) < 0.001


def test_mixed_polarity_winner():
    """Mix of higher_is_better and lower_is_better resolves correctly."""
    crits = [
        Criterion("speed", weight=2.0, higher_is_better=True),
        Criterion("cost", weight=1.0, higher_is_better=False),
    ]
    scores = {
        ("A", "speed"): 0.9,
        ("A", "cost"): 0.8,   # high cost = bad (effective 0.2)
        ("B", "speed"): 0.4,
        ("B", "cost"): 0.1,   # low cost = good (effective 0.9)
    }
    # A contribution: (2/3)*0.9 + (1/3)*0.2 = 0.6 + 0.0667 = 0.667
    # B contribution: (2/3)*0.4 + (1/3)*0.9 = 0.267 + 0.3 = 0.567
    r = _controlled_run(scores=scores, criteria=crits)
    assert r.winner == "A"


# ---------------------------------------------------------------------------
# Cells coverage
# ---------------------------------------------------------------------------

def test_cells_cover_every_option_criterion_pair():
    r = _two_option_run()
    pairs = {(c.option, c.criterion) for c in r.cells}
    assert pairs == {
        ("Postgres", "scalability"), ("Postgres", "simplicity"),
        ("SQLite", "scalability"), ("SQLite", "simplicity"),
    }


def test_cell_score_in_unit_interval():
    r = _two_option_run()
    for cell in r.cells:
        assert 0.0 <= cell.score <= 1.0, f"score out of range: {cell}"


def test_cell_contribution_non_negative():
    r = _two_option_run()
    for cell in r.cells:
        assert cell.contribution >= 0.0, f"contribution negative: {cell}"


# ---------------------------------------------------------------------------
# Sensitivity sweep
# ---------------------------------------------------------------------------

def test_sensitivity_sweep_present_for_each_criterion():
    r = _two_option_run()
    assert {s.criterion for s in r.sensitivity} == {"scalability", "simplicity"}


def test_sensitivity_detects_flip():
    """When a criterion is removed and the winner changes, decisive=True."""
    # A wins overall; but without 'key', B should win.
    crits = [
        Criterion("key", weight=4.0),
        Criterion("minor", weight=1.0),
    ]
    scores = {
        ("A", "key"): 0.95,
        ("A", "minor"): 0.1,
        ("B", "key"): 0.1,
        ("B", "minor"): 0.95,
    }
    r = _controlled_run(scores=scores, criteria=crits)
    assert r.winner == "A"
    key_sens = next(s for s in r.sensitivity if s.criterion == "key")
    assert key_sens.decisive is True
    assert key_sens.swing_to == "B"


def test_sensitivity_no_flip_when_lead_robust():
    """When one option dominates on all criteria, no flip occurs."""
    crits = [Criterion("c1", weight=1.0), Criterion("c2", weight=1.0)]
    scores = {
        ("Strong", "c1"): 0.99,
        ("Strong", "c2"): 0.99,
        ("Weak", "c1"): 0.01,
        ("Weak", "c2"): 0.01,
    }
    r = _controlled_run(scores=scores, criteria=crits, options=["Strong", "Weak"])
    assert r.winner == "Strong"
    for s in r.sensitivity:
        assert s.decisive is False, f"{s.criterion} was marked decisive unexpectedly"


def test_sensitivity_margin_delta_is_float():
    r = _two_option_run()
    for s in r.sensitivity:
        assert isinstance(s.margin_delta, float)


# ---------------------------------------------------------------------------
# Crux quality
# ---------------------------------------------------------------------------

def test_crux_is_nonempty_and_mentions_winner():
    r = _two_option_run()
    assert r.crux
    assert r.winner in r.crux


def test_crux_mentions_runner_up_when_present():
    r = _two_option_run()
    if r.runner_up:
        assert r.runner_up in r.crux


def test_crux_mentions_decisive_criterion_when_flip_exists():
    crits = [Criterion("key", weight=4.0), Criterion("minor", weight=1.0)]
    scores = {
        ("A", "key"): 0.95,
        ("A", "minor"): 0.1,
        ("B", "key"): 0.1,
        ("B", "minor"): 0.95,
    }
    r = _controlled_run(scores=scores, criteria=crits)
    assert "key" in r.crux, f"Crux does not mention 'key': {r.crux!r}"


def test_crux_mentions_adjudicate_when_decisive():
    crits = [Criterion("key", weight=4.0), Criterion("minor", weight=1.0)]
    scores = {
        ("A", "key"): 0.95, ("A", "minor"): 0.1,
        ("B", "key"): 0.1, ("B", "minor"): 0.95,
    }
    r = _controlled_run(scores=scores, criteria=crits)
    assert "Adjudicate" in r.crux


def test_crux_robust_lead_acknowledges_robustness():
    crits = [Criterion("c1", weight=1.0), Criterion("c2", weight=1.0)]
    scores = {
        ("Strong", "c1"): 0.99, ("Strong", "c2"): 0.99,
        ("Weak", "c1"): 0.01, ("Weak", "c2"): 0.01,
    }
    r = _controlled_run(scores=scores, criteria=crits, options=["Strong", "Weak"])
    assert "robust" in r.crux.lower() or "all weighting" in r.crux.lower()


# ---------------------------------------------------------------------------
# Decisive criteria list (additive field)
# ---------------------------------------------------------------------------

def test_decisive_criteria_field_present():
    r = _two_option_run()
    assert hasattr(r, "decisive_criteria")
    assert isinstance(r.decisive_criteria, list)


def test_decisive_criteria_matches_sensitivity():
    r = _two_option_run()
    from_sensitivity = {s.criterion for s in r.sensitivity if s.decisive}
    assert set(r.decisive_criteria) == from_sensitivity


# ---------------------------------------------------------------------------
# Primary driver (additive field)
# ---------------------------------------------------------------------------

def test_primary_driver_is_highest_weight_criterion():
    r = _two_option_run()
    # scalability has weight 2.0, simplicity has weight 1.0
    assert r.primary_driver == "scalability"


# ---------------------------------------------------------------------------
# Tie handling (two options with identical totals)
# ---------------------------------------------------------------------------

def test_tie_produces_valid_report():
    """Identical scores for both options — must not raise; winner is deterministic."""
    crits = [Criterion("c", weight=1.0)]
    scores = {("A", "c"): 0.5, ("B", "c"): 0.5}
    r = _controlled_run(scores=scores, criteria=crits)
    # Both totals are 0.5; winner is whichever sort() puts first (stable, alphabetical).
    assert r.winner in ("A", "B")
    assert abs(r.margin) < 0.001


# ---------------------------------------------------------------------------
# Dict criteria coercion
# ---------------------------------------------------------------------------

def test_dict_criteria_are_coerced():
    r = run_decide(
        "q", options=["a", "b"],
        criteria=[
            {"label": "x", "weight": 1.0},
            {"label": "y", "weight": 2.0, "higher_is_better": False},
        ],
    )
    assert {c.label for c in r.criteria} == {"x", "y"}
    y_crit = next(c for c in r.criteria if c.label == "y")
    assert y_crit.higher_is_better is False


def test_string_options_are_coerced():
    r = run_decide("q", options=["Alpha", "Beta"], criteria=[Criterion("c", 1.0)])
    assert {o.label for o in r.options} == {"Alpha", "Beta"}


# ---------------------------------------------------------------------------
# Margin correctness
# ---------------------------------------------------------------------------

def test_margin_equals_winner_minus_runner_up():
    r = _two_option_run()
    if r.runner_up:
        expected = round(r.totals[r.winner] - r.totals[r.runner_up], 4)
        assert abs(r.margin - expected) < 0.0001


# ---------------------------------------------------------------------------
# Position recording
# ---------------------------------------------------------------------------

def test_records_position_when_db_given():
    recorded = {}

    class FakeDB:
        pass

    import lighthouse_ai.verification.positions as positions

    orig = positions.record_position
    positions.record_position = lambda db, *, claim, probability: recorded.update(
        claim=claim, probability=probability)
    try:
        _two_option_run(positions_db=FakeDB())
    finally:
        positions.record_position = orig
    assert "claim" in recorded
    assert 0.5 <= recorded["probability"] <= 0.95


# ---------------------------------------------------------------------------
# Three-option run
# ---------------------------------------------------------------------------

def test_three_options_winner_is_consistent():
    crits = [Criterion("quality", weight=2.0), Criterion("price", weight=1.0)]
    scores = {
        ("Gold", "quality"): 0.95, ("Gold", "price"): 0.2,
        ("Silver", "quality"): 0.70, ("Silver", "price"): 0.6,
        ("Bronze", "quality"): 0.40, ("Bronze", "price"): 0.9,
    }
    r = _controlled_run(scores=scores, criteria=crits, options=["Gold", "Silver", "Bronze"])
    # Gold: (2/3)*0.95 + (1/3)*0.2 = 0.633 + 0.067 = 0.70
    # Silver: (2/3)*0.70 + (1/3)*0.6 = 0.467 + 0.2 = 0.667
    # Bronze: (2/3)*0.40 + (1/3)*0.9 = 0.267 + 0.3 = 0.567
    assert r.winner == "Gold"
    assert r.runner_up == "Silver"
