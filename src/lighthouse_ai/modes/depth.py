"""Research depth tiers → concrete engine knobs (see docs/research_depth_matrix.md).

Depth scales coverage and confidence, never trust. The grounding gate runs at
every tier; what changes here is how many rounds the engine runs, how much it
retrieves/fetches, and whether the adversarial + coverage-critic passes fire.

Tiers (display-layer names): Quick / Standard / Thorough / Deep. ``Deep`` is the
recursive question-tree tier (handled by the exhaustive engine) and is bounded by
a user budget, not a fixed round count.
"""

from __future__ import annotations

from typing import Any

#: Per-tier engine knobs. ``recursive`` marks the Deep tier (exhaustive engine).
DEPTH_TIERS: dict[str, dict[str, Any]] = {
    "quick": {
        "max_rounds": 2, "top_k": 4, "auto_fetch_max_results": 3,
        "high_stakes": False, "adversarial": False, "coverage_critic": False,
        "recursive": False,
    },
    "standard": {
        "max_rounds": 4, "top_k": 5, "auto_fetch_max_results": 5,
        "high_stakes": False, "adversarial": False, "coverage_critic": True,
        "recursive": False,
    },
    "thorough": {
        "max_rounds": 6, "top_k": 8, "auto_fetch_max_results": 8,
        "high_stakes": True, "adversarial": True, "coverage_critic": True,
        "recursive": False,
    },
    "deep": {
        "max_rounds": 12, "top_k": 10, "auto_fetch_max_results": 12,
        "high_stakes": True, "adversarial": True, "coverage_critic": True,
        "recursive": True,
    },
}

DEFAULT_TIER = "standard"

#: Accept display labels, legacy values, and a few synonyms.
_ALIASES = {
    "quick": "quick", "fast": "quick",
    "standard": "standard", "balanced": "standard", "normal": "standard",
    "thorough": "thorough", "exhaustive": "thorough", "deep-ish": "thorough",
    "deep": "deep", "professional": "deep", "overnight": "deep", "max": "deep",
}


def canonical_tier(name: str | None) -> str:
    """Normalize a depth label to a canonical tier key (defaults to standard)."""
    if not name:
        return DEFAULT_TIER
    return _ALIASES.get(str(name).strip().lower(), DEFAULT_TIER)


def resolve_depth(name: str | None) -> dict[str, Any]:
    """Return the engine-knob dict for a depth label. Always returns a copy."""
    tier = canonical_tier(name)
    knobs = dict(DEPTH_TIERS[tier])
    knobs["tier"] = tier
    return knobs
