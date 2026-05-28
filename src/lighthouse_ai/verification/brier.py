"""Brier score for calibration tracking."""

from __future__ import annotations

from collections.abc import Iterable


def brier_score(probability: float, outcome: bool) -> float:
    """Squared error between stated probability and 0/1 outcome.

    Lower is better. Range [0, 1]. A probability of 0.5 on a binary outcome
    always scores 0.25 regardless of which way the outcome falls.
    """
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f"probability out of [0,1]: {probability}")
    o = 1.0 if outcome else 0.0
    return (probability - o) ** 2


def mean_brier(items: Iterable[tuple[float, bool]]) -> float:
    """Mean Brier across a series of (probability, outcome) pairs."""
    items_list = list(items)
    if not items_list:
        return 0.0
    return sum(brier_score(p, o) for p, o in items_list) / len(items_list)
