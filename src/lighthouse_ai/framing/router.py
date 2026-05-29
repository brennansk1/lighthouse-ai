"""Adaptive RAG router (§14.5).

Classifies a query into one of five retrieval strategies:
  * ``vector`` — single dense+sparse retrieval (simple lookups).
  * ``agentic`` — multi-step ReAct-style retrieval (relational queries).
  * ``graph`` — LightRAG cross-document synthesis.
  * ``recency`` — date-filtered vector with recency weighting.
  * ``none`` — skip retrieval; answer from parametric knowledge.

When a gateway is supplied, :meth:`AdaptiveRouter.classify` uses an LLM
few-shot classifier on the ``planner`` role as the PRIMARY route picker, with
the rule-based router as the deterministic FALLBACK (used when no gateway is
given or the LLM call/parse fails). A fine-tuned DistilBERT-class classifier on
the Adaptive-RAG dataset (Jeong et al.) is the documented later upgrade — we do
NOT add a training dependency now.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .pipeline import QuestionType


class RouteKind(str, Enum):
    VECTOR = "vector"
    AGENTIC = "agentic"
    GRAPH = "graph"
    RECENCY = "recency"
    NONE = "none"


@dataclass(frozen=True)
class AdaptiveRoute:
    kind: RouteKind
    reason: str
    confidence: float  # 0..1; production: classifier probability


_DATE_PATTERNS = [
    re.compile(r"\b20\d{2}\b"),
    re.compile(r"\b(today|yesterday|this week|this month|recent|latest|"
               r"current|now)\b", re.IGNORECASE),
]
_RELATIONAL_PATTERNS = [
    re.compile(r"\b(between|across|compared with|relationship|"
               r"impact of .* on|how does .* affect)\b", re.IGNORECASE),
]
_NO_RETRIEVAL_HINTS = re.compile(
    r"^(define|what is|what does|explain) +[a-z ]+\?$", re.IGNORECASE
)


_VALID_ROUTE_VALUES = {r.value for r in RouteKind}

_ROUTE_FEWSHOT = (
    "Define dropout? -> none\n"
    "What's the latest on the chip ban? -> recency\n"
    "Compare Rust and Go on memory safety -> agentic\n"
    "What is the impact of fed policy on bond yields? -> graph\n"
    "Half-life of caesium-137 -> vector\n"
)


class AdaptiveRouter:
    """Pluggable router. LLM few-shot is primary when a gateway is supplied;
    deterministic rules (emulating the Adaptive-RAG classifier) are the fallback."""

    def classify(self, query: str, *, qtype: QuestionType | None = None,
                 gateway=None, job_id: str | None = None) -> AdaptiveRoute:
        """Pick a retrieval route for ``query``.

        PRIMARY (gateway supplied): LLM few-shot classifier on the ``planner``
        role. FALLBACK (gateway None, or the call/parse fails): the deterministic
        keyword rules below — offline output is unchanged.
        """
        if gateway is not None:
            llm = self._classify_llm(query, qtype=qtype, gateway=gateway, job_id=job_id)
            if llm is not None:
                return llm
        return self._classify_rules(query, qtype=qtype)

    def _classify_llm(self, query: str, *, qtype: QuestionType | None,
                      gateway, job_id: str | None) -> AdaptiveRoute | None:
        """Few-shot LLM route classifier. Returns None on any failure so the
        caller falls back to the rule-based router — never raises."""
        try:
            prompt = (
                "Choose the best retrieval strategy for the query from this set:\n"
                "vector (single dense+sparse lookup), agentic (multi-step "
                "relational/comparative), graph (cross-document synthesis), "
                "recency (date-filtered, recent events), none (answer from "
                "parametric knowledge; short definitions).\n\n"
                "Examples:\n"
                f"{_ROUTE_FEWSHOT}\n"
                "Reply with ONLY the strategy token (no punctuation, no explanation).\n\n"
                f"{query.strip()} ->"
            )
            resp = gateway.complete("planner", prompt, job_id=job_id)
            token = resp.text.strip().lower().splitlines()[0].strip().strip(".")
            for part in re.split(r"[\s:>-]+", token):
                if part in _VALID_ROUTE_VALUES:
                    return AdaptiveRoute(RouteKind(part),
                                         "planner LLM few-shot route", 0.8)
            return None
        except Exception:
            return None

    def _classify_rules(self, query: str, *, qtype: QuestionType | None = None) -> AdaptiveRoute:
        text = query.strip()
        lowered = text.lower()

        if _NO_RETRIEVAL_HINTS.match(text) and len(text.split()) <= 6:
            return AdaptiveRoute(RouteKind.NONE,
                                 "short definition question — parametric likely sufficient",
                                 0.6)

        # Recency cues short-circuit to recency-weighted retrieval.
        if any(p.search(text) for p in _DATE_PATTERNS):
            return AdaptiveRoute(RouteKind.RECENCY,
                                 "date or recency cue present", 0.75)

        # Comparative / multi-entity → graph or agentic.
        if qtype is QuestionType.COMPARATIVE:
            return AdaptiveRoute(RouteKind.AGENTIC,
                                 "comparative typed question — multi-step lookup", 0.7)
        if any(p.search(lowered) for p in _RELATIONAL_PATTERNS):
            return AdaptiveRoute(RouteKind.GRAPH,
                                 "relational language — graph synthesis indicated", 0.65)

        # Long, exploratory → agentic ReAct.
        if len(text.split()) > 16:
            return AdaptiveRoute(RouteKind.AGENTIC,
                                 "long exploratory query — agentic loop indicated", 0.55)

        # Default.
        return AdaptiveRoute(RouteKind.VECTOR,
                             "default single-shot dense+sparse retrieval", 0.5)
