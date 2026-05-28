"""Reflection cap (OpenHuman §3).

A tick emits at most ``MAX_REFLECTIONS_PER_TICK`` reflections — "the sweet spot
between useful surface and notification spam". When more candidates exist, keep
the highest-scored (by hotness, §2) and drop the rest at debug level.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .types import Reflection

__all__ = ["MAX_REFLECTIONS_PER_TICK", "apply_cap"]

MAX_REFLECTIONS_PER_TICK = 5

_log = logging.getLogger(__name__)


def apply_cap(
    reflections: list[Reflection],
    *,
    score: Callable[[Reflection], float] | None = None,
    limit: int = MAX_REFLECTIONS_PER_TICK,
) -> list[Reflection]:
    """Keep the top ``limit`` reflections; drop the rest (logged at debug).

    With ``score`` (e.g. a hotness-backed ranker) candidates are ordered highest
    first; without it, input order is preserved (stable). Ties keep input order.
    """
    if len(reflections) <= limit:
        return list(reflections)
    if score is not None:
        ordered = sorted(reflections, key=score, reverse=True)
    else:
        ordered = list(reflections)
    kept, dropped = ordered[:limit], ordered[limit:]
    _log.debug("reflection cap: kept %d, dropped %d", len(kept), len(dropped))
    return kept
