"""Persistence + tick runner for Watch v2 web monitors (FUTURE_FEATURES §1).

The offline CORE is already shipped and tested:

  * :mod:`lighthouse_ai.sources.scrapability` — the one-time pre-flight verdict.
  * :mod:`lighthouse_ai.modes.web_triggers` — the pure snapshot/trigger engine
    (:class:`Snapshot`, :func:`evaluate_trigger`).

This module is the *wiring* on top of that core: a tiny SQLite table that
remembers which pages a user registered to watch, plus a tick runner that the
supervisor's 24/7 loop calls. Everything that touches the outside world (the
network fetch, the wall clock) is *injected* so the whole module is
offline-deterministic in tests — pass a closure for ``fetch`` and an ISO string
for ``now`` and no socket opens and no clock is read.

Design notes
------------
* **No alembic.** The table is created idempotently by :func:`_ensure_table`
  (the established ``_ensure_`` pattern), so merely importing or calling this
  module never requires a migration step.
* **No ``datetime.now()`` at import** — and none inside the functions either:
  callers pass ``now`` explicitly. The supervisor reads its own clock and hands
  the ISO string in.
* **First check is a baseline.** A monitor with no prior snapshot stores its
  first observation and never alerts on it — there is nothing to compare
  against. The change-detection convention matches ``evaluate_trigger``.
* **A fetch error never kills the tick.** Each monitor is fetched inside its own
  try/except; a transport error for one page is recorded as a skip and the
  sweep moves on to the next monitor.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..persistence import open_db
from .web_triggers import Snapshot, evaluate_trigger

# An injected fetch returns the page text for a URL. Keeping the contract this
# small (``str -> str``) means tests pass a one-line closure and production
# passes a guarded-fetch adapter; the tick runner never imports httpx.
FetchFn = Callable[[str], str]

# An optional alert sink: called with a plain dict for every fired trigger so a
# caller (the supervisor, a notifier) can route it without this module knowing
# how alerts are delivered. Alerts are ALSO written to ``web_monitor_alerts`` so
# there is always a durable record even when no sink is supplied.
AlertSink = Callable[[dict[str, Any]], None]

_DEFAULT_CADENCE_SECONDS = 3600  # 60 minutes — the user-facing default.


# ---------------------------------------------------------------------------
# schema (idempotent _ensure_, NO alembic)
# ---------------------------------------------------------------------------


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Create the ``web_monitors`` + ``web_monitor_alerts`` tables if absent.

    Idempotent: safe to call on every entry point. ``criteria_json`` and
    ``last_snapshot_json`` hold the serialised trigger spec and the most recent
    :class:`Snapshot` (``as_dict``) respectively — both opaque JSON so the
    schema never has to change when a new criteria kind ships.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS web_monitors (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            criteria_json TEXT NOT NULL,
            cadence_seconds INTEGER NOT NULL,
            last_snapshot_json TEXT,
            last_checked_at TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS web_monitor_alerts (
            id TEXT PRIMARY KEY,
            monitor_id TEXT NOT NULL,
            url TEXT NOT NULL,
            fired_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            details_json TEXT NOT NULL
        )
        """
    )


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Map a ``web_monitors`` row to a JSON-friendly dict.

    ``criteria`` and ``last_snapshot`` are decoded back into objects so callers
    never see raw JSON strings.
    """
    (
        mid,
        name,
        url,
        criteria_json,
        cadence_seconds,
        last_snapshot_json,
        last_checked_at,
        status,
        created_at,
    ) = row
    return {
        "id": mid,
        "name": name,
        "url": url,
        "criteria": _loads(criteria_json, default={"kind": "any_change"}),
        "cadence_seconds": int(cadence_seconds),
        "last_snapshot": _loads(last_snapshot_json, default=None),
        "last_checked_at": last_checked_at,
        "status": status,
        "created_at": created_at,
    }


_SELECT_COLS = (
    "id, name, url, criteria_json, cadence_seconds, "
    "last_snapshot_json, last_checked_at, status, created_at"
)


def _loads(raw: str | None, *, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_web_monitor(
    state_db: str | Path,
    *,
    url: str,
    name: str | None = None,
    criteria: dict[str, Any] | None = None,
    cadence_seconds: int = _DEFAULT_CADENCE_SECONDS,
    now: str,
) -> dict[str, Any]:
    """Register a page to watch and return the stored monitor.

    Sane defaults for a non-technical user: ``criteria`` defaults to
    ``{"kind": "any_change"}`` ("tell me when anything changes") and ``name``
    defaults to the URL. ``now`` is the ISO-8601 ``created_at`` (injected, never
    read from a clock here). The new monitor has no ``last_checked_at`` so it is
    immediately due — its first tick captures the baseline.
    """
    crit = criteria or {"kind": "any_change"}
    label = name or url
    cadence = int(cadence_seconds) if int(cadence_seconds) > 0 else _DEFAULT_CADENCE_SECONDS
    mid = uuid.uuid4().hex
    conn = open_db(state_db)
    try:
        _ensure_table(conn)
        conn.execute(
            "INSERT INTO web_monitors "
            "(id, name, url, criteria_json, cadence_seconds, "
            " last_snapshot_json, last_checked_at, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, NULL, NULL, 'active', ?)",
            (mid, label, url, json.dumps(crit), cadence, now),
        )
        row = conn.execute(
            f"SELECT {_SELECT_COLS} FROM web_monitors WHERE id = ?", (mid,)
        ).fetchone()
    finally:
        conn.close()
    return _row_to_dict(row)


def list_web_monitors(state_db: str | Path) -> list[dict[str, Any]]:
    """Return every registered monitor (newest first)."""
    conn = open_db(state_db)
    try:
        _ensure_table(conn)
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM web_monitors "
            "ORDER BY created_at DESC, id DESC"
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def get_web_monitor(state_db: str | Path, monitor_id: str) -> dict[str, Any] | None:
    """Return one monitor by id, or ``None`` when it does not exist."""
    conn = open_db(state_db)
    try:
        _ensure_table(conn)
        row = conn.execute(
            f"SELECT {_SELECT_COLS} FROM web_monitors WHERE id = ?", (monitor_id,)
        ).fetchone()
    finally:
        conn.close()
    return _row_to_dict(row) if row else None


def set_web_monitor_status(
    state_db: str | Path, monitor_id: str, status: str
) -> dict[str, Any] | None:
    """Pause or resume a monitor. Returns the updated row, ``None`` if absent.

    Only ``active``/``paused`` are accepted — the tick runner picks up
    ``status = 'active'`` rows, so pausing is a pure flag flip and the
    monitor's snapshot/baseline is preserved for resume.
    """
    if status not in ("active", "paused"):
        raise ValueError(f"status must be 'active' or 'paused', not {status!r}")
    conn = open_db(state_db)
    try:
        _ensure_table(conn)
        cur = conn.execute(
            "UPDATE web_monitors SET status = ? WHERE id = ?",
            (status, monitor_id),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            f"SELECT {_SELECT_COLS} FROM web_monitors WHERE id = ?", (monitor_id,)
        ).fetchone()
    finally:
        conn.close()
    return _row_to_dict(row) if row else None


def delete_web_monitor(state_db: str | Path, monitor_id: str) -> bool:
    """Delete a monitor (and its alerts). Returns ``True`` when a row was removed."""
    conn = open_db(state_db)
    try:
        _ensure_table(conn)
        cur = conn.execute("DELETE FROM web_monitors WHERE id = ?", (monitor_id,))
        conn.execute(
            "DELETE FROM web_monitor_alerts WHERE monitor_id = ?", (monitor_id,)
        )
        deleted = cur.rowcount > 0
    finally:
        conn.close()
    return deleted


def list_web_monitor_alerts(
    state_db: str | Path, *, monitor_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Return recorded alerts (newest first), optionally for one monitor."""
    conn = open_db(state_db)
    try:
        _ensure_table(conn)
        if monitor_id is not None:
            rows = conn.execute(
                "SELECT id, monitor_id, url, fired_at, reason, details_json "
                "FROM web_monitor_alerts WHERE monitor_id = ? "
                "ORDER BY fired_at DESC, id DESC LIMIT ?",
                (monitor_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, monitor_id, url, fired_at, reason, details_json "
                "FROM web_monitor_alerts ORDER BY fired_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r[0],
            "monitor_id": r[1],
            "url": r[2],
            "fired_at": r[3],
            "reason": r[4],
            "details": _loads(r[5], default={}),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# tick runner
# ---------------------------------------------------------------------------


def _is_due(last_checked_at: str | None, cadence_seconds: int, now: str) -> bool:
    """Return whether a monitor is due at ``now`` (all ISO-8601 strings).

    A monitor with no ``last_checked_at`` is always due (first run). Otherwise
    it is due when ``last_checked_at + cadence <= now``. Comparison is on parsed
    datetimes so it is timezone-aware and never depends on string ordering.
    """
    if not last_checked_at:
        return True
    from datetime import datetime, timedelta

    try:
        last = datetime.fromisoformat(last_checked_at)
        current = datetime.fromisoformat(now)
    except ValueError:
        # Unparseable timestamps: fail safe by treating the monitor as due.
        return True
    return last + timedelta(seconds=cadence_seconds) <= current


def run_web_monitor_tick(
    state_db: str | Path,
    *,
    fetch: FetchFn,
    now: str,
    alert_sink: AlertSink | None = None,
) -> list[dict[str, Any]]:
    """Sweep due monitors once: fetch, diff against the last snapshot, alert.

    For each monitor whose ``last_checked_at + cadence`` has elapsed by ``now``:

      1. ``fetch(url)`` → page text (injected; a per-monitor error is caught and
         the monitor is skipped, never killing the sweep);
      2. build a :class:`Snapshot` (``fetched_at=now``);
      3. ``evaluate_trigger(last_snapshot, new_snapshot, criteria)``;
      4. on the FIRST check (no prior snapshot) record the baseline and do NOT
         alert; on a fired trigger record an alert (``web_monitor_alerts`` row
         and, when supplied, the ``alert_sink`` callback);
      5. persist the new snapshot + ``last_checked_at = now``.

    Returns a list of per-monitor outcome dicts (``status`` one of
    ``baseline`` / ``fired`` / ``quiet`` / ``error``) for logging/inspection.
    The function is offline-safe: with an injected ``fetch`` and ``now`` it opens
    no socket and reads no clock.
    """
    conn = open_db(state_db)
    outcomes: list[dict[str, Any]] = []
    try:
        _ensure_table(conn)
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM web_monitors WHERE status = 'active'"
        ).fetchall()
        monitors = [_row_to_dict(r) for r in rows]
        due = [
            m
            for m in monitors
            if _is_due(m["last_checked_at"], m["cadence_seconds"], now)
        ]

        for monitor in due:
            outcome = _run_one(conn, monitor, fetch=fetch, now=now, alert_sink=alert_sink)
            outcomes.append(outcome)
    finally:
        conn.close()
    return outcomes


def _run_one(
    conn: sqlite3.Connection,
    monitor: dict[str, Any],
    *,
    fetch: FetchFn,
    now: str,
    alert_sink: AlertSink | None,
) -> dict[str, Any]:
    """Run a single due monitor; persist state; return its outcome dict."""
    mid = monitor["id"]
    url = monitor["url"]

    try:
        text = fetch(url)
    except Exception as exc:  # transport error: skip THIS monitor, not the sweep
        return {"id": mid, "url": url, "status": "error", "reason": str(exc)}

    new_snap = Snapshot(text=text or "", fetched_at=now, url=url)

    prior_raw = monitor.get("last_snapshot")
    old_snap: Snapshot | None = None
    if isinstance(prior_raw, dict):
        try:
            old_snap = Snapshot.from_dict(prior_raw)
        except Exception:
            old_snap = None

    criteria = monitor.get("criteria") or {"kind": "any_change"}
    is_baseline = old_snap is None
    result = evaluate_trigger(old_snap, new_snap, criteria)

    # Persist the new snapshot + checked-at regardless of outcome.
    conn.execute(
        "UPDATE web_monitors SET last_snapshot_json = ?, last_checked_at = ? "
        "WHERE id = ?",
        (json.dumps(new_snap.as_dict()), now, mid),
    )

    if is_baseline:
        return {"id": mid, "url": url, "status": "baseline", "reason": result.reason}

    if not result.matched:
        return {"id": mid, "url": url, "status": "quiet", "reason": result.reason}

    # Fired: record an alert (durable row + optional sink callback).
    alert = {
        "id": uuid.uuid4().hex,
        "monitor_id": mid,
        "url": url,
        "name": monitor.get("name"),
        "fired_at": now,
        "reason": result.reason,
        "details": result.details,
    }
    conn.execute(
        "INSERT INTO web_monitor_alerts "
        "(id, monitor_id, url, fired_at, reason, details_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (alert["id"], mid, url, now, result.reason, json.dumps(result.details)),
    )
    if alert_sink is not None:
        try:
            alert_sink(alert)
        except Exception:
            # An alert sink must never break persistence/sweep.
            pass

    return {
        "id": mid,
        "url": url,
        "status": "fired",
        "reason": result.reason,
        "alert_id": alert["id"],
    }
