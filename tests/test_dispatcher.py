"""Offline tests for the job dispatcher (no real LLM)."""

from __future__ import annotations

import json

import pytest

from lighthouse_ai.dispatcher import (
    build_runtime_gateway,
    claim_one_job,
    dispatch_once,
    reap_stuck_jobs,
    run_job,
)
from lighthouse_ai.persistence import open_db


def _insert_job(state_db, jid: str, mode: str, meta: dict, status="queued"):
    conn = open_db(state_db)
    try:
        conn.execute(
            "INSERT INTO jobs (id, mode, status, metadata_json) VALUES (?, ?, ?, ?)",
            (jid, mode, status, json.dumps(meta)))
    finally:
        conn.close()


def _decide_meta():
    return {
        "topic": "Which database?",
        "options": ["Postgres", "SQLite"],
        "criteria": [
            {"label": "scalability", "weight": 2.0},
            {"label": "simplicity", "weight": 1.0},
        ],
    }


def _job_status(state_db, jid: str) -> str:
    conn = open_db(state_db)
    try:
        return conn.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0]
    finally:
        conn.close()


def test_claim_flips_to_running_and_returns_meta(migrated_paths):
    _insert_job(migrated_paths.state_db, "j1", "decide", _decide_meta())
    job = claim_one_job(migrated_paths.state_db)
    assert job is not None
    assert job.id == "j1"
    assert job.mode == "decide"
    assert job.meta["options"] == ["Postgres", "SQLite"]
    assert _job_status(migrated_paths.state_db, "j1") == "running"


def test_claim_returns_none_when_empty(migrated_paths):
    assert claim_one_job(migrated_paths.state_db) is None


def test_claim_does_not_reclaim_running(migrated_paths):
    _insert_job(migrated_paths.state_db, "j1", "decide", _decide_meta())
    first = claim_one_job(migrated_paths.state_db)
    second = claim_one_job(migrated_paths.state_db)
    assert first is not None
    assert second is None  # already running, nothing left to claim


def test_claim_oldest_first(migrated_paths):
    _insert_job(migrated_paths.state_db, "j1", "decide", _decide_meta())
    _insert_job(migrated_paths.state_db, "j2", "decide", _decide_meta())
    job = claim_one_job(migrated_paths.state_db)
    assert job.id == "j1"


def test_run_job_offline_produces_review_and_draft(migrated_paths):
    _insert_job(migrated_paths.state_db, "j1", "decide", _decide_meta())
    job = claim_one_job(migrated_paths.state_db)
    draft_id = run_job(migrated_paths, job)  # gateway=None → offline
    assert draft_id is not None
    assert _job_status(migrated_paths.state_db, "j1") == "review"

    conn = open_db(migrated_paths.state_db)
    try:
        row = conn.execute(
            "SELECT artifact_type, body_json, status FROM drafts WHERE id=?",
            (draft_id,)).fetchone()
    finally:
        conn.close()
    assert row[0] == "matrix"
    assert row[2] == "staged"
    body = json.loads(row[1])
    assert "winner" in body and body["winner"] in {"Postgres", "SQLite"}


def test_dispatch_once_end_to_end(migrated_paths):
    _insert_job(migrated_paths.state_db, "j1", "decide", _decide_meta())
    draft_id = dispatch_once(migrated_paths)
    assert draft_id is not None
    assert _job_status(migrated_paths.state_db, "j1") == "review"


def test_dispatch_once_idle_returns_none(migrated_paths):
    assert dispatch_once(migrated_paths) is None


def test_unknown_mode_fails_gracefully(migrated_paths):
    _insert_job(migrated_paths.state_db, "j1", "not-a-mode", {"topic": "x"})
    # canonical() raises KeyError on unknown; claim still succeeds, run marks failed.
    job = claim_one_job(migrated_paths.state_db)
    draft_id = run_job(migrated_paths, job)
    assert draft_id is None
    assert _job_status(migrated_paths.state_db, "j1") == "failed"


def test_reaper_requeues_running(migrated_paths):
    _insert_job(migrated_paths.state_db, "j1", "decide", _decide_meta(),
                status="running")
    requeued = reap_stuck_jobs(migrated_paths.state_db)
    assert requeued == ["j1"]
    assert _job_status(migrated_paths.state_db, "j1") == "queued"


def test_survey_dispatch(migrated_paths):
    meta = {
        "topic": "Which trials?",
        "documents": [
            {"id": "d1", "title": "RCT", "text": "A randomized trial of 200 patients."},
        ],
        "criteria": [{"label": "trial", "keywords": ["randomized"]}],
        "attributes": [{"label": "n", "keywords": ["patients"]}],
    }
    _insert_job(migrated_paths.state_db, "j1", "survey", meta)
    draft_id = dispatch_once(migrated_paths)
    assert draft_id is not None
    conn = open_db(migrated_paths.state_db)
    try:
        atype = conn.execute("SELECT artifact_type FROM drafts WHERE id=?",
                             (draft_id,)).fetchone()[0]
    finally:
        conn.close()
    assert atype == "table"


def test_reconstruct_dispatch(migrated_paths):
    meta = {
        "topic": "History?",
        "documents": [{"id": "d1", "text": "In 2020 it launched. In 2022 it grew."}],
    }
    _insert_job(migrated_paths.state_db, "j1", "reconstruct", meta)
    draft_id = dispatch_once(migrated_paths)
    assert draft_id is not None
    conn = open_db(migrated_paths.state_db)
    try:
        atype = conn.execute("SELECT artifact_type FROM drafts WHERE id=?",
                             (draft_id,)).fetchone()[0]
    finally:
        conn.close()
    assert atype == "timeline"


# ── all-seven-modes end-to-end coverage ────────────────────────────────────
#
# Each case is the minimal wizard-shaped metadata for a mode. The dispatcher
# must run every one offline-deterministically (gateway=None), move the job to
# ``review``, and write a ``staged`` draft of the registered artifact type.

# (mode, metadata, expected artifact_type, body_json expected non-null?)
_ALL_MODE_CASES = [
    ("watch", {"topic": "AI policy", "source_urls": ["https://example.com/a"]},
     "digest", True),
    ("ask", {"topic": "What is retrieval augmented generation in practice?"},
     "transcript", True),
    ("investigate", {"topic": "Why did the schedule slip this quarter?"},
     "report", True),
    ("survey", {"topic": "Trials of drug X"}, "table", True),
    ("reconstruct", {"topic": "History of the merger"}, "timeline", True),
    ("decide", {"topic": "Which database?",
                "options": ["Postgres", "SQLite"],
                "criteria": [{"label": "scale", "weight": 2.0},
                             {"label": "simple", "weight": 1.0}]},
     "matrix", True),
    ("adjudicate", {"topic": "Is remote work more productive?"},
     "verdict", True),
]


def _draft_row(state_db, draft_id: str):
    conn = open_db(state_db)
    try:
        return conn.execute(
            "SELECT artifact_type, body_json, status, source_count "
            "FROM drafts WHERE id=?", (draft_id,)).fetchone()
    finally:
        conn.close()


@pytest.mark.parametrize("mode,meta,artifact_type,has_body_json", _ALL_MODE_CASES)
def test_all_modes_dispatch_offline(migrated_paths, mode, meta, artifact_type,
                                    has_body_json):
    """Every mode runs offline-deterministically into a staged draft."""
    _insert_job(migrated_paths.state_db, "j1", mode, meta)
    # run_job must never raise; dispatch_once returns the draft id on success.
    draft_id = dispatch_once(migrated_paths)
    assert draft_id is not None, f"{mode} produced no draft"
    assert _job_status(migrated_paths.state_db, "j1") == "review"

    row = _draft_row(migrated_paths.state_db, draft_id)
    assert row is not None
    assert row[0] == artifact_type
    assert row[2] == "staged"
    if has_body_json:
        assert row[1] is not None
        # body_json must be valid JSON.
        assert json.loads(row[1]) is not None


def test_all_modes_never_raise_run_job(migrated_paths):
    """run_job swallows engine errors and marks the job failed, never raises."""
    for i, (mode, meta, _atype, _bj) in enumerate(_ALL_MODE_CASES):
        jid = f"jx{i}"
        _insert_job(migrated_paths.state_db, jid, mode, meta)
        job = claim_one_job(migrated_paths.state_db)
        assert job is not None
        # Should not raise for any mode.
        run_job(migrated_paths, job)  # gateway=None → offline
        assert _job_status(migrated_paths.state_db, jid) == "review"


def test_watch_digest_body_json_shape(migrated_paths):
    meta = {
        "topic": "Breaking news watch",
        "documents": [
            {"id": "i1", "url": "https://x/1", "title": "Breaking: major event",
             "text": "A major breaking development occurred today."},
        ],
    }
    _insert_job(migrated_paths.state_db, "j1", "watch", meta)
    draft_id = dispatch_once(migrated_paths)
    row = _draft_row(migrated_paths.state_db, draft_id)
    body = json.loads(row[1])
    assert body["total_seen"] == 1
    # "Breaking"/"major" keywords push this into the alert bucket deterministically.
    assert len(body["alerts"]) + len(body["digest"]) == 1


def test_ask_transcript_has_turns(migrated_paths):
    meta = {"topic": "Explain what hybrid retrieval does for search quality."}
    _insert_job(migrated_paths.state_db, "j1", "ask", meta)
    draft_id = dispatch_once(migrated_paths)
    row = _draft_row(migrated_paths.state_db, draft_id)
    body = json.loads(row[1])
    roles = [t["role"] for t in body["turns"]]
    assert roles == ["user", "assistant"]


def test_investigate_report_has_sections(migrated_paths):
    meta = {"topic": "Why did revenue decline in the last fiscal year?"}
    _insert_job(migrated_paths.state_db, "j1", "investigate", meta)
    draft_id = dispatch_once(migrated_paths)
    row = _draft_row(migrated_paths.state_db, draft_id)
    body = json.loads(row[1])
    assert len(body["sections"]) >= 1
    assert "question_type" in body


def test_adjudicate_verdict_has_perspectives(migrated_paths):
    meta = {"topic": "Should we adopt a four-day work week?"}
    _insert_job(migrated_paths.state_db, "j1", "adjudicate", meta)
    draft_id = dispatch_once(migrated_paths)
    row = _draft_row(migrated_paths.state_db, draft_id)
    body = json.loads(row[1])
    assert len(body["responses"]) == 4
    assert "judge_summary" in body


# ── runtime gateway resolution (offline; no real LLM call) ──────────────────

def test_build_runtime_gateway_none_when_ollama_absent(migrated_paths, monkeypatch):
    """No installed Ollama tags → None, so the loop uses offline stubs."""
    import lighthouse_ai.pipeline as pl
    monkeypatch.setattr(pl, "_ollama_installed_tags", lambda: [])
    assert build_runtime_gateway(migrated_paths) is None


def test_build_runtime_gateway_real_when_tags_present(migrated_paths, monkeypatch):
    """Installed tags → a real-backend Gateway is constructed (no LLM call made).

    Constructing the Gateway never contacts Ollama; generation only happens
    inside ``Gateway.complete``, which we do not call here.
    """
    import lighthouse_ai.pipeline as pl
    from lighthouse_ai.gateway import Gateway
    monkeypatch.setattr(pl, "_ollama_installed_tags", lambda: ["llama3.1:8b"])
    gw = build_runtime_gateway(migrated_paths)
    assert isinstance(gw, Gateway)
