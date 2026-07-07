"""Tests for the per-job progress trace (Zone A).

Covers the three contract surfaces:
  (a) ``ProgressEmitter`` writes ordered ``job_events`` rows, updates the job's
      ``metadata_json.progress``, and (with a bus) publishes ``job.step``.
  (b) an offline ``dispatch_once`` on an ``investigate`` job produces a
      multi-event trace with phases advancing and a final ``done`` at pct 100.
  (c) ``GET /api/jobs/{id}/trace`` replays the events in the contract shape.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from lighthouse_ai.controlplane import create_app
from lighthouse_ai.dispatcher import dispatch_once
from lighthouse_ai.persistence import open_db
from lighthouse_ai.progress import ProgressEmitter


def _insert_job(state_db, jid: str, mode: str, meta: dict, status="queued"):
    conn = open_db(state_db)
    try:
        conn.execute(
            "INSERT INTO jobs (id, mode, status, metadata_json) VALUES (?, ?, ?, ?)",
            (jid, mode, status, json.dumps(meta)),
        )
    finally:
        conn.close()


class _FakeBus:
    """Records publish() calls in-process (no event loop needed)."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def publish(self, name, data=None):
        self.events.append((name, data or {}))


# ── (a) ProgressEmitter primitives ──────────────────────────────────────────


def test_emitter_writes_ordered_rows_and_updates_progress(migrated_paths):
    _insert_job(migrated_paths.state_db, "j1", "investigate", {"topic": "X"})
    bus = _FakeBus()
    em = ProgressEmitter("j1", migrated_paths, bus)

    em.emit("framing", "start", "Framing", 5.0, {"mode": "investigate"})
    em.emit("drafting", "round", "Round 1", 45.0, {"round": 1})
    em.emit("done", "done", "Complete", 100.0)

    conn = open_db(migrated_paths.state_db)
    try:
        rows = conn.execute(
            "SELECT seq, phase, kind, pct, payload_json FROM job_events "
            "WHERE job_id='j1' ORDER BY seq"
        ).fetchall()
        meta_json = conn.execute("SELECT metadata_json FROM jobs WHERE id='j1'").fetchone()[0]
    finally:
        conn.close()

    # Ordered, monotonic seq starting at 1.
    assert [r[0] for r in rows] == [1, 2, 3]
    assert [r[1] for r in rows] == ["framing", "drafting", "done"]
    assert rows[-1][3] == 100.0
    assert json.loads(rows[0][4]) == {"mode": "investigate"}

    # progress tracked pct/100, last write wins.
    assert json.loads(meta_json)["progress"] == 1.0

    # Bus saw a job.step per emit, with the exact payload contract.
    assert [name for name, _ in bus.events] == ["job.step"] * 3
    first = bus.events[0][1]
    assert set(first) == {"job_id", "seq", "phase", "kind", "label", "pct", "data"}
    assert first["job_id"] == "j1"
    assert first["seq"] == 1
    assert first["phase"] == "framing"


def test_emitter_is_best_effort_on_bad_state(migrated_paths, tmp_path):
    """A failure path (job row absent) must not raise — best-effort contract."""
    em = ProgressEmitter("missing", migrated_paths, bus=None)
    # No job row → _update_progress is a no-op, emit still records the event.
    em.emit("framing", "start", "Framing", 5.0)
    conn = open_db(migrated_paths.state_db)
    try:
        n = conn.execute("SELECT COUNT(*) FROM job_events WHERE job_id='missing'").fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_emitter_no_bus_still_persists(migrated_paths):
    _insert_job(migrated_paths.state_db, "j2", "investigate", {"topic": "X"})
    em = ProgressEmitter("j2", migrated_paths, bus=None)
    em.emit("framing", "start", "Framing", 10.0)
    conn = open_db(migrated_paths.state_db)
    try:
        row = conn.execute("SELECT metadata_json FROM jobs WHERE id='j2'").fetchone()
    finally:
        conn.close()
    assert json.loads(row[0])["progress"] == pytest.approx(0.1)


# ── (b) offline dispatch produces a multi-event trace ───────────────────────


def test_dispatch_investigate_produces_advancing_trace(migrated_paths):
    _insert_job(migrated_paths.state_db, "inv1", "investigate", {"topic": "Why did Y happen?"})
    draft_id = dispatch_once(migrated_paths)  # gateway=None → offline
    assert draft_id is not None

    conn = open_db(migrated_paths.state_db)
    try:
        rows = conn.execute(
            "SELECT seq, phase, kind, pct FROM job_events WHERE job_id='inv1' ORDER BY seq"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) >= 2, "expected a multi-event trace"
    # seq is monotonic.
    seqs = [r[0] for r in rows]
    assert seqs == sorted(seqs)
    assert seqs[0] == 1
    # pct is non-decreasing across the run.
    pcts = [r[3] for r in rows]
    assert pcts == sorted(pcts)
    # Starts with framing, ends with done at 100.
    assert rows[0][1] == "framing"
    assert rows[-1][1] == "done"
    assert rows[-1][2] == "done"
    assert rows[-1][3] == 100.0


def test_dispatch_simple_mode_has_min_trace(migrated_paths):
    """A mode without rich callbacks still gets framing→drafting→done."""
    _insert_job(migrated_paths.state_db, "ask1", "ask", {"topic": "What is V?"})
    draft_id = dispatch_once(migrated_paths)
    assert draft_id is not None
    conn = open_db(migrated_paths.state_db)
    try:
        phases = [
            r[0]
            for r in conn.execute(
                "SELECT phase FROM job_events WHERE job_id='ask1' ORDER BY seq"
            ).fetchall()
        ]
    finally:
        conn.close()
    assert phases[0] == "framing"
    assert "drafting" in phases
    assert phases[-1] == "done"


# ── (c) the trace endpoint ──────────────────────────────────────────────────


def test_trace_endpoint_returns_events(migrated_paths):
    client = TestClient(create_app(migrated_paths))
    client.post("/api/jobs", json={"mode": "investigate", "topic": "Why did Y happen?"})
    draft_id = dispatch_once(migrated_paths)
    assert draft_id is not None
    # Find the job id (the only job).
    conn = open_db(migrated_paths.state_db)
    try:
        jid = conn.execute("SELECT id FROM jobs LIMIT 1").fetchone()[0]
    finally:
        conn.close()

    body = client.get(f"/api/jobs/{jid}/trace").json()
    assert body["job_id"] == jid
    assert body["status"] == "review"
    assert body["pct"] == 100.0
    assert isinstance(body["events"], list) and body["events"]
    ev = body["events"][0]
    assert set(ev) == {"seq", "ts", "phase", "kind", "label", "pct", "data"}
    assert body["events"][-1]["phase"] == "done"
    # Ordered by seq.
    seqs = [e["seq"] for e in body["events"]]
    assert seqs == sorted(seqs)


def test_trace_endpoint_unknown_job_is_empty(migrated_paths):
    client = TestClient(create_app(migrated_paths))
    body = client.get("/api/jobs/nope/trace").json()
    assert body == {"job_id": "nope", "status": None, "pct": 0.0, "events": []}
