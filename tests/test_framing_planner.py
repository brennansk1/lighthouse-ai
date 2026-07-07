"""Zone T — planner LLM as the PRIMARY framing path (gap #10, #13, #21).

These tests assert the primary/fallback flip:
  * gateway=None  -> deterministic keyword/template baseline (offline-stable).
  * fake gateway returning canned planner JSON -> LLM drives typing, frames,
    sub-questions, and load-bearing flagging.
  * malformed/failed planner output -> graceful fallback to heuristic, no crash.
  * router uses the LLM route when a gateway is present, else the rules.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from lighthouse_ai.framing import (
    AdaptiveRouter,
    QuestionType,
    RouteKind,
    classify_question,
    run_framing,
)
from lighthouse_ai.framing.pipeline import _run_framing_deterministic

# --- helpers ----------------------------------------------------------------


def _planner_gw(payload: dict) -> MagicMock:
    """Fake gateway whose planner call returns ``payload`` as JSON text."""
    gw = MagicMock()
    gw.complete.return_value = MagicMock(text=json.dumps(payload))
    return gw


def _full_payload(**over) -> dict:
    base = {
        "question_type": "comparative",
        "critique": {
            "well_formed": True,
            "is_compound": False,
            "has_presupposition": False,
            "is_underspecified": False,
            "implicit_utility": False,
            "notes": ["LLM note"],
        },
        "framings": [
            {"label": "L1", "statement": "frame one", "rationale": "r1"},
            {"label": "L2", "statement": "frame two", "rationale": "r2"},
        ],
        "chosen_label": "L2",
        "sub_questions": [
            "What does the LLM say drives it?",
            "What evidence is decisive?",
        ],
        "load_bearing": ["What evidence is decisive?"],
    }
    base.update(over)
    return base


# --- (1) gateway=None is byte-for-byte the deterministic baseline -----------

_KNOWN_CASES = [
    ("Should I move from PyTorch to JAX?", QuestionType.DECISION_SUPPORT),
    ("Compare Python vs Rust for systems programming", QuestionType.COMPARATIVE),
    ("Why did the bank collapse?", QuestionType.CAUSAL_EXPLANATION),
    ("Will AI solve coding by 2030?", QuestionType.PREDICTIVE_FORECAST),
    ("What is the speed of light?", QuestionType.FACTUAL_LOOKUP),
]


@pytest.mark.parametrize("q,expected_type", _KNOWN_CASES)
def test_gateway_none_matches_deterministic_baseline(q, expected_type):
    fq = run_framing(q)  # no gateway
    assert fq.question_type == expected_type
    # Identical to calling the deterministic path directly (no behaviour change).
    det = _run_framing_deterministic(q)
    assert fq == det


def test_classify_question_none_is_keyword():
    # No gateway -> pure keyword classifier, unchanged from before.
    assert classify_question("Python vs Rust") == QuestionType.COMPARATIVE
    assert classify_question("What is the speed of light?") == QuestionType.FACTUAL_LOOKUP


# --- (2) canned planner JSON drives the whole frame -------------------------


def test_planner_drives_typing_frames_subs_and_load_bearing():
    payload = _full_payload()
    gw = _planner_gw(payload)
    # A question the KEYWORD classifier would call FACTUAL_LOOKUP, to prove the
    # LLM's "comparative" is what wins.
    fq = run_framing("Tell me about widgets", gateway=gw, job_id="j1")

    # planner role was used
    assert gw.complete.call_args[0][0] == "planner"

    # typing came from the LLM, not the keyword fallback
    assert fq.question_type == QuestionType.COMPARATIVE

    # frames came from the LLM (its labels), and chosen honours chosen_label
    assert [f.label for f in fq.framings] == ["L1", "L2"]
    assert fq.chosen.label == "L2"

    # sub-questions from the LLM
    assert fq.sub_questions == [
        "What does the LLM say drives it?",
        "What evidence is decisive?",
    ]

    # load-bearing flagging is LLM-led and a subset of sub_questions
    assert fq.load_bearing == ["What evidence is decisive?"]
    assert set(fq.load_bearing) <= set(fq.sub_questions)

    # critique propagated from the LLM
    assert fq.critique.notes == ["LLM note"]


def test_classify_question_uses_llm_when_gateway_present():
    gw = MagicMock()
    gw.complete.return_value = MagicMock(text="causal_explanation")
    # keyword would say FACTUAL_LOOKUP; LLM wins
    assert classify_question("Tell me about widgets", gateway=gw) == QuestionType.CAUSAL_EXPLANATION
    assert gw.complete.call_args[0][0] == "planner"


def test_classify_question_tolerates_decorated_llm_token():
    gw = MagicMock()
    gw.complete.return_value = MagicMock(text="-> comparative.")
    assert classify_question("anything", gateway=gw) == QuestionType.COMPARATIVE


def test_planner_load_bearing_falls_back_to_heuristic_when_omitted():
    # No load_bearing field -> heuristic over the LLM's own sub-questions.
    payload = _full_payload()
    del payload["load_bearing"]
    gw = _planner_gw(payload)
    fq = run_framing("anything", gateway=gw)
    assert fq.load_bearing == ["What evidence is decisive?"]  # matches 'evidence'


# --- (3) malformed / failed LLM output -> graceful fallback -----------------


def test_malformed_json_falls_back_to_heuristic():
    gw = MagicMock()
    gw.complete.return_value = MagicMock(text="this is not json {{{")
    fq = run_framing("Will AI replace coders by 2030?", gateway=gw)
    # deterministic keyword path took over
    assert fq.question_type == QuestionType.PREDICTIVE_FORECAST
    assert fq.sub_questions


def test_gateway_exception_falls_back_to_heuristic():
    gw = MagicMock()
    gw.complete.side_effect = RuntimeError("planner down")
    fq = run_framing("Compare Python vs Rust", gateway=gw)
    assert fq.question_type == QuestionType.COMPARATIVE
    assert fq == _run_framing_deterministic("Compare Python vs Rust")


def test_empty_framings_falls_back_to_heuristic():
    payload = _full_payload(framings=[])
    gw = _planner_gw(payload)
    fq = run_framing("Why did X happen?", gateway=gw)
    # falls back; keyword sees 'why' -> causal_explanation
    assert fq.question_type == QuestionType.CAUSAL_EXPLANATION


def test_bad_type_value_falls_back_to_heuristic():
    payload = _full_payload(question_type="not_a_real_type")
    gw = _planner_gw(payload)
    fq = run_framing("Why did X happen?", gateway=gw)
    assert fq.question_type == QuestionType.CAUSAL_EXPLANATION


def test_classify_question_bad_llm_token_falls_back():
    gw = MagicMock()
    gw.complete.return_value = MagicMock(text="banana")
    # unknown token -> keyword fallback (comparative)
    assert classify_question("Python vs Rust", gateway=gw) == QuestionType.COMPARATIVE


# --- (4) router: LLM primary, rules fallback --------------------------------


def test_router_uses_llm_route_when_gateway_present():
    gw = MagicMock()
    gw.complete.return_value = MagicMock(text="graph")
    r = AdaptiveRouter().classify("Half-life of caesium-137", gateway=gw)
    # rules alone would say VECTOR; LLM says GRAPH
    assert r.kind is RouteKind.GRAPH
    assert gw.complete.call_args[0][0] == "planner"


def test_router_falls_back_to_rules_without_gateway():
    r = AdaptiveRouter().classify("Half-life of caesium-137")
    assert r.kind is RouteKind.VECTOR


def test_router_falls_back_on_llm_failure():
    gw = MagicMock()
    gw.complete.side_effect = RuntimeError("planner down")
    r = AdaptiveRouter().classify("What's the latest on the chip ban?", gateway=gw)
    assert r.kind is RouteKind.RECENCY  # rule-based recency cue


def test_router_falls_back_on_bad_llm_token():
    gw = MagicMock()
    gw.complete.return_value = MagicMock(text="nonsense-token")
    r = AdaptiveRouter().classify("Define dropout?", gateway=gw)
    assert r.kind is RouteKind.NONE  # rules: short definition
