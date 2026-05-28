"""Tests for the job worker that executes queued research jobs (offline)."""

from __future__ import annotations

import json

from lighthouse_ai import worker
from lighthouse_ai.persistence import open_db


def _queue_job(paths, jid="j1", mode="Deep-Dive", topic="What is quantum computing?",
               status="queued"):
    conn = open_db(paths.state_db)
    try:
        conn.execute(
            "INSERT INTO jobs (id, mode, status, metadata_json) VALUES (?,?,?,?)",
            (jid, mode, status, json.dumps({"topic": topic, "depth": "Standard"})))
    finally:
        conn.close()


def _job_status(paths, jid):
    conn = open_db(paths.state_db)
    try:
        return conn.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0]
    finally:
        conn.close()


def test_pipeline_mode_mapping():
    assert worker._pipeline_mode("Deep-Dive") == "deep-dive"
    assert worker._pipeline_mode("QUC") == "quc"
    assert worker._pipeline_mode("Quick") == "quc"
    assert worker._pipeline_mode("Monitor") == "deep-dive"
    assert worker._pipeline_mode("") == "deep-dive"


def test_worker_runs_queued_job_to_review(migrated_paths):
    _queue_job(migrated_paths)
    ran = worker.process_once(migrated_paths, offline=True)
    assert ran is True
    assert _job_status(migrated_paths, "j1") == "review"
    # A draft was staged and linked to the job.
    conn = open_db(migrated_paths.state_db)
    try:
        row = conn.execute(
            "SELECT job_id, status FROM drafts WHERE job_id='j1'").fetchone()
    finally:
        conn.close()
    assert row is not None and row[1] == "staged"


def test_worker_noop_when_no_jobs(migrated_paths):
    assert worker.process_once(migrated_paths, offline=True) is False


def test_worker_claims_one_and_marks_running(migrated_paths):
    _queue_job(migrated_paths, "j1")
    _queue_job(migrated_paths, "j2")
    job = worker.claim_next_job(migrated_paths.state_db)
    assert job["id"] == "j1"  # oldest first
    assert _job_status(migrated_paths, "j1") == "running"
    assert _job_status(migrated_paths, "j2") == "queued"
    # Claiming again gets the next one, not the already-claimed one.
    job2 = worker.claim_next_job(migrated_paths.state_db)
    assert job2["id"] == "j2"


def test_worker_records_error_on_empty_topic(migrated_paths):
    _queue_job(migrated_paths, "j1", topic="")
    job = worker.claim_next_job(migrated_paths.state_db)
    status = worker.run_job(migrated_paths, job, offline=True)
    assert status == "error"
    assert _job_status(migrated_paths, "j1") == "error"


def test_worker_skips_when_paused(migrated_paths):
    _queue_job(migrated_paths)
    conn = open_db(migrated_paths.state_db)
    try:
        conn.execute(
            "INSERT INTO supervisor_state (id, status) VALUES (1, 'paused_hard') "
            "ON CONFLICT(id) DO UPDATE SET status='paused_hard'")
    finally:
        conn.close()
    assert worker.process_once(migrated_paths, offline=True) is False
    assert _job_status(migrated_paths, "j1") == "queued"  # untouched while paused
