"""Offline-deterministic tests for Decide's evidence-variance robustness (§6).

All runs are gateway=None. Cell scores come from a monkey-patched deterministic
stub; evidence disagreement is injected via the ``evidence_variance`` argument.
No real LLM calls, no clock, fully reproducible.
"""

from __future__ import annotations

from lighthouse_ai.modes.decide import (
    Criterion,
    DecideReport,
    run_decide,
)


def _controlled_run(
    *,
    scores: dict[tuple[str, str], float],
    criteria: list[Criterion],
    options: list[str] | None = None,
    evidence_variance: dict[tuple[str, str], float] | None = None,
) -> DecideReport:
    """Run decide with a monkey-patched score function for predictable results."""
    import lighthouse_ai.modes.decide as _mod

    opts = options or ["A", "B"]
    original_stub = _mod._stub_score

    def fake_stub(opt: str, crit: str) -> float:
        return scores.get((opt, crit), 0.5)

    _mod._stub_score = fake_stub
    try:
        return run_decide(
            "test question",
            options=opts,
            criteria=criteria,
            evidence_variance=evidence_variance,
        )
    finally:
        _mod._stub_score = original_stub


# ---------------------------------------------------------------------------
# New fields exist with safe defaults
# ---------------------------------------------------------------------------


def test_new_fields_default_when_no_variance():
    crits = [Criterion("c1", 1.0), Criterion("c2", 1.0)]
    scores = {
        ("A", "c1"): 0.9,
        ("A", "c2"): 0.9,
        ("B", "c1"): 0.1,
        ("B", "c2"): 0.1,
    }
    r = _controlled_run(scores=scores, criteria=crits)
    assert r.robust_to_weights is True
    assert r.robust_to_evidence is True
    assert r.contested_criteria == []
    assert r.decided_on_contested_evidence is False
    # Cells default variance 0.0 when nothing is contested.
    assert all(c.variance == 0.0 for c in r.cells)


def test_cell_variance_propagates_from_argument():
    crits = [Criterion("c1", 1.0), Criterion("c2", 1.0)]
    scores = {
        ("A", "c1"): 0.6,
        ("A", "c2"): 0.6,
        ("B", "c1"): 0.4,
        ("B", "c2"): 0.4,
    }
    r = _controlled_run(
        scores=scores,
        criteria=crits,
        evidence_variance={("A", "c1"): 0.3},
    )
    cell = next(c for c in r.cells if c.option == "A" and c.criterion == "c1")
    assert abs(cell.variance - 0.3) < 1e-9
    assert "c1" in r.contested_criteria
    assert "c2" not in r.contested_criteria


# ---------------------------------------------------------------------------
# Evidence perturbation narrows / flips an otherwise weight-robust winner
# ---------------------------------------------------------------------------


def test_contested_evidence_breaks_weight_robust_winner():
    """A wins on both criteria under every weighting (weight-robust), but the
    evidence on (A, c1) is contested: the worst-case corner flips the winner to
    B. So robust_to_weights stays True while robust_to_evidence becomes False."""
    crits = [Criterion("c1", 1.0), Criterion("c2", 1.0)]
    scores = {
        ("A", "c1"): 0.6,
        ("A", "c2"): 0.55,
        ("B", "c1"): 0.4,
        ("B", "c2"): 0.45,
    }
    # Baseline: A=0.575, B=0.425. Dropping either criterion still leaves A
    # ahead → no weight-flip. A 0.5 band on (A,c1) drives A's c1 to 0.1, making
    # A=0.325 < B=0.425 in the pessimistic corner.
    r = _controlled_run(
        scores=scores,
        criteria=crits,
        evidence_variance={("A", "c1"): 0.5},
    )
    assert r.winner == "A"
    assert r.robust_to_weights is True, "winner should survive every weight drop"
    assert r.robust_to_evidence is False, "contested evidence should flip the corner"


def test_robust_to_evidence_true_when_band_too_small_to_flip():
    """A small variance band that cannot overcome the margin leaves the winner
    robust on BOTH axes."""
    crits = [Criterion("c1", 1.0), Criterion("c2", 1.0)]
    scores = {
        ("A", "c1"): 0.9,
        ("A", "c2"): 0.9,
        ("B", "c1"): 0.1,
        ("B", "c2"): 0.1,
    }
    r = _controlled_run(
        scores=scores,
        criteria=crits,
        evidence_variance={("A", "c1"): 0.1},
    )
    assert r.winner == "A"
    assert r.robust_to_weights is True
    assert r.robust_to_evidence is True
    assert "c1" in r.contested_criteria  # still flagged contested


# ---------------------------------------------------------------------------
# Crux names contested evidence on a decisive criterion
# ---------------------------------------------------------------------------


def test_crux_mentions_contested_evidence_on_decisive_criterion():
    """The decisive criterion ('key') is ALSO contested → the crux must say the
    decision rests on disputed evidence."""
    crits = [Criterion("key", weight=4.0), Criterion("minor", weight=1.0)]
    scores = {
        ("A", "key"): 0.95,
        ("A", "minor"): 0.1,
        ("B", "key"): 0.1,
        ("B", "minor"): 0.95,
    }
    r = _controlled_run(
        scores=scores,
        criteria=crits,
        evidence_variance={("A", "key"): 0.2, ("B", "key"): 0.2},
    )
    assert r.winner == "A"
    key_sens = next(s for s in r.sensitivity if s.criterion == "key")
    assert key_sens.decisive is True
    assert key_sens.evidence_contested is True
    assert r.decided_on_contested_evidence is True
    low = r.crux.lower()
    assert "contested" in low, f"crux should flag contested evidence: {r.crux!r}"
    assert "key" in r.crux
    assert "Adjudicate" in r.crux


def test_crux_robust_but_contested_evidence_flips_is_named():
    """No weight-flip (weight-robust) but evidence perturbation flips: the crux
    should acknowledge the contested evidence rather than overclaim robustness."""
    crits = [Criterion("c1", 1.0), Criterion("c2", 1.0)]
    scores = {
        ("A", "c1"): 0.6,
        ("A", "c2"): 0.55,
        ("B", "c1"): 0.4,
        ("B", "c2"): 0.45,
    }
    r = _controlled_run(
        scores=scores,
        criteria=crits,
        evidence_variance={("A", "c1"): 0.5},
    )
    assert r.robust_to_weights is True
    assert r.robust_to_evidence is False
    low = r.crux.lower()
    assert "contested" in low, f"crux should flag contested evidence: {r.crux!r}"
    # Must not falsely claim the lead is robust across all scenarios.
    assert "across all weighting scenarios" not in low


def test_uncontested_decisive_crux_does_not_mention_contested():
    """Decisive criterion with NO variance → crux stays the plain decisive form
    (no spurious 'contested' wording)."""
    crits = [Criterion("key", weight=4.0), Criterion("minor", weight=1.0)]
    scores = {
        ("A", "key"): 0.95,
        ("A", "minor"): 0.1,
        ("B", "key"): 0.1,
        ("B", "minor"): 0.95,
    }
    r = _controlled_run(scores=scores, criteria=crits)
    assert "contested" not in r.crux.lower()
    assert "key" in r.crux


# ---------------------------------------------------------------------------
# Position confidence is discounted when the winner is not evidence-robust
# ---------------------------------------------------------------------------


def test_position_probability_discounted_when_not_evidence_robust():
    recorded = {}

    class FakeDB:
        pass

    import lighthouse_ai.verification.positions as positions

    crits = [Criterion("c1", 1.0), Criterion("c2", 1.0)]
    scores = {
        ("A", "c1"): 0.6,
        ("A", "c2"): 0.55,
        ("B", "c1"): 0.4,
        ("B", "c2"): 0.45,
    }
    orig = positions.record_position
    positions.record_position = lambda db, *, claim, probability: recorded.update(
        claim=claim, probability=probability
    )
    try:
        import lighthouse_ai.modes.decide as _mod

        original_stub = _mod._stub_score
        _mod._stub_score = lambda o, c: scores.get((o, c), 0.5)
        try:
            run_decide(
                "q",
                options=["A", "B"],
                criteria=crits,
                positions_db=FakeDB(),
                evidence_variance={("A", "c1"): 0.5},
            )
        finally:
            _mod._stub_score = original_stub
    finally:
        positions.record_position = orig
    assert 0.5 <= recorded["probability"] <= 0.95
