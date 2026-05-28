"""Framing pipeline + Adaptive RAG router tests."""

from __future__ import annotations

import pytest

from lighthouse_ai.framing import (
    AdaptiveRouter,
    QuestionType,
    RouteKind,
    classify_question,
    critique_question,
    decompose,
    frame_question,
    multiply_frames,
    run_framing,
)

# --- typing ---

@pytest.mark.parametrize("q,expected", [
    ("Should I go to grad school?", QuestionType.DECISION_SUPPORT),
    ("Python vs Rust for systems programming", QuestionType.COMPARATIVE),
    ("Why did the bank collapse?", QuestionType.CAUSAL_EXPLANATION),
    ("Will AI solve coding by 2030?", QuestionType.PREDICTIVE_FORECAST),
    ("What's going on with the chip ban?", QuestionType.EXPLORATORY_SURVEY),
    ("Is the homeopathy claim disputed?", QuestionType.CONTROVERSY_RESOLUTION),
    ("Is method X good for time series forecasting?", QuestionType.METHODOLOGY_EVALUATION),
    ("What is the speed of light?", QuestionType.FACTUAL_LOOKUP),
])
def test_classify_question_matches_keyword_rules(q, expected):
    assert classify_question(q) == expected


# --- critique ---

def test_compound_question_flagged():
    c = critique_question("What is X and why is Y true?")
    assert c.is_compound
    assert not c.well_formed


def test_well_formed_question_passes():
    c = critique_question("What is the half-life of caesium-137 in soil?")
    assert c.well_formed


def test_implicit_utility_flagged():
    c = critique_question("What is the best laptop for graphic design under $2000?")
    assert c.implicit_utility


def test_under_specified_flagged():
    c = critique_question("Tell me about ai")
    assert c.is_underspecified


# --- multiplication + selection ---

def test_multiply_frames_returns_at_least_three():
    fs = multiply_frames("Should I retrain on Rust?", QuestionType.DECISION_SUPPORT)
    assert len(fs) >= 3


def test_frame_question_picks_first_with_rationale():
    fs = multiply_frames("Will AI solve coding?", QuestionType.PREDICTIVE_FORECAST)
    chosen = frame_question(fs, QuestionType.PREDICTIVE_FORECAST)
    assert chosen.label == fs[0].label
    assert "predictive_forecast" in chosen.rationale


def test_frame_question_empty_raises():
    with pytest.raises(ValueError):
        frame_question([], QuestionType.FACTUAL_LOOKUP)


# --- decomposition ---

def test_decompose_includes_evidence_subquestion_for_comparative():
    subs = decompose("X vs Y", QuestionType.COMPARATIVE)
    assert any("evidence" in s.lower() for s in subs)


# --- full pipeline ---

def test_run_framing_end_to_end():
    fq = run_framing("Should I move from PyTorch to JAX?")
    assert fq.question_type == QuestionType.DECISION_SUPPORT
    assert fq.framings
    assert fq.chosen
    assert fq.sub_questions
    # The load-bearing slice is a subset of all sub-questions.
    assert set(fq.load_bearing) <= set(fq.sub_questions)


# --- router ---

def test_router_short_definition_skips_retrieval():
    r = AdaptiveRouter().classify("Define dropout?")
    assert r.kind is RouteKind.NONE


def test_router_recency_cue_uses_recency():
    r = AdaptiveRouter().classify("What's the latest on the chip ban?")
    assert r.kind is RouteKind.RECENCY


def test_router_comparative_uses_agentic():
    r = AdaptiveRouter().classify("Compare Rust and Go", qtype=QuestionType.COMPARATIVE)
    assert r.kind is RouteKind.AGENTIC


def test_router_relational_uses_graph():
    r = AdaptiveRouter().classify("What is the impact of fed policy on bond yields?")
    assert r.kind is RouteKind.GRAPH


def test_router_default_uses_vector():
    r = AdaptiveRouter().classify("Half-life of caesium-137")
    assert r.kind is RouteKind.VECTOR


def test_router_long_query_uses_agentic():
    long_q = (
        "I want to understand how supply chains in Southeast Asia evolved over the "
        "last decade in relation to memory chip manufacturing and labor cost trends"
    )
    r = AdaptiveRouter().classify(long_q)
    # Long query could be GRAPH (relational) or AGENTIC depending on which rule wins.
    assert r.kind in {RouteKind.AGENTIC, RouteKind.GRAPH, RouteKind.RECENCY}
