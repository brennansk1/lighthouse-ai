"""Reciprocal Rank Fusion — design §14.4 fusion step.

Per Cormack et al. 2009, the RRF score for an item across multiple rankings
is ``sum( 1 / (k + rank_i) )`` where ``rank_i`` is the 1-based rank in
ranking ``i``. ``k=60`` is the default used by Elastic, Qdrant, and the
original paper.
"""

from __future__ import annotations

from collections.abc import Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    *,
    k: int = 60,
) -> list[tuple[str, float]]:
    """Fuse multiple ranked lists into one. Returns (id, score) sorted desc."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
