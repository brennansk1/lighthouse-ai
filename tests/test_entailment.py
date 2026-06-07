"""Entailment gate honesty (A4).

The entailment scorer must fail HONEST: when no real scorer is installed it
returns ``None`` ("unchecked") rather than a fabricated ``1.0`` pass, and every
consumer must refuse to count an unchecked claim as entailed.
"""

from __future__ import annotations

import importlib.util

from lighthouse_ai.verification import entailment
from lighthouse_ai.verification.discipline import check

_MINICHECK_INSTALLED = importlib.util.find_spec("minicheck") is not None


# --- no scorer → unchecked, never a fabricated pass ---

def test_score_claim_returns_none_when_no_scorer(monkeypatch):
    """With no real scorer, score_claim returns None (unchecked), not 1.0."""
    monkeypatch.setattr(entailment, "_get_scorer", lambda: (None, None))
    assert entailment.score_claim("the sky is blue", "the sky is blue") is None


def test_score_claims_returns_none_list_when_no_scorer(monkeypatch):
    monkeypatch.setattr(entailment, "_get_scorer", lambda: (None, None))
    out = entailment.score_claims(["a", "b"], ["x", "y"])
    assert out == [None, None]


def test_available_false_without_minicheck():
    """available() reflects the real scorer only — no cosine HHEM fallback."""
    if _MINICHECK_INSTALLED:
        assert entailment.available() is True
    else:
        assert entailment.available() is False


def test_no_cosine_hhem_branch():
    """The HHEM cosine branch is gone; 'hhem' is never a scorer kind."""
    import inspect

    src = inspect.getsource(entailment)
    assert "hhem" not in src.lower()
    assert "encode(" not in src
    assert "_hhem_available" not in src


# --- discipline consumer: unchecked must not inflate coverage ---

def test_discipline_entailment_checked_false_without_scorer(monkeypatch):
    """No scorer → entailment_checked False, coverage stays 0.0 (not 100%)."""
    monkeypatch.setattr(entailment, "available", lambda: False)

    class _Chunk:
        text = "Drug X reduced mortality by 30% in the trial."

    rep = check(
        "Drug X reduced mortality by 30% [1].",
        evidence_chunks=[_Chunk()],
    )
    assert rep.entailment_checked is False
    # Unchecked must NOT be reported as fully entailed.
    assert rep.entailment_coverage == 0.0


def test_high_stakes_claim_with_no_scorer_does_not_silently_pass(monkeypatch):
    """A high-stakes sourced claim with no scorer must not pass *silently*.

    The faithfulness gap is surfaced truthfully (entailment_checked False +
    an explicit note) so a caller can never mistake an unverified synthesis for
    a "fully entailed" one.
    """
    monkeypatch.setattr(entailment, "available", lambda: False)

    class _Chunk:
        text = "Drug X reduced mortality by 30% in the trial."

    rep = check(
        "Drug X reduced mortality by 30% [1]. Drug X is safe [1].",
        min_coverage=0.0,
        high_stakes=True,
        evidence_chunks=[_Chunk()],
    )
    assert rep.entailment_checked is False
    # Not silent: the unchecked-faithfulness gap is surfaced in notes, and
    # coverage is not inflated to a fabricated 100%.
    assert rep.entailment_coverage == 0.0
    assert any("unchecked" in n for n in rep.notes)


# --- discipline consumer: a contradicted claim (fake scorer) scores low ---

def test_discipline_contradicted_claim_scores_below_threshold(monkeypatch):
    """With a fake scorer, a contradicted claim is NOT counted as entailed."""

    def _fake_score(claim: str, grounding: str):
        # Mortality went UP in the grounding; the claim says it went down.
        if "reduced" in claim and "increased" in grounding:
            return 0.05
        return 0.95

    monkeypatch.setattr(entailment, "available", lambda: True)
    monkeypatch.setattr(entailment, "score_claim", _fake_score)

    class _Chunk:
        text = "Drug X increased mortality by 30% in the trial."

    rep = check(
        "Drug X reduced mortality by 30% [1].",
        evidence_chunks=[_Chunk()],
    )
    assert rep.entailment_checked is True
    # The single sourced claim is contradicted → 0% entailed, not a fake pass.
    assert rep.entailment_coverage == 0.0


def test_score_claim_with_fake_minicheck_scorer(monkeypatch):
    """A monkeypatched MiniCheck scorer routes through the real code path."""

    class _FakeMiniCheck:
        def score(self, docs, claims):
            # Contradiction → low; otherwise high.
            score = 0.02 if "not" in claims[0] else 0.91
            return None, [score], None, None

    monkeypatch.setattr(entailment, "_get_scorer",
                        lambda: (_FakeMiniCheck(), "minicheck"))

    assert entailment.score_claim("the sky is blue", "the sky is blue") == 0.91
    contradicted = entailment.score_claim("the sky is not blue", "the sky is blue")
    assert contradicted is not None and contradicted < entailment.MINICHECK_THRESHOLD
