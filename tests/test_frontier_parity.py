"""Offline tests for the frontier-parity grader (eval/frontier_parity.py).

Deterministic — no LLM, no backend. Proves the auto-grade rewards a
well-grounded, honest artifact, penalizes a thin/dishonest one, catches a
fabricated citation, scales breadth with depth, and that the frontier
head-to-head math (deltas, wins, trust-wedge) is correct.
"""

from __future__ import annotations

from lighthouse_ai.eval.frontier_parity import (
    BENCHMARK_QUESTIONS,
    FrontierScore,
    compare,
    grade_artifact,
    render_report,
)


def _good_artifact(depth="thorough"):
    """A grounded, stress-tested, honest artifact — should score high."""
    return {
        "question": "Q?",
        "depth": depth,
        "sections": [
            {
                "title": "A",
                "sub_question": "a?",
                "body": "Finding a.",
                "citations": [1, 2],
                "is_load_bearing": True,
            },
            {
                "title": "B",
                "sub_question": "b?",
                "body": "Finding b.",
                "citations": [3, 4, 5],
                "is_load_bearing": True,
            },
        ],
        "open_questions": ["What about X?"],
        "ruled_out": ["Y"],
        "coverage": 0.9,
        "coverage_gaps": [],
        "adversarial": {"tested": 2, "survived": 2, "contested": 0},
        "contested_claims": [],
        "acquisition": {"documents_acquired": 30, "blocked_chunks": 0},
        "provenance": {
            "backend": "ollama",
            "metrics": {
                "citation_coverage": 0.97,
                "entailment_coverage": 0.92,
                "fabricated_citations": 0,
            },
        },
    }


def _thin_artifact():
    """A fluent-but-ungrounded artifact — no citations, no stress test, no
    admitted open questions. The frontier failure mode."""
    return {
        "question": "Q?",
        "depth": "thorough",
        "sections": [
            {
                "title": "A",
                "sub_question": "a?",
                "body": "Confident prose with no sources.",
                "citations": [],
                "is_load_bearing": True,
            }
        ],
        "open_questions": [],
        "ruled_out": [],
    }


def test_good_artifact_scores_high():
    score = grade_artifact(_good_artifact())
    assert score.overall >= 0.85
    d = score.dimensions
    assert d["grounding"] >= 0.9
    assert d["citation_verifiability"] == 1.0
    assert d["contradiction_honesty"] >= 0.8  # adversarial + contested + coverage
    assert d["open_question_honesty"] == 1.0
    assert d["breadth"] == 0.2  # 5 distinct sources ÷ 25 (thorough) target


def test_thin_artifact_scores_low():
    score = grade_artifact(_thin_artifact())
    assert score.overall <= 0.15
    d = score.dimensions
    assert d["grounding"] == 0.0
    assert d["citation_verifiability"] == 0.0  # nothing cited → nothing verifiable
    assert d["contradiction_honesty"] == 0.0
    assert d["open_question_honesty"] == 0.0


def test_breadth_scales_with_depth():
    """Same source count is held to a higher bar at Deep than Quick."""
    art = _good_artifact(depth="quick")
    art["sections"] = [
        {
            "title": "A",
            "sub_question": "a?",
            "body": "x",
            "citations": [1, 2, 3],
            "is_load_bearing": True,
        }
    ]
    quick = grade_artifact(art)
    art["depth"] = "deep"
    deep = grade_artifact(art)
    # 3 sources: 3/5 at quick vs 3/40 at deep — quick scores much higher on breadth.
    assert quick.dimensions["breadth"] > deep.dimensions["breadth"]
    assert quick.dimensions["breadth"] == 0.6


def test_fabricated_citation_tanks_verifiability():
    art = _good_artifact()
    art["provenance"]["metrics"]["fabricated_citations"] = 2
    score = grade_artifact(art)
    assert score.dimensions["citation_verifiability"] < 1.0


def test_grounding_prefers_entailment_then_falls_back_to_citation():
    art = _good_artifact()
    art["provenance"]["metrics"]["entailment_coverage"] = 0
    art["provenance"]["metrics"]["citation_coverage"] = 0.8
    assert grade_artifact(art).dimensions["grounding"] == 0.8


def test_open_question_partial_credit_for_ruled_out_only():
    art = _thin_artifact()
    art["ruled_out"] = ["Z"]
    assert grade_artifact(art).dimensions["open_question_honesty"] == 0.6


def test_frontier_score_normalizes_1_to_5():
    fs = FrontierScore(
        breadth=5,
        grounding=1,
        citation_verifiability=3,
        contradiction_honesty=5,
        open_question_honesty=1,
    )
    n = fs.normalized()
    assert n["breadth"] == 1.0
    assert n["grounding"] == 0.0
    assert n["citation_verifiability"] == 0.5


def test_compare_computes_deltas_wins_and_trust_wedge():
    lh = grade_artifact(_good_artifact())
    # Frontier: fluent + broad but weak grounding/verifiability (the usual shape).
    fr = FrontierScore(
        breadth=5,
        grounding=3,
        citation_verifiability=2,
        contradiction_honesty=3,
        open_question_honesty=2,
        model="claude",
    )
    cmp = compare(lh, fr)
    assert cmp["frontier"]["model"] == "claude"
    # Lighthouse should win the two trust columns.
    assert cmp["wins"]["grounding"] == "lighthouse"
    assert cmp["wins"]["citation_verifiability"] == "lighthouse"
    assert cmp["holds_trust_wedge"] is True


def test_compare_without_frontier_returns_lighthouse_only():
    cmp = compare(grade_artifact(_good_artifact()))
    assert "frontier" not in cmp
    assert "lighthouse" in cmp


def test_trust_wedge_lost_when_frontier_grounding_higher():
    # A degraded Lighthouse run (mock-ish: no entailment, low citation coverage).
    art = _thin_artifact()
    lh = grade_artifact(art)
    fr = FrontierScore(
        breadth=5,
        grounding=5,
        citation_verifiability=5,
        contradiction_honesty=5,
        open_question_honesty=5,
    )
    assert compare(lh, fr)["holds_trust_wedge"] is False


def test_render_report_table_has_a_row_per_question():
    results = [
        {"question": "Q1 about coffee", "comparison": compare(grade_artifact(_good_artifact()))},
        {
            "question": "Q2 about LLMs",
            "comparison": compare(grade_artifact(_thin_artifact()), FrontierScore(3, 3, 3, 3, 3)),
        },
    ]
    md = render_report(results)
    assert "Frontier-parity report" in md
    assert "Q1 about coffee" in md
    assert "Q2 about LLMs" in md
    assert md.count("\n|") >= 4  # header + separator + 2 rows


def test_benchmark_questions_present():
    assert len(BENCHMARK_QUESTIONS) == 5
    assert all(isinstance(q, str) and len(q) > 20 for q in BENCHMARK_QUESTIONS)
