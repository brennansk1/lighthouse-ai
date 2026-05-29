"""Offline tests for research depth tiers and their wiring into Investigate."""

from __future__ import annotations

import json

from lighthouse_ai.modes.depth import (
    DEFAULT_TIER,
    canonical_tier,
    resolve_depth,
)
from lighthouse_ai.persistence import open_db


def test_canonical_tier_aliases():
    assert canonical_tier("Quick") == "quick"
    assert canonical_tier("exhaustive") == "thorough"
    assert canonical_tier("Professional") == "deep"
    assert canonical_tier("overnight") == "deep"
    assert canonical_tier(None) == DEFAULT_TIER
    assert canonical_tier("nonsense") == DEFAULT_TIER


def test_resolve_depth_monotonic_rounds():
    q = resolve_depth("quick")["max_rounds"]
    s = resolve_depth("standard")["max_rounds"]
    t = resolve_depth("thorough")["max_rounds"]
    d = resolve_depth("deep")["max_rounds"]
    assert q < s < t < d


def test_deep_tier_is_recursive_and_adversarial():
    deep = resolve_depth("deep")
    assert deep["recursive"] is True
    assert deep["adversarial"] is True
    assert deep["coverage_critic"] is True
    assert resolve_depth("quick")["recursive"] is False


def test_resolve_depth_returns_copy():
    a = resolve_depth("standard")
    a["max_rounds"] = 999
    assert resolve_depth("standard")["max_rounds"] != 999


def _insert(state_db, jid, mode, meta):
    conn = open_db(state_db)
    try:
        conn.execute(
            "INSERT INTO jobs (id, mode, status, metadata_json) "
            "VALUES (?, ?, 'queued', ?)", (jid, mode, json.dumps(meta)))
    finally:
        conn.close()


def test_investigate_records_depth_in_body(migrated_paths):
    """The chosen depth tier + max_rounds are recorded in the artifact."""
    from lighthouse_ai.dispatcher import dispatch_once

    _insert(migrated_paths.state_db, "j1", "investigate",
            {"topic": "Why did the rollout slip?", "depth": "thorough"})
    draft_id = dispatch_once(migrated_paths)  # offline
    conn = open_db(migrated_paths.state_db)
    try:
        bj = conn.execute("SELECT body_json FROM drafts WHERE id=?",
                          (draft_id,)).fetchone()[0]
    finally:
        conn.close()
    body = json.loads(bj)
    assert body["depth"] == "thorough"
    assert body["max_rounds"] == resolve_depth("thorough")["max_rounds"]
    # Thorough enables coverage critic + adversarial pass → recorded in body.
    assert "coverage" in body
    assert "adversarial" in body


def test_quick_tier_skips_adversarial(migrated_paths):
    from lighthouse_ai.dispatcher import dispatch_once

    _insert(migrated_paths.state_db, "j1", "investigate",
            {"topic": "Quick scan question?", "depth": "quick"})
    draft_id = dispatch_once(migrated_paths)
    conn = open_db(migrated_paths.state_db)
    try:
        bj = conn.execute("SELECT body_json FROM drafts WHERE id=?",
                          (draft_id,)).fetchone()[0]
    finally:
        conn.close()
    body = json.loads(bj)
    assert body["depth"] == "quick"
    assert "adversarial" not in body   # quick tier skips the refutation pass
