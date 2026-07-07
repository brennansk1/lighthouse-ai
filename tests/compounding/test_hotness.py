"""Tests for the Hotness Score (OpenHuman §2 integration).

Ports OpenHuman's locked behavioural cases plus the piecewise decay boundaries
and monotonicity properties.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lighthouse_ai.compounding.hotness import (
    TOPIC_CREATION_THRESHOLD,
    EntityStats,
    hotness_at,
    hotness_breakdown,
    recency_decay,
)

_DAY_MS = 86_400_000
NOW = 1_000 * _DAY_MS  # arbitrary fixed "now" well past the epoch


# --- ported OpenHuman locked cases ----------------------------------------


def test_zero_signal_is_zero() -> None:
    stats = EntityStats(mention_count_30d=0, distinct_sources=0, last_seen_ms=None)
    assert hotness_at(stats, NOW) == 0.0


def test_spike_crosses_threshold() -> None:
    # 100 mentions, 5 sources, 3 query hits, seen today → comfortably past 10.0.
    stats = EntityStats(
        mention_count_30d=100,
        distinct_sources=5,
        last_seen_ms=NOW,
        query_hits_30d=3,
    )
    assert hotness_at(stats, NOW) >= TOPIC_CREATION_THRESHOLD


def test_old_but_widely_cited_stays_meaningful() -> None:
    # Last seen 60 days ago (recency term decays to 0), but 12 independent
    # sources keep it meaningful via the distinct_sources term.
    stats = EntityStats(
        mention_count_30d=4,
        distinct_sources=12,
        last_seen_ms=NOW - 60 * _DAY_MS,
    )
    score = hotness_at(stats, NOW)
    # ln(5) mentions + 0.5*12 sources + 0 recency + 0 centrality + 0 hits.
    assert score == pytest.approx(math.log(5) + 0.5 * 12)
    assert score > 6.0  # source corroboration alone keeps it meaningful


# --- piecewise recency decay boundaries ------------------------------------


def test_recency_none_is_zero() -> None:
    assert recency_decay(None, NOW) == 0.0


def test_recency_exactly_one_day_is_full() -> None:
    assert recency_decay(NOW - _DAY_MS, NOW) == 1.0


def test_recency_seven_days_is_half() -> None:
    assert recency_decay(NOW - 7 * _DAY_MS, NOW) == pytest.approx(0.5)


def test_recency_thirty_days_is_zero() -> None:
    assert recency_decay(NOW - 30 * _DAY_MS, NOW) == pytest.approx(0.0)


def test_recency_beyond_thirty_days_is_zero() -> None:
    assert recency_decay(NOW - 45 * _DAY_MS, NOW) == 0.0


def test_recency_midweek_between_full_and_half() -> None:
    val = recency_decay(NOW - 4 * _DAY_MS, NOW)
    assert 0.5 < val < 1.0


# --- breakdown decomposes into five named terms ----------------------------


def test_breakdown_terms_sum_to_total() -> None:
    stats = EntityStats(
        mention_count_30d=10,
        distinct_sources=3,
        last_seen_ms=NOW,
        query_hits_30d=2,
        graph_centrality=0.7,
    )
    b = hotness_breakdown(stats, NOW)
    assert b.total == pytest.approx(
        b.mentions + b.sources + b.recency + b.centrality + b.query_hits
    )
    assert b.total == pytest.approx(hotness_at(stats, NOW))
    # All five named terms present in the tooltip dict.
    assert set(b.as_dict()) == {
        "mentions",
        "sources",
        "recency",
        "centrality",
        "query_hits",
        "total",
    }


def test_none_centrality_contributes_zero() -> None:
    stats = EntityStats(
        mention_count_30d=1, distinct_sources=0, last_seen_ms=None, graph_centrality=None
    )
    assert hotness_breakdown(stats, NOW).centrality == 0.0


# --- monotonicity properties (hypothesis) ----------------------------------


@given(
    mentions=st.integers(min_value=0, max_value=10_000),
    extra=st.integers(min_value=1, max_value=1_000),
    sources=st.integers(min_value=0, max_value=100),
    hits=st.integers(min_value=0, max_value=100),
)
def test_more_mentions_never_lowers_hotness(mentions, extra, sources, hits) -> None:
    base = EntityStats(
        mention_count_30d=mentions, distinct_sources=sources, last_seen_ms=NOW, query_hits_30d=hits
    )
    more = EntityStats(
        mention_count_30d=mentions + extra,
        distinct_sources=sources,
        last_seen_ms=NOW,
        query_hits_30d=hits,
    )
    assert hotness_at(more, NOW) >= hotness_at(base, NOW)


@given(
    sources=st.integers(min_value=0, max_value=100),
    extra=st.integers(min_value=1, max_value=100),
)
def test_more_sources_never_lowers_hotness(sources, extra) -> None:
    base = EntityStats(mention_count_30d=5, distinct_sources=sources, last_seen_ms=NOW)
    more = EntityStats(mention_count_30d=5, distinct_sources=sources + extra, last_seen_ms=NOW)
    assert hotness_at(more, NOW) >= hotness_at(base, NOW)


@given(
    age_days=st.integers(min_value=0, max_value=60),
    older_days=st.integers(min_value=1, max_value=60),
)
def test_older_last_seen_never_raises_hotness(age_days, older_days) -> None:
    newer = EntityStats(
        mention_count_30d=5, distinct_sources=2, last_seen_ms=NOW - age_days * _DAY_MS
    )
    older = EntityStats(
        mention_count_30d=5,
        distinct_sources=2,
        last_seen_ms=NOW - (age_days + older_days) * _DAY_MS,
    )
    assert hotness_at(older, NOW) <= hotness_at(newer, NOW)
