"""Entailment-based faithfulness checking (Sprint 30).

Wraps MiniCheck-Flan-T5-Large (lytang/MiniCheck-Flan-T5-Large, MIT, 770M params)
as the *only* real entailment scorer.

MiniCheck is lazy-imported so the module is safe to import with zero extra deps
installed — when no scorer is available, ``score_claim`` returns ``None``
("unchecked") rather than a fabricated pass.  Consumers MUST treat ``None`` as
"not verified" and never count it toward entailment coverage; a high-stakes
claim with no scorer must not silently pass.

Usage:
    from lighthouse_ai.verification.entailment import score_claim, available
    if available():
        s = score_claim(claim_text, grounding_chunk_text)
        # None = unchecked (no scorer); 0.0 = contradicted; 1.0 = fully entailed
"""

from __future__ import annotations

import importlib.util
from typing import Any

MINICHECK_THRESHOLD: float = 0.5

# Module-level cache for the scorer instance (lazy init on first call).
_scorer: object | None = None
_scorer_kind: str | None = None  # "minicheck" | None


def _minicheck_available() -> bool:
    return importlib.util.find_spec("minicheck") is not None


def available() -> bool:
    """Return True iff a real entailment scorer (MiniCheck) is importable."""
    return _minicheck_available()


def _get_scorer() -> tuple[object | None, str | None]:
    """Lazy-load and cache the best available scorer.

    Returns (scorer_object, kind) where kind is "minicheck" or None.
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

    return _scorer, _scorer_kind


def score_claim(claim: str, grounding: str) -> float | None:
    """Score how well the grounding chunk entails the claim.

    Returns a float in [0.0, 1.0] — 1.0 means fully entailed; 0.0 means
    contradicted or unsupported.  Returns ``None`` ("unchecked") when no real
    scorer is available, so consumers can refuse to count the claim as entailed
    rather than fabricating a pass.
    """
    scorer, kind = _get_scorer()
    if scorer is None or kind is None:
        return None

    _scorer_any: Any = scorer
    try:
        if kind == "minicheck":
            _, scores, _, _ = _scorer_any.score(docs=[grounding], claims=[claim])
            return float(scores[0])
    except Exception:
        return None

    return None


def score_claims(claims: list[str], groundings: list[str]) -> list[float | None]:
    """Batch entailment scoring.

    Each claim is scored against the corresponding grounding (parallel lists).
    Shorter list determines length.  Elements are ``None`` when unchecked.
    """
    return [score_claim(c, g) for c, g in zip(claims, groundings)]
