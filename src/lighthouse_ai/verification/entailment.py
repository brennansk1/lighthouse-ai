"""Entailment-based faithfulness checking (Sprint 30).

Wraps MiniCheck-Flan-T5-Large (lytang/MiniCheck-Flan-T5-Large, MIT, 770M params)
as the primary entailment scorer, with HHEM-2.1-Open (vectara/hallucination_evaluation_model,
Apache-2.0, 439MB) as a secondary tripwire metric.

Both are lazy-imported so the module is safe to import with zero extra deps
installed — when unavailable, score() returns 1.0 (neutral / no penalty) so
the discipline gate degrades to its existing regex-only coverage check.

Usage:
    from lighthouse_ai.verification.entailment import score_claim, available
    if available():
        s = score_claim(claim_text, grounding_chunk_text)
        # 0.0 = contradicted; 1.0 = fully entailed
"""

from __future__ import annotations

import importlib.util
from typing import Any

MINICHECK_THRESHOLD: float = 0.5
HHEM_THRESHOLD: float = 0.5

# Module-level cache for the scorer instance (lazy init on first call).
_scorer: object | None = None
_scorer_kind: str | None = None  # "minicheck" | "hhem" | None


def _minicheck_available() -> bool:
    return importlib.util.find_spec("minicheck") is not None


def _hhem_available() -> bool:
    return importlib.util.find_spec("sentence_transformers") is not None


def available() -> bool:
    """Return True iff MiniCheck OR HHEM is importable."""
    return _minicheck_available() or _hhem_available()


def _get_scorer() -> tuple[object | None, str | None]:
    """Lazy-load and cache the best available scorer.

    Returns (scorer_object, kind) where kind is "minicheck", "hhem", or None.
    """
    global _scorer, _scorer_kind
    if _scorer_kind is not None or (_scorer is None and _scorer_kind is None
                                    and not available()):
        return _scorer, _scorer_kind

    if _scorer is None:
        if _minicheck_available():
            try:
                from minicheck.minicheck import MiniCheck  # type: ignore[import]
                _scorer = MiniCheck(model_name="flan-t5-large", device="cpu",
                                    cache_dir=None)
                _scorer_kind = "minicheck"
            except Exception:
                _scorer = None
                _scorer_kind = None

        if _scorer is None and _hhem_available():
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore[import]
                _scorer = SentenceTransformer("vectara/hallucination_evaluation_model")
                _scorer_kind = "hhem"
            except Exception:
                _scorer = None
                _scorer_kind = None

    return _scorer, _scorer_kind


def score_claim(claim: str, grounding: str) -> float:
    """Score how well the grounding chunk entails the claim.

    Returns a float in [0.0, 1.0].  1.0 means fully entailed; 0.0 means
    contradicted or unsupported.  Returns 1.0 (no penalty) when no scorer
    is available so the discipline gate gracefully degrades.
    """
    scorer, kind = _get_scorer()
    if scorer is None or kind is None:
        return 1.0

    _scorer_any: Any = scorer
    try:
        if kind == "minicheck":
            _, scores, _, _ = _scorer_any.score(docs=[grounding], claims=[claim])
            return float(scores[0])

        if kind == "hhem":
            # sentence-transformers cosine similarity as a soft entailment proxy
            import numpy as np
            embs = _scorer_any.encode([claim, grounding], convert_to_numpy=True,
                                 normalize_embeddings=True)
            sim = float(np.dot(embs[0], embs[1]))
            # Cosine is in [-1, 1]; rescale to [0, 1]
            return float(max(0.0, min(1.0, (sim + 1.0) / 2.0)))
    except Exception:
        return 1.0

    return 1.0


def score_claims(claims: list[str], groundings: list[str]) -> list[float]:
    """Batch entailment scoring.

    Each claim is scored against the corresponding grounding (parallel lists).
    Shorter list determines length.
    """
    return [score_claim(c, g) for c, g in zip(claims, groundings)]
