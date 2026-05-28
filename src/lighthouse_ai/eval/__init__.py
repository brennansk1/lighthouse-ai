"""Retrieval evaluation harness.

The #1 production gap is that retrieval quality is unmeasured: we ship a
hybrid search pipeline but have no numbers telling us whether it actually
surfaces the right documents. This package closes that gap with a tiny,
dependency-free harness:

  * :mod:`metrics` — pure, hand-checkable ranking metrics plus a
    deterministic faithfulness proxy (no LLM required).
  * :mod:`golden` — a small built-in golden set and an ``evaluate()`` that
    runs it end-to-end through the real ``HybridSearch`` pipeline and reports
    aggregate precision@5 / recall@5 / MRR.

The intent is a regression *instrument*: even with the stub HashEmbedder the
harness produces real numbers, so swapping in the production embedder later
turns the same harness into a quality gate.
"""

from __future__ import annotations

from .golden import (
    GoldenCase,
    GoldenSet,
    build_golden_set,
    build_index,
    evaluate,
)
from .metrics import (
    faithfulness,
    mean_metric,
    mrr,
    precision_at_k,
    recall_at_k,
)

__all__ = [
    "GoldenCase",
    "GoldenSet",
    "build_golden_set",
    "build_index",
    "evaluate",
    "faithfulness",
    "mean_metric",
    "mrr",
    "precision_at_k",
    "recall_at_k",
]
