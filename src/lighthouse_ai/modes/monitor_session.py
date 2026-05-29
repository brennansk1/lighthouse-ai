"""Event-monitor sessions — time-bounded watches over one or more sources.

A *session* is a standing Mode-A monitor with a lifecycle: it starts (now or
at ``starts_at``), polls its sources on a cadence, and ends when one of three
conditions is met:

  * ``ends_at`` is reached (explicit end time), or
  * the watch goes quiet — ``consecutive_quiet`` cycles whose top salience
    stays below ``salience_floor`` reaches ``quiet_cycles`` (auto-stop), or
  * the session exceeds ``max_duration_s`` since creation (safety cap).

Each cycle reuses :func:`lighthouse_ai.modes.monitor.run_monitor` with a dedup
ledger rehydrated from already-seen items, so the same URL is never recorded
twice. Salience is heuristic only (no LLM): the supervisor sweep that drives
this must stay cheap and never block on the gateway.

The persisted dedup makes ``run_session_cycle`` idempotent across restarts.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..persistence import open_db
from .monitor import (
    MonitorItem,
    MonitorReport,
    MonitorState,
    SalienceFn,
    default_salience,
    run_monitor,
)

# A fetcher turns a session into the raw items seen this cycle. Injected so
# tests can supply a deterministic feed and production can hit the network.
FetchFn = Callable[["MonitorSession"], list[MonitorItem]]


@dataclass(frozen=True)
class AutoStopConfig:
    """When a session may end itself rather than running to ``ends_at``."""
    quiet_cycles: int = 3
    salience_floor: float = 0.5
    max_duration_s: int = 86400  # 24h hard cap


@dataclass(frozen=True)
class SessionSpec:
    """User-supplied parameters for a new monitor session."""
    label: str
    source_urls: list[str] = field(default_factory=list)
    starts_at: str | None = None
    ends_at: str | None = None
    auto_stop: bool = True
    poll_interval_s: int = 300
    auto: AutoStopConfig = field(default_factory=AutoStopConfig)


@dataclass(frozen=True)
class MonitorSession:
    id: str
    label: str
    source_urls: list[str]
    created_at: str
    starts_at: str | None
    ends_at: str | None
    auto_stop: bool
    quiet_cycles: int
    salience_floor: float
    max_duration_s: int
    poll_interval_s: int
    status: str
    consecutive_quiet: int
    last_salience: float | None
    last_polled_at: str | None
    cycles: int
    ended_reason: str | None


# --- time helpers -----------------------------------------------------------

def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _parse_dt(ts: str | None) -> datetime | None:
    """Parse an ISO or SQLite ``datetime('now')`` string to aware UTC."""
    if not ts:
        return None
    s = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


# --- row mapping ------------------------------------------------------------

def _row_to_session(row: sqlite3.Row) -> MonitorSession:
    return MonitorSession(
        id=row["id"],
        label=row["label"],
        source_urls=json.loads(row["source_urls_json"] or "[]"),
        created_at=row["created_at"],
        starts_at=row["starts_at"],
        ends_at=row["ends_at"],
        auto_stop=bool(row["auto_stop"]),
        quiet_cycles=row["quiet_cycles"],
        salience_floor=row["salience_floor"],
        max_duration_s=row["max_duration_s"],
        poll_interval_s=row["poll_interval_s"],
        status=row["status"],
        consecutive_quiet=row["consecutive_quiet"],
        last_salience=row["last_salience"],
        last_polled_at=row["last_polled_at"],
        cycles=row["cycles"],
        ended_reason=row["ended_reason"],
    )


def _conn(db: Path) -> sqlite3.Connection:
    conn = open_db(db)
    conn.row_factory = sqlite3.Row
    return conn


# --- CRUD -------------------------------------------------------------------

def create_session(db: Path, spec: SessionSpec) -> MonitorSession:
    sid = uuid.uuid4().hex[:8]
    conn = _conn(db)
    try:
        conn.execute(
            """
            INSERT INTO monitor_sessions
              (id, label, source_urls_json, starts_at, ends_at, auto_stop,
               quiet_cycles, salience_floor, max_duration_s, poll_interval_s)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (sid, spec.label, json.dumps(spec.source_urls),
             spec.starts_at, spec.ends_at, 1 if spec.auto_stop else 0,
             spec.auto.quiet_cycles, spec.auto.salience_floor,
             spec.auto.max_duration_s, spec.poll_interval_s),
        )
        row = conn.execute("SELECT * FROM monitor_sessions WHERE id=?", (sid,)).fetchone()
    finally:
        conn.close()
    return _row_to_session(row)


def list_sessions(db: Path, *, status: str | None = None) -> list[MonitorSession]:
    conn = _conn(db)
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM monitor_sessions WHERE status=? ORDER BY created_at DESC",
                (status,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM monitor_sessions ORDER BY created_at DESC").fetchall()
    finally:
        conn.close()
    return [_row_to_session(r) for r in rows]


def get_session(db: Path, session_id: str) -> MonitorSession | None:
    conn = _conn(db)
    try:
        row = conn.execute("SELECT * FROM monitor_sessions WHERE id=?",
                           (session_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_session(row) if row else None


def get_session_results(db: Path, session_id: str) -> list[dict]:
    conn = _conn(db)
    try:
        rows = conn.execute(
            """SELECT id, dedup_key, url, title, salience, category, is_alert,
                      cycle, created_at
               FROM monitor_items WHERE session_id=?
               ORDER BY salience DESC, id DESC""",
            (session_id,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def stop_session(db: Path, session_id: str, *, reason: str = "manual"
                 ) -> MonitorSession | None:
    conn = _conn(db)
    try:
        cur = conn.execute(
            """UPDATE monitor_sessions SET status='ended', ended_reason=?
               WHERE id=? AND status != 'ended'""",
            (reason, session_id))
        if cur.rowcount == 0:
            row = conn.execute("SELECT * FROM monitor_sessions WHERE id=?",
                               (session_id,)).fetchone()
            return _row_to_session(row) if row else None
        row = conn.execute("SELECT * FROM monitor_sessions WHERE id=?",
                           (session_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_session(row)


def due_sessions(db: Path, *, now: datetime | None = None) -> list[MonitorSession]:
    """Active sessions that have started and whose poll interval has elapsed."""
    now = now or _now()
    out: list[MonitorSession] = []
    for s in list_sessions(db, status="active"):
        started = _parse_dt(s.starts_at)
        if started is not None and started > now:
            continue  # not started yet
        last = _parse_dt(s.last_polled_at)
        if last is not None and (now - last) < timedelta(seconds=s.poll_interval_s):
            continue  # polled too recently
        out.append(s)
    return out


# --- default fetcher --------------------------------------------------------

def _default_fetch(session: MonitorSession) -> list[MonitorItem]:
    """Production fetcher: pull + parse each source URL as an RSS/Atom feed."""
    from ..sources.rss import fetch_feed
    items: list[MonitorItem] = []
    for url in session.source_urls:
        try:
            items.extend(fetch_feed(url))
        except Exception:
            continue  # a dead feed must not abort the whole cycle
    return items


# --- the cycle --------------------------------------------------------------

def run_session_cycle(
    db: Path,
    session_id: str,
    *,
    fetch_fn: FetchFn = _default_fetch,
    salience_fn: SalienceFn = default_salience,
    now: datetime | None = None,
) -> MonitorReport | None:
    """Run one polling cycle for ``session_id``.

    Returns the :class:`MonitorReport` for the cycle, or ``None`` if the
    session is missing or no longer active. Persists new (deduped) items and
    advances the session's lifecycle, ending it when a stop condition is met.
    """
    now = now or _now()
    session = get_session(db, session_id)
    if session is None or session.status != "active":
        return None

    items = fetch_fn(session)

    conn = _conn(db)
    try:
        seen = {r["dedup_key"] for r in conn.execute(
            "SELECT dedup_key FROM monitor_items WHERE session_id=?",
            (session_id,)).fetchall()}
        st = MonitorState(seen_keys=set(seen))
        report = run_monitor(session.label, items, state=st, salience_fn=salience_fn)

        cycle_no = session.cycles + 1
        classified = report.alerts + report.digest
        for c in classified:
            conn.execute(
                """INSERT OR IGNORE INTO monitor_items
                     (session_id, dedup_key, url, title, salience, category,
                      is_alert, cycle)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (session_id, c.item.dedup_key(), c.item.url, c.item.title,
                 c.salience, c.category, 1 if c.is_alert else 0, cycle_no))

        max_salience = max((c.salience for c in classified), default=0.0)
        quiet = max_salience < session.salience_floor
        consecutive_quiet = session.consecutive_quiet + 1 if quiet else 0

        ended_reason = _stop_reason(session, now, consecutive_quiet)
        new_status = "ended" if ended_reason else "active"

        conn.execute(
            """UPDATE monitor_sessions
               SET cycles=?, consecutive_quiet=?, last_salience=?,
                   last_polled_at=?, status=?, ended_reason=?
               WHERE id=?""",
            (cycle_no, consecutive_quiet, max_salience, now.isoformat(timespec="seconds"),
             new_status, ended_reason, session_id))
    finally:
        conn.close()
    return report


def _stop_reason(session: MonitorSession, now: datetime,
                 consecutive_quiet: int) -> str | None:
    """Which stop condition (if any) ends the session this cycle."""
    ends = _parse_dt(session.ends_at)
    if ends is not None and now >= ends:
        return "time_reached"
    created = _parse_dt(session.created_at)
    if created is not None and (now - created) >= timedelta(seconds=session.max_duration_s):
        return "max_duration"
    if session.auto_stop and consecutive_quiet >= session.quiet_cycles:
        return "auto_stop_quiet"
    return None
