"""Tests for the content-diff + trigger-criteria evaluator (Watch v2)."""

from __future__ import annotations

from lighthouse_ai.modes.web_triggers import (
    Snapshot,
    content_diff,
    evaluate_trigger,
    hash_text,
)

TS = "2026-05-29T00:00:00"


def snap(text: str) -> Snapshot:
    return Snapshot(text=text, fetched_at=TS, url="https://example.com/p")


# --- Snapshot --------------------------------------------------------------


def test_snapshot_hashes_text():
    s = snap("hello world")
    assert s.content_hash == hash_text("hello world")
    assert s.content_hash


def test_snapshot_roundtrip():
    s = snap("alpha beta")
    s2 = Snapshot.from_dict(s.as_dict())
    assert s2.content_hash == s.content_hash
    assert s2.text == s.text


# --- content_diff ----------------------------------------------------------


def test_content_diff_added_removed():
    d = content_diff("a\nb\nc", "b\nc\nd")
    assert d["added"] == ["d"]
    assert d["removed"] == ["a"]
    assert d["changed"] is True
    assert d["n_added"] == 1 and d["n_removed"] == 1


def test_content_diff_no_change():
    d = content_diff("a\nb", "b\na")
    assert d["changed"] is False
    assert d["added"] == [] and d["removed"] == []


# --- any_change ------------------------------------------------------------


def test_any_change_fires_on_diff():
    r = evaluate_trigger(snap("old text"), snap("new text"), {"kind": "any_change"})
    assert r.matched is True
    assert "diff" in r.details


def test_any_change_no_fire_when_identical():
    r = evaluate_trigger(snap("same"), snap("same"), {"kind": "any_change"})
    assert r.matched is False


def test_any_change_first_tick_baseline():
    r = evaluate_trigger(None, snap("anything"), {"kind": "any_change"})
    assert r.matched is False
    assert "baseline" in r.reason


# --- keyword ---------------------------------------------------------------


def test_keyword_fires_when_newly_present():
    crit = {"kind": "keyword", "terms": ["recall"]}
    r = evaluate_trigger(snap("all clear"), snap("safety recall issued"), crit)
    assert r.matched is True
    assert "recall" in r.details["hits"]


def test_keyword_no_fire_when_already_present():
    crit = {"kind": "keyword", "terms": ["recall"], "require_new": True}
    r = evaluate_trigger(snap("old recall"), snap("new recall notice"), crit)
    assert r.matched is False


def test_keyword_presence_mode_fires_first_tick():
    crit = {"kind": "keyword", "terms": ["recall"], "require_new": False}
    r = evaluate_trigger(None, snap("recall here"), crit)
    assert r.matched is True


def test_keyword_no_terms_no_fire():
    r = evaluate_trigger(snap("x"), snap("y"), {"kind": "keyword"})
    assert r.matched is False


# --- selector_text ---------------------------------------------------------


def test_selector_region_change_fires():
    crit = {"kind": "selector_text", "name": "price", "before": "Price:", "after": "USD"}
    old = snap("Price: 100 USD trailing")
    new = snap("Price: 120 USD trailing")
    r = evaluate_trigger(old, new, crit)
    assert r.matched is True
    assert r.details["old"] == "100"
    assert r.details["new"] == "120"


def test_selector_region_unchanged_no_fire():
    crit = {"kind": "selector_text", "name": "price", "before": "Price:", "after": "USD"}
    r = evaluate_trigger(snap("Price: 100 USD"), snap("Price: 100 USD here"), crit)
    assert r.matched is False


def test_selector_contains_fires():
    crit = {
        "kind": "selector_text",
        "name": "status",
        "before": "Status:",
        "after": ".",
        "contains": "shipped",
    }
    r = evaluate_trigger(snap("Status: pending."), snap("Status: shipped."), crit)
    assert r.matched is True


def test_selector_broken_self_reports():
    crit = {"kind": "selector_text", "name": "price", "before": "Price:", "after": "USD"}
    r = evaluate_trigger(snap("Price: 100 USD"), snap("no anchor here"), crit)
    assert r.matched is False
    assert r.details.get("broken") is True
    assert "selector" in r.reason.lower()


def test_selector_first_tick_baseline():
    crit = {"kind": "selector_text", "name": "price", "before": "Price:", "after": "USD"}
    r = evaluate_trigger(None, snap("Price: 100 USD"), crit)
    assert r.matched is False
    assert "baseline" in r.reason


# --- threshold -------------------------------------------------------------


def test_threshold_above_fires():
    crit = {"kind": "threshold", "label": "Temp:", "above": 30}
    r = evaluate_trigger(None, snap("Temp: 42 degrees"), crit)
    assert r.matched is True
    assert r.details["value"] == 42.0


def test_threshold_above_no_fire():
    crit = {"kind": "threshold", "label": "Temp:", "above": 50}
    r = evaluate_trigger(None, snap("Temp: 42 degrees"), crit)
    assert r.matched is False


def test_threshold_below_fires():
    crit = {"kind": "threshold", "label": "Stock:", "below": 10}
    r = evaluate_trigger(None, snap("Stock: 3 left"), crit)
    assert r.matched is True


def test_threshold_changed_fires():
    crit = {"kind": "threshold", "label": "Version:", "changed": True}
    r = evaluate_trigger(snap("Version: 1"), snap("Version: 2"), crit)
    assert r.matched is True
    assert r.details["old"] == 1.0 and r.details["value"] == 2.0


def test_threshold_changed_no_fire():
    crit = {"kind": "threshold", "label": "Version:", "changed": True}
    r = evaluate_trigger(snap("Version: 1"), snap("Version: 1 still"), crit)
    assert r.matched is False


def test_threshold_pattern_capture():
    crit = {"kind": "threshold", "pattern": r"v(\d+\.\d+)", "above": 2.0}
    r = evaluate_trigger(None, snap("release v3.5 now"), crit)
    assert r.matched is True
    assert r.details["value"] == 3.5


def test_threshold_no_number_no_fire():
    crit = {"kind": "threshold", "label": "Price:", "above": 5}
    r = evaluate_trigger(None, snap("Price: unavailable"), crit)
    assert r.matched is False


def test_threshold_comma_number():
    crit = {"kind": "threshold", "label": "Count:", "above": 1000}
    r = evaluate_trigger(None, snap("Count: 12,345 items"), crit)
    assert r.matched is True
    assert r.details["value"] == 12345.0


# --- unknown ---------------------------------------------------------------


def test_unknown_kind_no_fire():
    r = evaluate_trigger(snap("a"), snap("b"), {"kind": "bogus"})
    assert r.matched is False
    assert "unknown" in r.reason.lower()


def test_threshold_equals_fires_with_float_tolerance():
    """'equals' must match within float tolerance — exact == on parsed floats
    misfires on values like 0.30000000000000004."""
    crit = {"kind": "threshold", "label": "Result:", "equals": 0.3}
    r = evaluate_trigger(None, snap(f"Result: {0.1 + 0.2}"), crit)
    assert r.matched is True


def test_threshold_equals_no_fire_when_different():
    crit = {"kind": "threshold", "label": "Result:", "equals": 0.3}
    r = evaluate_trigger(None, snap("Result: 0.31"), crit)
    assert r.matched is False
