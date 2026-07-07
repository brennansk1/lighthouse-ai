"""Unit tests for event-monitor sessions (modes/monitor_session.py).

All offline: the feed is supplied via an injected ``fetch_fn`` and salience is
the heuristic default (no LLM, no network).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lighthouse_ai.modes.monitor import MonitorItem
from lighthouse_ai.modes.monitor_session import (
    AutoStopConfig,
    SessionSpec,
    create_session,
    get_session,
    get_session_results,
    list_sessions,
    run_session_cycle,
    stop_session,
)


def _item(url: str, title: str = "headline", body: str = "body text") -> MonitorItem:
    return MonitorItem(source="feed", url=url, title=title, body=body)


def _loud_items(n: int = 1) -> list[MonitorItem]:
    # "breaking" pushes default_salience above the 0.5 floor.
    return [_item(f"https://x/{i}", body="breaking major development") for i in range(n)]


def test_create_and_get(migrated_paths):
    s = create_session(
        migrated_paths.state_db, SessionSpec(label="Hearing", source_urls=["https://x/feed"])
    )
    assert s.status == "active"
    assert s.label == "Hearing"
    assert s.source_urls == ["https://x/feed"]
    fetched = get_session(migrated_paths.state_db, s.id)
    assert fetched is not None and fetched.id == s.id


def test_list_filters_by_status(migrated_paths):
    a = create_session(migrated_paths.state_db, SessionSpec(label="A"))
    create_session(migrated_paths.state_db, SessionSpec(label="B"))
    stop_session(migrated_paths.state_db, a.id)
    active = list_sessions(migrated_paths.state_db, status="active")
    ended = list_sessions(migrated_paths.state_db, status="ended")
    assert {s.label for s in active} == {"B"}
    assert {s.label for s in ended} == {"A"}


def test_cycle_records_items_and_dedups(migrated_paths):
    s = create_session(migrated_paths.state_db, SessionSpec(label="W", auto_stop=False))
    items = _loud_items(3)
    run_session_cycle(migrated_paths.state_db, s.id, fetch_fn=lambda _s: items)
    run_session_cycle(migrated_paths.state_db, s.id, fetch_fn=lambda _s: items)
    results = get_session_results(migrated_paths.state_db, s.id)
    assert len(results) == 3  # dedup across cycles — no duplicates


def test_stop_session_is_manual(migrated_paths):
    s = create_session(migrated_paths.state_db, SessionSpec(label="W"))
    stopped = stop_session(migrated_paths.state_db, s.id)
    assert stopped is not None
    assert stopped.status == "ended"
    assert stopped.ended_reason == "manual"


def test_inactive_session_cycle_returns_none(migrated_paths):
    s = create_session(migrated_paths.state_db, SessionSpec(label="W"))
    stop_session(migrated_paths.state_db, s.id)
    assert (
        run_session_cycle(migrated_paths.state_db, s.id, fetch_fn=lambda _s: _loud_items(1)) is None
    )


def test_auto_stop_after_quiet_cycles(migrated_paths):
    s = create_session(
        migrated_paths.state_db,
        SessionSpec(label="Quiet", auto=AutoStopConfig(quiet_cycles=2, salience_floor=0.5)),
    )
    # Empty feed → max salience 0.0 < floor → quiet each cycle.
    run_session_cycle(migrated_paths.state_db, s.id, fetch_fn=lambda _s: [])
    mid = get_session(migrated_paths.state_db, s.id)
    assert mid.status == "active"  # one quiet cycle, not yet at threshold
    run_session_cycle(migrated_paths.state_db, s.id, fetch_fn=lambda _s: [])
    done = get_session(migrated_paths.state_db, s.id)
    assert done.status == "ended"
    assert done.ended_reason == "auto_stop_quiet"


def test_loud_cycle_resets_quiet_counter(migrated_paths):
    s = create_session(
        migrated_paths.state_db,
        SessionSpec(label="Noisy", auto=AutoStopConfig(quiet_cycles=2, salience_floor=0.5)),
    )
    run_session_cycle(migrated_paths.state_db, s.id, fetch_fn=lambda _s: [])  # quiet
    run_session_cycle(
        migrated_paths.state_db, s.id, fetch_fn=lambda _s: _loud_items(1)
    )  # loud → reset
    run_session_cycle(migrated_paths.state_db, s.id, fetch_fn=lambda _s: [])  # quiet again
    still = get_session(migrated_paths.state_db, s.id)
    assert still.status == "active"  # counter was reset by the loud cycle


def test_end_at_time(migrated_paths):
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat(timespec="seconds")
    s = create_session(
        migrated_paths.state_db, SessionSpec(label="Timed", ends_at=past, auto_stop=False)
    )
    run_session_cycle(migrated_paths.state_db, s.id, fetch_fn=lambda _s: _loud_items(1))
    done = get_session(migrated_paths.state_db, s.id)
    assert done.status == "ended"
    assert done.ended_reason == "time_reached"


def test_max_duration_cap(migrated_paths):
    s = create_session(
        migrated_paths.state_db,
        SessionSpec(label="Capped", auto_stop=False, auto=AutoStopConfig(max_duration_s=0)),
    )
    run_session_cycle(migrated_paths.state_db, s.id, fetch_fn=lambda _s: _loud_items(1))
    done = get_session(migrated_paths.state_db, s.id)
    assert done.status == "ended"
    assert done.ended_reason == "max_duration"
