"""Tests for the Watch v2 web-monitor store + tick runner.

Everything is offline-deterministic: ``fetch`` and ``now`` are injected so no
socket opens and no clock is read.
"""

from __future__ import annotations

from lighthouse_ai.modes.web_monitor_store import (
    create_web_monitor,
    delete_web_monitor,
    get_web_monitor,
    list_web_monitor_alerts,
    list_web_monitors,
    run_web_monitor_tick,
)


def _db(tmp_path):
    return str(tmp_path / "state.db")


# ---------------------------- CRUD ----------------------------


def test_create_list_delete_roundtrip(tmp_path):
    db = _db(tmp_path)
    m = create_web_monitor(
        db,
        url="https://example.com/page",
        name="My Page",
        criteria={"kind": "any_change"},
        cadence_seconds=600,
        now="2026-05-29T00:00:00+00:00",
    )
    assert m["url"] == "https://example.com/page"
    assert m["name"] == "My Page"
    assert m["criteria"] == {"kind": "any_change"}
    assert m["cadence_seconds"] == 600
    assert m["status"] == "active"
    assert m["last_snapshot"] is None
    assert m["last_checked_at"] is None

    listing = list_web_monitors(db)
    assert len(listing) == 1
    assert listing[0]["id"] == m["id"]

    assert get_web_monitor(db, m["id"])["id"] == m["id"]

    assert delete_web_monitor(db, m["id"]) is True
    assert list_web_monitors(db) == []
    assert get_web_monitor(db, m["id"]) is None
    assert delete_web_monitor(db, m["id"]) is False


def test_create_defaults(tmp_path):
    db = _db(tmp_path)
    m = create_web_monitor(db, url="https://x.test", now="2026-05-29T00:00:00+00:00")
    assert m["name"] == "https://x.test"  # defaults to URL
    assert m["criteria"] == {"kind": "any_change"}
    assert m["cadence_seconds"] == 3600  # default 60 minutes


# ---------------------------- tick: baseline then change ----------------------------


def test_tick_baseline_then_change_any_change(tmp_path):
    db = _db(tmp_path)
    bodies = iter(["first version of the page", "SECOND different version"])

    def fetch(url: str) -> str:
        return next(bodies)

    create_web_monitor(
        db,
        url="https://example.com",
        criteria={"kind": "any_change"},
        cadence_seconds=60,
        now="2026-05-29T00:00:00+00:00",
    )

    # First tick → baseline, no alert.
    out1 = run_web_monitor_tick(db, fetch=fetch, now="2026-05-29T00:00:00+00:00")
    assert len(out1) == 1
    assert out1[0]["status"] == "baseline"
    assert list_web_monitor_alerts(db) == []

    # Second tick (cadence elapsed) → content changed → fired.
    out2 = run_web_monitor_tick(db, fetch=fetch, now="2026-05-29T00:05:00+00:00")
    assert len(out2) == 1
    assert out2[0]["status"] == "fired"

    alerts = list_web_monitor_alerts(db)
    assert len(alerts) == 1
    assert alerts[0]["url"] == "https://example.com"
    assert "changed" in alerts[0]["reason"]


def test_tick_no_change_is_quiet(tmp_path):
    db = _db(tmp_path)

    def fetch(url: str) -> str:
        return "stable content that never changes"

    create_web_monitor(
        db, url="https://stable.test", cadence_seconds=60,
        now="2026-05-29T00:00:00+00:00",
    )
    run_web_monitor_tick(db, fetch=fetch, now="2026-05-29T00:00:00+00:00")
    out = run_web_monitor_tick(db, fetch=fetch, now="2026-05-29T00:05:00+00:00")
    assert out[0]["status"] == "quiet"
    assert list_web_monitor_alerts(db) == []


def test_tick_keyword_criterion_fires(tmp_path):
    db = _db(tmp_path)
    bodies = iter(["all is calm", "the word recall now appears"])

    def fetch(url: str) -> str:
        return next(bodies)

    create_web_monitor(
        db,
        url="https://news.test",
        criteria={"kind": "keyword", "terms": ["recall"]},
        cadence_seconds=60,
        now="2026-05-29T00:00:00+00:00",
    )
    out1 = run_web_monitor_tick(db, fetch=fetch, now="2026-05-29T00:00:00+00:00")
    assert out1[0]["status"] == "baseline"
    out2 = run_web_monitor_tick(db, fetch=fetch, now="2026-05-29T00:05:00+00:00")
    assert out2[0]["status"] == "fired"
    assert "recall" in list_web_monitor_alerts(db)[0]["reason"]


def test_alert_sink_called_on_fire(tmp_path):
    db = _db(tmp_path)
    bodies = iter(["before", "after change"])

    def fetch(url: str) -> str:
        return next(bodies)

    received: list[dict] = []

    create_web_monitor(
        db, url="https://sink.test", cadence_seconds=60,
        now="2026-05-29T00:00:00+00:00",
    )
    run_web_monitor_tick(
        db, fetch=fetch, now="2026-05-29T00:00:00+00:00",
        alert_sink=received.append,
    )
    assert received == []  # baseline does not alert
    run_web_monitor_tick(
        db, fetch=fetch, now="2026-05-29T00:05:00+00:00",
        alert_sink=received.append,
    )
    assert len(received) == 1
    assert received[0]["url"] == "https://sink.test"


# ---------------------------- tick: cadence scheduling ----------------------------


def test_tick_respects_cadence(tmp_path):
    db = _db(tmp_path)
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return f"body-{len(calls)}"

    create_web_monitor(
        db, url="https://cadence.test", cadence_seconds=600,
        now="2026-05-29T00:00:00+00:00",
    )

    # t=0 → due (first run), baseline.
    run_web_monitor_tick(db, fetch=fetch, now="2026-05-29T00:00:00+00:00")
    assert len(calls) == 1

    # t=+5min → NOT due (cadence is 10min); fetch must not be called.
    out = run_web_monitor_tick(db, fetch=fetch, now="2026-05-29T00:05:00+00:00")
    assert len(calls) == 1
    assert out == []

    # t=+10min → due again.
    run_web_monitor_tick(db, fetch=fetch, now="2026-05-29T00:10:00+00:00")
    assert len(calls) == 2


def test_tick_fetch_error_skips_monitor(tmp_path):
    db = _db(tmp_path)

    def fetch(url: str) -> str:
        raise RuntimeError("network down")

    create_web_monitor(
        db, url="https://broken.test", cadence_seconds=60,
        now="2026-05-29T00:00:00+00:00",
    )
    out = run_web_monitor_tick(db, fetch=fetch, now="2026-05-29T00:00:00+00:00")
    assert out[0]["status"] == "error"
    # The monitor stays in place; last_checked_at not advanced (no snapshot).
    m = get_web_monitor(db, out[0]["id"])
    assert m["last_snapshot"] is None
