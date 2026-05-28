"""Question framing pipeline (§10).

Sprint 8 ships a deterministic, rule-based baseline so the surrounding
system has the contract right. Production swaps in:
  * A small classifier (DistilBERT or planner-model few-shot) for question typing.
  * A planner LLM for critique, frame multiplication, decomposition.
  * The Question Library lookup (golden_sets/framings.db) for warm-starting.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum


class QuestionType(str, Enum):
    FACTUAL_LOOKUP = "factual_lookup"
    COMPARATIVE = "comparative"
    CAUSAL_EXPLANATION = "causal_explanation"
    PREDICTIVE_FORECAST = "predictive_forecast"
    DECISION_SUPPORT = "decision_support"
    EXPLORATORY_SURVEY = "exploratory_survey"
    CONTROVERSY_RESOLUTION = "controversy_resolution"
    METHODOLOGY_EVALUATION = "methodology_evaluation"


@dataclass(frozen=True)
class QuestionCritique:
    well_formed: bool
    is_compound: bool
    has_presupposition: bool
    is_underspecified: bool
    implicit_utility: bool
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Framing:
    label: str
    statement: str
    rationale: str = ""


@dataclass(frozen=True)
class FramedQuestion:
    original: str
    question_type: QuestionType
    critique: QuestionCritique
    framings: list[Framing]
    chosen: Framing
    sub_questions: list[str] = field(default_factory=list)
    load_bearing: list[str] = field(default_factory=list)


# --- Typing ------------------------------------------------------

_TYPE_KEYWORDS: list[tuple[QuestionType, list[str]]] = [
    # Order matters: more specific rules come first.
    (QuestionType.DECISION_SUPPORT,      ["should i", "should we", "best choice", "what to do"]),
    (QuestionType.CONTROVERSY_RESOLUTION,["disputed", "controversial", "alleged", "true?"]),
    (QuestionType.METHODOLOGY_EVALUATION,["method", "approach", "technique", "good for"]),
    (QuestionType.EXPLORATORY_SURVEY,    ["what's going on", "what is happening",
                                           "landscape", "overview", "state of"]),
    (QuestionType.COMPARATIVE,           ["vs", "versus", "compare", "better than"]),
    (QuestionType.CAUSAL_EXPLANATION,    ["why", "cause", "led to", "because"]),
    (QuestionType.PREDICTIVE_FORECAST,   ["will", "forecast", "predict", "future", "by 20"]),
]


def classify_question(q: str) -> QuestionType:
    """Cheap keyword classifier; replaced by ML classifier in production."""
    text = q.lower().strip().rstrip("?")
    for qtype, keywords in _TYPE_KEYWORDS:
        for k in keywords:
            # Multi-word keywords match anywhere; single words use word boundaries.
            if " " in k:
                if k in text:
                    return qtype
            else:
                if re.search(rf"\b{re.escape(k)}\b", text):
                    return qtype
    return QuestionType.FACTUAL_LOOKUP


# --- Critique ----------------------------------------------------

_COMPOUND_RE = re.compile(r"\b(and|or)\s+(how|why|what|when|where|which)\b", re.IGNORECASE)
_PRESUPPOSITION_HINTS = ["why did", "given that", "since", "now that"]
_UTILITY_WORDS = ["best", "optimal", "good", "ideal", "right"]


def critique_question(q: str) -> QuestionCritique:
    notes: list[str] = []
    text = q.lower()

    is_compound = bool(_COMPOUND_RE.search(q))
    if is_compound:
        notes.append("compound: contains conjunction joining two question stems")

    has_pre = any(h in text for h in _PRESUPPOSITION_HINTS)
    if has_pre:
        notes.append("presupposition: question assumes the premise")

    is_under = len(text.split()) < 6 or "?" not in q
    if is_under:
        notes.append("under-specified: missing scope or constraints")

    implicit = any(re.search(rf"\b{w}\b", text) for w in _UTILITY_WORDS)
    if implicit:
        notes.append("implicit utility: 'best/optimal/good' needs a utility function")

    well_formed = not (is_compound or is_under)
    return QuestionCritique(
        well_formed=well_formed, is_compound=is_compound,
        has_presupposition=has_pre, is_underspecified=is_under,
        implicit_utility=implicit, notes=notes,
    )


# --- Frame multiplication ----------------------------------------

def multiply_frames(q: str, qtype: QuestionType) -> list[Framing]:
    """Return 3-5 alternative framings.

    The deterministic baseline produces framings keyed off the question
    type; production uses the planner LLM to draft them.
    """
    base = q.strip().rstrip("?")
    frames: list[Framing] = []
    if qtype is QuestionType.DECISION_SUPPORT:
        frames = [
            Framing("F1-NPV", f"What maximizes 5-year NPV under stated constraints in: {base}?"),
            Framing("F2-trajectory", f"What maximizes the long-run trajectory of: {base}?"),
            Framing("F3-downside", f"What minimizes downside risk for: {base}?"),
            Framing("F4-options", f"What preserves the most future options re: {base}?"),
        ]
    elif qtype is QuestionType.COMPARATIVE:
        frames = [
            Framing("F1-criteria", f"On what criteria do the options in '{base}' differ?"),
            Framing("F2-stakes", f"What are the stakes / failure modes of each option in '{base}'?"),
            Framing("F3-evidence", f"What evidence is decisive vs marginal for '{base}'?"),
        ]
    elif qtype is QuestionType.PREDICTIVE_FORECAST:
        frames = [
            Framing("F1-base-rate", f"What is the base rate / reference class for '{base}'?"),
            Framing("F2-drivers", f"What are the load-bearing drivers of '{base}'?"),
            Framing("F3-uncertainty", f"What uncertainty intervals are appropriate for '{base}'?"),
        ]
    else:
        frames = [
            Framing("F1-as-stated", base + "?"),
            Framing("F2-broader", f"What is the broader landscape around '{base}'?"),
            Framing("F3-narrower", f"What is the most specific decidable version of '{base}'?"),
        ]
    return frames


def frame_question(framings: list[Framing], qtype: QuestionType) -> Framing:
    """Default policy: pick F1 with a short rationale.

    Production uses the planner LLM with anchor context; for under-specified
    questions, the design says to run multiple framings in parallel or ask
    the user — that's wired in by the manager agent (later sprint).
    """
    if not framings:
        raise ValueError("no framings to choose from")
    first = framings[0]
    return Framing(first.label, first.statement,
                   rationale=f"default selection for {qtype.value}")


# --- Decomposition + validation ---------------------------------

def decompose(question: str, qtype: QuestionType) -> list[str]:
    """Produce 2-5 sub-questions whose union answers the parent."""
    base = question.strip().rstrip("?")
    if qtype is QuestionType.COMPARATIVE:
        return [
            f"What is the strongest case for each option in '{base}'?",
            f"What evidence would *change* the choice in '{base}'?",
            "On what dimensions do the options materially differ?",
        ]
    if qtype is QuestionType.PREDICTIVE_FORECAST:
        return [
            f"What is the base rate for outcomes like '{base}'?",
            "What are the load-bearing drivers?",
            "What uncertainty intervals does the evidence support?",
        ]
    if qtype is QuestionType.CAUSAL_EXPLANATION:
        return [
            f"What is the proximate cause of '{base}'?",
            "What are the contributing distal causes?",
            "What counterfactuals undermine the proposed cause?",
        ]
    if qtype is QuestionType.METHODOLOGY_EVALUATION:
        return [
            f"What is the track record of the method in '{base}'?",
            "What alternative methods exist and how do they compare?",
            "What are the documented failure modes?",
        ]
    return [
        f"What is established about '{base}'?",
        f"What is disputed about '{base}'?",
        f"What is unknown about '{base}'?",
    ]


def load_bearing_subquestions(subs: list[str]) -> list[str]:
    """Heuristic: questions containing 'evidence', 'cause', 'change', or 'driver'
    are usually load-bearing because their answers can flip the parent."""
    return [s for s in subs
            if re.search(r"\b(evidence|cause|change|drivers?)\b", s.lower())]


# --- Top-level driver -------------------------------------------

def _run_framing_deterministic(question: str) -> FramedQuestion:
    qtype = classify_question(question)
    critique = critique_question(question)
    framings = multiply_frames(question, qtype)
    chosen = frame_question(framings, qtype)
    subs = decompose(chosen.statement, qtype)
    return FramedQuestion(
        original=question, question_type=qtype, critique=critique,
        framings=framings, chosen=chosen,
        sub_questions=subs, load_bearing=load_bearing_subquestions(subs),
    )


def run_framing(question: str, *, gateway=None, job_id: str | None = None) -> FramedQuestion:
    """Frame a research question, optionally using the planner LLM.

    Falls back to deterministic keyword/template baseline when gateway is
    None, or when the LLM response cannot be parsed — so tests and offline
    mode are unaffected.
    """
    if gateway is not None:
        try:
            return _run_framing_llm(question, gateway=gateway, job_id=job_id)
        except Exception:
            pass
    return _run_framing_deterministic(question)


def _run_framing_llm(question: str, *, gateway, job_id: str | None) -> FramedQuestion:
    """Use the planner role to classify, frame, and decompose the question.

    The planner is instructed to return JSON matching the FramedQuestion schema.
    Any failure (network, bad JSON, empty fields) propagates to let the
    caller fall back to the deterministic baseline.
    """
    prompt = (
        "You are a research question analyst. Analyze this research question and "
        "respond with ONLY valid JSON (no markdown, no commentary) matching this schema:\n\n"
        "{\n"
        '  "question_type": "factual_lookup | comparative | causal_explanation | '
        'predictive_forecast | decision_support | exploratory_survey | '
        'controversy_resolution | methodology_evaluation",\n'
        '  "critique": {\n'
        '    "well_formed": true,\n'
        '    "is_compound": false,\n'
        '    "has_presupposition": false,\n'
        '    "is_underspecified": false,\n'
        '    "implicit_utility": false,\n'
        '    "notes": []\n'
        '  },\n'
        '  "framings": [\n'
        '    {"label": "F1-label", "statement": "reframed question", "rationale": "why"}\n'
        '  ],\n'
        '  "chosen_label": "F1-label",\n'
        '  "sub_questions": ["sub-question 1", "sub-question 2"]\n'
        "}\n\n"
        f"Research question: {question}"
    )
    resp = gateway.complete("planner", prompt, job_id=job_id)
    raw = resp.text.strip()
    # Strip markdown code fences that some models add
    if raw.startswith("```"):
        lines = raw.split("\n")
        # drop first line (```json or ```) and last line (```)
        inner = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        raw = inner.strip()
    data = json.loads(raw)  # raises on bad JSON
    qtype = QuestionType(data["question_type"])
    cd = data["critique"]
    critique = QuestionCritique(
        well_formed=bool(cd.get("well_formed", True)),
        is_compound=bool(cd.get("is_compound", False)),
        has_presupposition=bool(cd.get("has_presupposition", False)),
        is_underspecified=bool(cd.get("is_underspecified", False)),
        implicit_utility=bool(cd.get("implicit_utility", False)),
        notes=list(cd.get("notes", [])),
    )
    framings = [
        Framing(
            label=str(f["label"]),
            statement=str(f["statement"]),
            rationale=str(f.get("rationale", "")),
        )
        for f in data.get("framings", [])
    ]
    if not framings:
        raise ValueError("planner returned no framings")
    chosen_label = data.get("chosen_label", framings[0].label)
    chosen = next((f for f in framings if f.label == chosen_label), framings[0])
    subs = [str(s) for s in data.get("sub_questions", [])]
    if not subs:
        raise ValueError("planner returned no sub_questions")
    return FramedQuestion(
        original=question, question_type=qtype, critique=critique,
        framings=framings, chosen=chosen,
        sub_questions=subs, load_bearing=load_bearing_subquestions(subs),
    )
