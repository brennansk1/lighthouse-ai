"""Adaptive RAG router (§14.5).

Classifies a query into one of five retrieval strategies:
  * ``vector`` — single dense+sparse retrieval (simple lookups).
  * ``agentic`` — multi-step ReAct-style retrieval (relational queries).
  * ``graph`` — LightRAG cross-document synthesis.
  * ``recency`` — date-filtered vector with recency weighting.
  * ``none`` — skip retrieval; answer from parametric knowledge.

Sprint 8 ships a rule-based router. Production fine-tunes a DistilBERT-class
classifier on the Adaptive-RAG dataset (Jeong et al.) and plugs it in via
:meth:`AdaptiveRouter.classify`.
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


class AdaptiveRouter:
    """Pluggable router. Default rules emulate the Adaptive-RAG classifier."""

    def classify(self, query: str, *, qtype: QuestionType | None = None) -> AdaptiveRoute:
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
