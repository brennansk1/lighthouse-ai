"""Offline research-quality benchmark tests (no real LLM).

The headline assertion: the grounding gate catches a planted hallucination that a
fluent frontier model would repeat. Plus structural scoring of an artifact.
"""

from __future__ import annotations

from lighthouse_ai.eval.research_benchmark import (
    grounding_catches_hallucination,
    run,
    score_artifact,
)


def test_grounding_gate_catches_planted_hallucination():
    card = grounding_catches_hallucination()
    assert card.checks["fabricated_citation_caught"]
    assert card.checks["high_stakes_gate_fails_on_fabrication"]
    assert card.checks["triangulated_claim_detected"]
    assert card.passed


def test_run_returns_scorecard():
    out = run()
    assert out["grounding_gate"]["passed"] is True


def test_score_artifact_flags_missing_quality_signals():
    # A bare artifact with no provenance/adversarial/coverage must NOT pass.
    card = score_artifact({"question": "x", "citation_coverage": 0.2})
    assert card.passed is False
    assert card.checks["has_provenance"] is False
    assert card.checks["adversarial_ran"] is False


def test_score_artifact_rewards_complete_artifact():
    body = {
        "depth": "thorough",
        "citation_coverage": 0.97,
        "entailment_coverage": 0.92,
        "adversarial": {"contested": 0},
        "coverage": 1.0,
        "contested_claims": [],
        "provenance": {"backend": "ollama", "metrics": {}},
    }
    card = score_artifact(body, depth="thorough")
    assert card.checks["has_provenance"]
    assert card.checks["backend_real"]
    assert card.checks["adversarial_ran"]
    assert card.checks["coverage_ran"]
    assert card.checks["citation_coverage_>=0.95"]
    assert card.checks["depth_honored"]
    assert card.passed
