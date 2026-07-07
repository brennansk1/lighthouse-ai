"""Tests for provenance emission (§27.7) and the replay tool (§27.8).

These exercise replay/verify against a migrated tmp audit.db seeded with
model_call rows that mirror the gateway's recorded payload shape, plus the
PROV-O JSON-LD round trip through provenance.jsonl. No model is ever loaded.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lighthouse_ai.persistence import open_db
from lighthouse_ai.provenance import (
    PROV_CONTEXT,
    ProvenanceLog,
    load_provenance,
    prov_activity,
)
from lighthouse_ai.replay import (
    ReplayDriftError,
    ReplayReport,
    ReplayStep,
    ReplayTrace,
    replay_job,
    verify_replayable,
)
from lighthouse_ai.schema import migrate_path

# --- fixtures / helpers ---------------------------------------------------


def _make_payload(
    job_id: str,
    model: str,
    digest: str,
    *,
    prompt_tokens: int = 10,
    completion_tokens: int = 20,
    backend: str = "ollama",
) -> dict:
    """Mirror the gateway ``_record`` payload shape for a model_call event."""
    return {
        "role": "researcher",
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "usd": 0.0,
        "fingerprint": {
            "model_string": model,
            "registry_digest_sha256": digest,
            "backend": backend,
            "runtime_version": "0.1",
            "pulled_at": "2026-05-27T00:00:00Z",
        },
        "prompt_preview": "hello",
        "job_id": job_id,
        "backend_used": backend,
    }


def _insert(
    conn, payload: dict, *, actor: str = "gateway:researcher", event_type: str = "model_call"
) -> None:
    conn.execute(
        "INSERT INTO audit_events (actor, event_type, payload_json) VALUES (?, ?, ?)",
        (actor, event_type, json.dumps(payload, sort_keys=True)),
    )


@pytest.fixture()
def audit_db(tmp_path: Path) -> Path:
    db = tmp_path / "audit.db"
    migrate_path(db, "audit")
    return db


# --- replay_job reconstruction --------------------------------------------


def test_replay_job_empty_when_no_events(audit_db: Path) -> None:
    trace = replay_job(audit_db, "job-none")
    assert isinstance(trace, ReplayTrace)
    assert len(trace) == 0
    assert trace.steps == ()


def test_replay_job_reconstructs_single_step(audit_db: Path) -> None:
    conn = open_db(audit_db)
    try:
        _insert(conn, _make_payload("job-1", "llama3", "aaa"))
    finally:
        conn.close()
    trace = replay_job(audit_db, "job-1")
    assert len(trace) == 1
    step = trace.steps[0]
    assert isinstance(step, ReplayStep)
    assert step.model == "llama3"
    assert step.digest == "aaa"
    assert step.job_id == "job-1"


def test_replay_job_preserves_insertion_order(audit_db: Path) -> None:
    conn = open_db(audit_db)
    try:
        for i, model in enumerate(["m0", "m1", "m2", "m3"]):
            _insert(conn, _make_payload("job-ord", model, f"d{i}"))
    finally:
        conn.close()
    trace = replay_job(audit_db, "job-ord")
    assert [s.model for s in trace.steps] == ["m0", "m1", "m2", "m3"]
    # seq is monotonically increasing
    seqs = [s.seq for s in trace.steps]
    assert seqs == sorted(seqs)


def test_replay_job_filters_by_job_id(audit_db: Path) -> None:
    conn = open_db(audit_db)
    try:
        _insert(conn, _make_payload("job-a", "m", "1"))
        _insert(conn, _make_payload("job-b", "m", "2"))
        _insert(conn, _make_payload("job-a", "m", "3"))
    finally:
        conn.close()
    trace = replay_job(audit_db, "job-a")
    assert len(trace) == 2
    assert all(s.job_id == "job-a" for s in trace.steps)
    assert [s.digest for s in trace.steps] == ["1", "3"]


def test_replay_job_ignores_non_model_call_events(audit_db: Path) -> None:
    conn = open_db(audit_db)
    try:
        _insert(conn, {"job_id": "job-x", "foo": "bar"}, event_type="heartbeat")
        _insert(conn, _make_payload("job-x", "m", "z"))
    finally:
        conn.close()
    trace = replay_job(audit_db, "job-x")
    assert len(trace) == 1
    assert trace.steps[0].digest == "z"


def test_replay_job_captures_tokens_and_backend(audit_db: Path) -> None:
    conn = open_db(audit_db)
    try:
        _insert(
            conn,
            _make_payload(
                "job-tok", "m", "d", prompt_tokens=7, completion_tokens=13, backend="ollama"
            ),
        )
    finally:
        conn.close()
    step = replay_job(audit_db, "job-tok").steps[0]
    assert step.prompt_tokens == 7
    assert step.completion_tokens == 13
    assert step.backend == "ollama"
    assert step.ts is not None


def test_replay_trace_models_first_seen_order(audit_db: Path) -> None:
    conn = open_db(audit_db)
    try:
        for model, digest in [("b", "1"), ("a", "2"), ("b", "3"), ("c", "4")]:
            _insert(conn, _make_payload("job-m", model, digest))
    finally:
        conn.close()
    trace = replay_job(audit_db, "job-m")
    assert trace.models == ["b", "a", "c"]


def test_replay_job_tolerates_malformed_payload(audit_db: Path) -> None:
    conn = open_db(audit_db)
    try:
        conn.execute(
            "INSERT INTO audit_events (actor, event_type, payload_json) VALUES (?, 'model_call', ?)",
            ("gateway:x", "not-json"),
        )
        _insert(conn, _make_payload("job-ok", "m", "d"))
    finally:
        conn.close()
    trace = replay_job(audit_db, "job-ok")
    assert len(trace) == 1


# --- verify_replayable drift detection ------------------------------------


def test_verify_all_replayable(audit_db: Path) -> None:
    conn = open_db(audit_db)
    try:
        _insert(conn, _make_payload("job-r", "m1", "dig1"))
        _insert(conn, _make_payload("job-r", "m2", "dig2"))
    finally:
        conn.close()
    report = verify_replayable(
        audit_db,
        "job-r",
        installed_digests={"m1": "dig1", "m2": "dig2"},
    )
    assert isinstance(report, ReplayReport)
    assert report.fully_replayable
    assert report.drifted_steps == []
    assert report.first_divergence is None
    assert len(report.replayable_steps) == 2


def test_verify_flags_drift_and_raises(audit_db: Path) -> None:
    conn = open_db(audit_db)
    try:
        _insert(conn, _make_payload("job-d", "m1", "dig1"))
        _insert(conn, _make_payload("job-d", "m2", "OLD"))
    finally:
        conn.close()
    with pytest.raises(ReplayDriftError) as exc:
        verify_replayable(audit_db, "job-d", installed_digests={"m1": "dig1", "m2": "NEW"})
    report = exc.value.report
    assert not report.fully_replayable
    assert len(report.drifted_steps) == 1
    assert report.drifted_steps[0].step.model == "m2"


def test_verify_allow_drift_returns_report(audit_db: Path) -> None:
    conn = open_db(audit_db)
    try:
        _insert(conn, _make_payload("job-ad", "m1", "OLD"))
    finally:
        conn.close()
    report = verify_replayable(
        audit_db, "job-ad", installed_digests={"m1": "NEW"}, allow_drift=True
    )
    assert not report.fully_replayable
    assert report.verdicts[0].drifted is True
    assert report.verdicts[0].replayable is False


def test_verify_missing_model_is_not_drift_but_not_replayable(audit_db: Path) -> None:
    conn = open_db(audit_db)
    try:
        _insert(conn, _make_payload("job-miss", "ghost", "dig"))
    finally:
        conn.close()
    report = verify_replayable(
        audit_db,
        "job-miss",
        installed_digests={},  # nothing installed
        allow_drift=True,
    )
    verdict = report.verdicts[0]
    assert verdict.replayable is False
    assert verdict.drifted is False  # absent != drifted
    assert verdict.installed_digest is None
    assert "not-installed" in verdict.reason


def test_verify_first_divergence_is_earliest(audit_db: Path) -> None:
    conn = open_db(audit_db)
    try:
        _insert(conn, _make_payload("job-fd", "m1", "ok1"))
        _insert(conn, _make_payload("job-fd", "m2", "BAD"))
        _insert(conn, _make_payload("job-fd", "m3", "BAD3"))
    finally:
        conn.close()
    report = verify_replayable(
        audit_db,
        "job-fd",
        installed_digests={"m1": "ok1", "m2": "GOOD", "m3": "GOOD3"},
        allow_drift=True,
    )
    div = report.first_divergence
    assert div is not None
    assert div.step.model == "m2"


def test_verify_verdict_reason_strings(audit_db: Path) -> None:
    conn = open_db(audit_db)
    try:
        _insert(conn, _make_payload("job-rsn", "m1", "same"))
        _insert(conn, _make_payload("job-rsn", "m2", "old"))
    finally:
        conn.close()
    report = verify_replayable(
        audit_db, "job-rsn", installed_digests={"m1": "same", "m2": "new"}, allow_drift=True
    )
    reasons = {v.step.model: v.reason for v in report.verdicts}
    assert "byte-exact" in reasons["m1"]
    assert "drifted" in reasons["m2"]


def test_verify_empty_job_is_fully_replayable(audit_db: Path) -> None:
    # A job with no model calls vacuously replays.
    report = verify_replayable(audit_db, "job-empty", installed_digests={})
    assert report.fully_replayable
    assert report.verdicts == ()


# --- PROV-O builder + round trip ------------------------------------------


def test_prov_activity_shape() -> None:
    rec = prov_activity(
        activity_id="9f3a",
        agent="section_researcher",
        used=["sha256:abc", "arxiv_search"],
        generated="c12",
        attributed_to="8f4",
        started_at=datetime(2026, 5, 27, 14, 33, 12, tzinfo=UTC),
        ended_at=datetime(2026, 5, 27, 14, 33, 18, tzinfo=UTC),
    )
    assert rec["@context"] == PROV_CONTEXT
    assert rec["@type"] == "prov:Activity"
    assert rec["@id"] == "urn:lighthouse:action:9f3a"
    assert rec["prov:wasAssociatedWith"] == "urn:lighthouse:agent:section_researcher"
    assert rec["prov:generated"] == "urn:lighthouse:artifact:c12"
    assert rec["prov:wasAttributedTo"] == "urn:lighthouse:model:sha256:8f4"
    assert rec["prov:startedAtTime"] == "2026-05-27T14:33:12Z"
    assert rec["prov:endedAtTime"] == "2026-05-27T14:33:18Z"
    assert isinstance(rec["prov:used"], list)
    assert len(rec["prov:used"]) == 2


def test_prov_activity_optional_fields_omitted() -> None:
    rec = prov_activity(activity_id="x", agent="a")
    assert "prov:generated" not in rec
    assert "prov:wasAttributedTo" not in rec
    assert "prov:startedAtTime" not in rec
    assert rec["prov:used"] == []


def test_prov_activity_preserves_full_urns() -> None:
    rec = prov_activity(
        activity_id="x",
        agent="a",
        used=["urn:lighthouse:source:s1"],
        generated="urn:lighthouse:claim:c1",
        attributed_to="urn:lighthouse:model:sha256:m1",
    )
    assert rec["prov:used"] == ["urn:lighthouse:source:s1"]
    assert rec["prov:generated"] == "urn:lighthouse:claim:c1"
    assert rec["prov:wasAttributedTo"] == "urn:lighthouse:model:sha256:m1"


def test_prov_activity_naive_datetime_treated_as_utc() -> None:
    rec = prov_activity(activity_id="x", agent="a", started_at=datetime(2026, 1, 1, 0, 0, 0))
    assert rec["prov:startedAtTime"] == "2026-01-01T00:00:00Z"


def test_provenance_log_round_trip(tmp_path: Path) -> None:
    log = ProvenanceLog(dir=tmp_path)
    r1 = log.append_activity(activity_id="a1", agent="researcher", generated="c1")
    r2 = log.append_activity(activity_id="a2", agent="critic", used=["c1"])
    assert log.path.name == "provenance.jsonl"
    loaded = log.load()
    assert loaded == [r1, r2]


def test_load_provenance_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_provenance(tmp_path / "nope.jsonl") == []


def test_load_provenance_skips_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "provenance.jsonl"
    rec = prov_activity(activity_id="a", agent="x")
    p.write_text(json.dumps(rec) + "\n\n\n", encoding="utf-8")
    loaded = load_provenance(p)
    assert loaded == [rec]


def test_provenance_log_appends_not_truncates(tmp_path: Path) -> None:
    log = ProvenanceLog(dir=tmp_path)
    log.append_activity(activity_id="a", agent="x")
    log2 = ProvenanceLog(dir=tmp_path)
    log2.append_activity(activity_id="b", agent="y")
    assert len(load_provenance(log.path)) == 2


def test_append_then_torn_write_does_not_corrupt_prior_records(tmp_path: Path) -> None:
    """A crash that leaves a torn final line must not destroy earlier records.

    Simulates a power loss mid-append: a complete record followed by a
    partial (newline-less, half-written) JSON fragment. ``load_provenance``
    must still return the intact record and simply drop the torn tail.
    """
    log = ProvenanceLog(dir=tmp_path)
    rec = log.append_activity(activity_id="a", agent="x")
    # Simulate a torn append: a partial JSON fragment with no newline.
    with log.path.open("a", encoding="utf-8") as fh:
        fh.write('{"@id": "urn:lighthouse:action:b", "@ty')  # truncated
    loaded = load_provenance(log.path)
    assert loaded == [rec]  # first record survives; torn tail dropped


def test_load_provenance_reraises_on_midfile_corruption(tmp_path: Path) -> None:
    """Corruption in a non-final line is real tampering, not a torn tail."""
    p = tmp_path / "provenance.jsonl"
    p.write_text('{"ok": 1}\nNOT JSON\n{"ok": 2}\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_provenance(p)


def test_provenance_jsonl_is_one_json_object_per_line(tmp_path: Path) -> None:
    log = ProvenanceLog(dir=tmp_path)
    log.append_activity(activity_id="a", agent="x")
    log.append_activity(activity_id="b", agent="y")
    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)  # each line parses independently
        assert obj["@type"] == "prov:Activity"
