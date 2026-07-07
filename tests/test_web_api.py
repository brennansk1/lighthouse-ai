"""Tests for the dashboard JSON API (Sprint 22.1–22.3) and the SSE bus."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from lighthouse_ai.controlplane import create_app
from lighthouse_ai.web.events import EventBus, sse_format


@pytest.fixture
def client(migrated_paths):
    return TestClient(create_app(migrated_paths))


# ============================ JOBS ============================


def test_jobs_empty(client):
    assert client.get("/api/jobs").json() == {"jobs": []}


def test_job_create_list_get(client):
    r = client.post("/api/jobs", json={"mode": "Deep-Dive", "topic": "EU AI Act"})
    assert r.status_code == 200
    jid = r.json()["id"]
    listing = client.get("/api/jobs").json()["jobs"]
    assert any(j["id"] == jid for j in listing)
    detail = client.get(f"/api/jobs/{jid}").json()
    assert detail["metadata"]["topic"] == "EU AI Act"
    assert "model_calls" in detail


def test_job_create_persists_depth_and_budget(client):
    r = client.post(
        "/api/jobs",
        json={
            "mode": "investigate",
            "topic": "Deep dive on X",
            "depth": "deep",
            "budget": "overnight",
        },
    )
    assert r.status_code == 200
    jid = r.json()["id"]
    meta = client.get(f"/api/jobs/{jid}").json()["metadata"]
    assert meta["depth"] == "deep"
    assert meta["budget"] == "overnight"


def test_adjudicate_quick_promoted_to_standard(client):
    jid = client.post(
        "/api/jobs", json={"mode": "adjudicate", "topic": "Is X true?", "depth": "quick"}
    ).json()["id"]
    meta = client.get(f"/api/jobs/{jid}").json()["metadata"]
    assert meta["depth"] == "standard"  # Quick adjudication is not allowed


_EXPORT_MODES = [
    (
        "decide",
        {"topic": "A vs B?", "options": ["A", "B"], "criteria": [{"label": "cost", "weight": 1.0}]},
        "matrix",
    ),
    ("adjudicate", {"topic": "Is X true?"}, "verdict"),
    ("investigate", {"topic": "Why did Y happen?"}, "report"),
    ("survey", {"topic": "Trials of Z"}, "table"),
    ("reconstruct", {"topic": "History of W"}, "timeline"),
    ("ask", {"topic": "What is V?"}, "transcript"),
    ("watch", {"topic": "topic U"}, "digest"),
]


@pytest.mark.parametrize("mode,meta,artifact_type", _EXPORT_MODES)
def test_export_all_artifact_types(migrated_paths, client, mode, meta, artifact_type):
    """Every artifact type dispatches offline and exports as md/csv/json."""
    from lighthouse_ai.dispatcher import dispatch_once

    client.post("/api/jobs", json={"mode": mode, **meta})
    draft_id = dispatch_once(migrated_paths)  # offline
    assert draft_id is not None
    for fmt in ("json", "md", "csv"):
        r = client.get(f"/api/library/{draft_id}/export?format={fmt}")
        assert r.status_code == 200, f"{mode}/{fmt} -> {r.status_code}"
        assert r.text, f"{mode}/{fmt} empty"
    detail = client.get(f"/api/library/{draft_id}").json()
    assert detail.get("artifact_type") == artifact_type


def test_classify_suggests_depth_tier(client):
    body = client.get("/api/classify", params={"q": "What is the capital of France?"}).json()
    assert "question_type" in body
    assert body["suggested_tier"] in {"quick", "standard", "thorough", "deep"}


def test_job_get_404(client):
    assert client.get("/api/jobs/nope").status_code == 404


def test_job_pause_resume_cancel(client):
    jid = client.post("/api/jobs", json={"mode": "Monitor", "topic": "x"}).json()["id"]
    assert client.post(f"/api/jobs/{jid}/pause").json()["status"] == "paused"
    assert client.post(f"/api/jobs/{jid}/resume").json()["status"] == "running"
    assert client.post(f"/api/jobs/{jid}/cancel").json()["status"] == "cancelled"


def test_job_pause_404(client):
    assert client.post("/api/jobs/nope/pause").status_code == 404


# ============================ DRAFTS ==========================


def _seed_draft(paths, status="staged"):
    from lighthouse_ai.persistence import open_db

    conn = open_db(paths.state_db)
    try:
        conn.execute(
            "INSERT INTO drafts (id, topic, title, body_html, wep_band, wep_phrase, "
            "source_count, status) VALUES ('d1','T','Title','<p>body</p>','0.85–0.95',"
            "'very likely', 23, ?)",
            (status,),
        )
    finally:
        conn.close()


def test_drafts_list_and_get(migrated_paths, client):
    _seed_draft(migrated_paths)
    assert client.get("/api/drafts").json()["drafts"][0]["id"] == "d1"
    detail = client.get("/api/drafts/d1").json()
    assert "<p>body</p>" in detail["body_html"]


def test_draft_approve(migrated_paths, client):
    _seed_draft(migrated_paths)
    assert client.post("/api/drafts/d1/approve").json()["status"] == "published"
    # No longer staged.
    staged = client.get("/api/drafts?status=staged").json()["drafts"]
    assert not staged


def test_draft_approve_marks_job_done(migrated_paths, client):
    """Approving a draft moves its originating job out of 'review'."""
    from lighthouse_ai.persistence import open_db

    conn = open_db(migrated_paths.state_db)
    try:
        conn.execute(
            "INSERT INTO jobs (id, mode, status, metadata_json) "
            "VALUES ('j1','Deep-Dive','review','{}')"
        )
        conn.execute(
            "INSERT INTO drafts (id, job_id, topic, title, body_html, source_count, status) "
            "VALUES ('dj','j1','T','Ti','<p>b</p>',1,'staged')"
        )
    finally:
        conn.close()
    client.post("/api/drafts/dj/approve")
    jobs = client.get("/api/jobs").json()["jobs"]
    assert next(j for j in jobs if j["id"] == "j1")["status"] == "done"


def test_draft_approve_404_when_not_staged(migrated_paths, client):
    _seed_draft(migrated_paths, status="published")
    assert client.post("/api/drafts/d1/approve").status_code == 404


def test_draft_reject_records_reason(migrated_paths, client):
    _seed_draft(migrated_paths)
    r = client.post("/api/drafts/d1/reject", json={"reason": "stale sources"})
    assert r.json()["status"] == "rejected"
    detail = client.get("/api/drafts/d1").json()
    assert detail["reject_reason"] == "stale sources"


# ============================ TOPICS ==========================


def test_topic_create_get_delete(client):
    r = client.post(
        "/api/topics",
        json={
            "name": "EU AI Act",
            "mode": "Monitor",
            "sources": ["https://a/feed", "https://b/feed"],
        },
    )
    tid = r.json()["id"]
    detail = client.get(f"/api/topics/{tid}").json()
    assert detail["name"] == "EU AI Act"
    assert len(detail["sources"]) == 2
    listing = client.get("/api/topics").json()["topics"]
    assert listing[0]["source_count"] == 2
    assert client.delete(f"/api/topics/{tid}").json()["deleted"] is True
    assert client.get(f"/api/topics/{tid}").status_code == 404


# ====================== MONITOR SESSIONS ======================


def test_monitor_session_create_list_get(client):
    r = client.post(
        "/api/monitor/sessions",
        json={"label": "Hearing", "source_urls": ["https://a/feed"], "auto_stop": True},
    )
    assert r.status_code == 200
    sid = r.json()["id"]
    assert r.json()["status"] == "active"
    listing = client.get("/api/monitor/sessions").json()["sessions"]
    assert any(s["id"] == sid for s in listing)
    detail = client.get(f"/api/monitor/sessions/{sid}").json()
    assert detail["label"] == "Hearing"
    assert detail["source_urls"] == ["https://a/feed"]


def test_monitor_session_get_404(client):
    assert client.get("/api/monitor/sessions/nope").status_code == 404
    assert client.get("/api/monitor/sessions/nope/results").status_code == 404


def test_monitor_session_stop(client):
    sid = client.post("/api/monitor/sessions", json={"label": "S"}).json()["id"]
    r = client.post(f"/api/monitor/sessions/{sid}/stop")
    assert r.json()["status"] == "ended"
    assert r.json()["ended_reason"] == "manual"
    active = client.get("/api/monitor/sessions?status=active").json()["sessions"]
    assert not any(s["id"] == sid for s in active)


def test_monitor_session_stop_404(client):
    assert client.post("/api/monitor/sessions/nope/stop").status_code == 404


def test_monitor_session_results_empty(client):
    sid = client.post("/api/monitor/sessions", json={"label": "S"}).json()["id"]
    assert client.get(f"/api/monitor/sessions/{sid}/results").json() == {"results": []}


# ========================= POSITIONS ==========================


def test_positions_resolve_and_calibration(migrated_paths, client):
    from lighthouse_ai.verification.positions import record_position

    pos = record_position(migrated_paths.positions_db, claim="X happens", probability=0.8)
    # Overdue list shows the unresolved one.
    overdue = client.get("/api/positions?overdue=true").json()["positions"]
    assert any(p["id"] == pos.id for p in overdue)
    r = client.post(f"/api/positions/{pos.id}/resolve", json={"outcome": "confirmed"})
    assert r.json()["outcome"] is True
    cal = client.get("/api/calibration").json()
    assert cal["n"] == 1


def test_position_defer_is_noop(migrated_paths, client):
    from lighthouse_ai.verification.positions import record_position

    pos = record_position(migrated_paths.positions_db, claim="Y", probability=0.5)
    r = client.post(f"/api/positions/{pos.id}/resolve", json={"outcome": "defer"})
    assert r.json()["deferred"] is True


def test_position_resolve_404(client):
    assert (
        client.post("/api/positions/9999/resolve", json={"outcome": "confirmed"}).status_code == 404
    )


# ========================= HYPOTHESES =========================


def test_hypothesis_crud(client):
    hid = client.post("/api/hypotheses", json={"statement": "The sky is blue"}).json()["id"]
    items = client.get("/api/hypotheses").json()["hypotheses"]
    assert any(h["id"] == hid for h in items)
    r = client.patch(f"/api/hypotheses/{hid}", json={"status": "supported"})
    assert r.json()["status"] == "supported"
    supported = client.get("/api/hypotheses?status=supported").json()["hypotheses"]
    assert any(h["id"] == hid for h in supported)


def test_hypothesis_bad_status_400(client):
    hid = client.post("/api/hypotheses", json={"statement": "x"}).json()["id"]
    assert client.patch(f"/api/hypotheses/{hid}", json={"status": "bogus"}).status_code == 400


# ============================ HEALTH ==========================


def test_health_shape(client):
    body = client.get("/api/health").json()
    assert body["overall"] in {"green", "attention"}
    assert "databases" in body
    assert "storage" in body
    assert "external" in body
    # Budget removed — local tool has no spend caps.
    assert "budget" not in body
    # Free RAM is re-probed and surfaced; chosen models are reported.
    assert "free_ram_gb" in body["hardware"]
    assert "chosen_models" in body
    # CPU cores and GPU are surfaced for the Health page diagnostics.
    assert "cpu_cores_logical" in body["hardware"]
    assert "cpu_cores_physical" in body["hardware"]
    assert "gpu" in body["hardware"]


def test_audit_verify_and_list(migrated_paths, client):
    from lighthouse_ai.verification.audit_chain import append_event

    append_event(
        migrated_paths.audit_db,
        actor="t",
        event_type="e",
        payload={"k": 1},
        data_dir=migrated_paths.data_dir,
    )
    events = client.get("/api/audit").json()["events"]
    assert events
    assert client.post("/api/audit/verify").json()["ok"] is True


def test_governor_reset_and_kill(client):
    assert "reset" in client.post("/api/governor/reset").json()
    assert client.post("/api/governor/kill").json()["killed"] is True


# ============================ SETTINGS ========================


def test_settings_returns_config(migrated_paths, client):
    # Write a minimal config.
    migrated_paths.config_file.write_text('[lighthouse]\nversion = "0.1.0"\n')
    body = client.get("/api/settings").json()
    assert body["config"]["lighthouse"]["version"] == "0.1.0"


def test_settings_flat_fields_defaults(client):
    body = client.get("/api/settings").json()
    assert body["offline_mode"] is False
    assert body["backup_enabled"] is False
    assert body["notify_enabled"] is False
    assert body["theme"] == "system"
    assert "data_dir" in body


def test_settings_patch_round_trip(migrated_paths, client):
    # Seed an unrelated section to confirm PATCH preserves it.
    migrated_paths.config_file.write_text('[lighthouse]\nversion = "0.1.0"\n')
    r = client.patch("/api/settings", json={"offline_mode": True, "theme": "dark"})
    assert r.status_code == 200
    body = r.json()
    assert body["offline_mode"] is True
    assert body["theme"] == "dark"
    # Untouched flat field keeps its default; unrelated section is preserved.
    assert body["backup_enabled"] is False
    assert body["config"]["lighthouse"]["version"] == "0.1.0"
    # Persisted across a fresh GET.
    again = client.get("/api/settings").json()
    assert again["offline_mode"] is True
    assert again["theme"] == "dark"


def test_secrets_masked(migrated_paths, client):
    # Seed via a file-backed store so list() can enumerate it regardless of
    # whether a real OS keychain is present on the test machine.
    from lighthouse_ai.secrets import SecretStore

    SecretStore(migrated_paths.data_dir, prefer_keyring=False).put("test.key", "supersecret")
    body = client.get("/api/secrets").json()
    assert body["secrets"].get("test.key") == "***"
    assert "supersecret" not in json.dumps(body)


def test_secrets_post_does_not_leak_value(client):
    """The POST response must never echo the secret value back."""
    r = client.post("/api/secrets", json={"key": "k2", "value": "topsecret"})
    assert "topsecret" not in json.dumps(r.json())


def test_skills_and_perspectives_empty(client):
    assert client.get("/api/skills").json() == {"skills": []}
    assert client.get("/api/perspectives").json() == {"perspectives": []}


# ============================ SSE BUS =========================


def test_event_bus_publish_subscribe():
    bus = EventBus()

    async def run():
        q = bus.subscribe()
        bus.publish("job.status", {"id": "x", "status": "running"})
        msg = await asyncio.wait_for(q.get(), timeout=1.0)
        return msg

    msg = asyncio.run(run())
    assert msg["event"] == "job.status"
    assert msg["data"]["id"] == "x"


def test_event_bus_unsubscribe():
    bus = EventBus()
    q = bus.subscribe()
    assert bus.subscriber_count == 1
    bus.unsubscribe(q)
    assert bus.subscriber_count == 0


def test_sse_format_encoding():
    frame = sse_format({"event": "job.progress", "data": {"id": "x", "progress": 0.5}})
    assert frame.startswith("event: job.progress\n")
    assert '"progress": 0.5' in frame
    assert frame.endswith("\n\n")


def test_event_bus_drops_full_queue():
    bus = EventBus(max_queue=2)

    async def run():
        q = bus.subscribe()
        for i in range(5):
            bus.publish("audit.appended", {"seq": i})
        # Queue capped at 2; publishing more drops the subscriber, not crash.
        return q.qsize()

    size = asyncio.run(run())
    assert size <= 2


def test_create_app_starts_no_daemon(migrated_paths):
    """Safety invariant: create_app() must NOT start the dispatch/monitor loops
    (those belong to serve(run=True) only) — protects against runaway processes."""
    import threading

    create_app(migrated_paths)
    names = {t.name for t in threading.enumerate()}
    assert "dispatch-loop" not in names
    assert "monitor-loop" not in names


def test_api_write_publishes_event(migrated_paths):
    """A job-status change pushes onto the bus."""
    app = create_app(migrated_paths)
    bus = app.state.event_bus
    received = []

    async def run():
        q = bus.subscribe()
        # Use the TestClient inside the loop.
        client = TestClient(app)
        jid = client.post("/api/jobs", json={"mode": "Monitor", "topic": "x"}).json()["id"]
        client.post(f"/api/jobs/{jid}/pause")
        # Drain whatever arrived.
        try:
            while True:
                received.append(await asyncio.wait_for(q.get(), timeout=0.2))
        except TimeoutError:
            pass

    asyncio.run(run())
    kinds = [m["event"] for m in received]
    assert "job.status" in kinds


# ===================== MODES / LIBRARY / ASK (Phase 4) ==================


def test_modes_endpoint_lists_seven(client):
    modes = client.get("/api/modes").json()["modes"]
    keys = {m["key"] for m in modes}
    assert keys == {"watch", "ask", "investigate", "survey", "reconstruct", "decide", "adjudicate"}


def test_create_decide_job_normalizes_and_validates(client):
    # Missing options → 400.
    r = client.post("/api/jobs", json={"mode": "decide", "topic": "db?"})
    assert r.status_code == 400
    # Valid Decide job is accepted and stored under the canonical key.
    r = client.post(
        "/api/jobs",
        json={
            "mode": "Decide",
            "topic": "db?",
            "options": ["a", "b"],
            "criteria": [{"label": "speed", "weight": 1.0}],
        },
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "decide"


def test_legacy_mode_alias_accepted(client):
    r = client.post("/api/jobs", json={"mode": "Deep-Dive", "topic": "x"})
    assert r.json()["mode"] == "investigate"


def _seed_artifact(paths, *, atype="matrix", body=None, status="staged"):
    import json as _json

    from lighthouse_ai.persistence import open_db

    conn = open_db(paths.state_db)
    try:
        conn.execute(
            "INSERT INTO drafts (id, topic, title, body_html, body_json, "
            "artifact_type, source_count, status) "
            "VALUES ('a1','T','Title','<p>b</p>',?,?,2,?)",
            (_json.dumps(body) if body else None, atype, status),
        )
    finally:
        conn.close()


def test_library_lists_and_filters(client, migrated_paths):
    _seed_artifact(migrated_paths, atype="matrix")
    arts = client.get("/api/library").json()["artifacts"]
    assert any(a["id"] == "a1" and a["artifact_type"] == "matrix" for a in arts)
    # Filter by type that doesn't match → empty.
    assert client.get("/api/library?type=timeline").json()["artifacts"] == []


def test_library_get_parses_body(client, migrated_paths):
    _seed_artifact(migrated_paths, body={"winner": "a", "totals": {"a": 0.6}})
    art = client.get("/api/library/a1").json()
    assert art["body"]["winner"] == "a"


def test_library_export_formats(client, migrated_paths):
    _seed_artifact(
        migrated_paths,
        body={
            "cells": [{"option": "a", "criterion": "speed", "score": 0.5, "contribution": 0.5}],
            "totals": {"a": 0.5, "b": 0.4},
        },
    )
    assert client.get("/api/library/a1/export?format=json").json()["id"] == "a1"
    md = client.get("/api/library/a1/export?format=md")
    assert md.status_code == 200 and "# Title" in md.text
    csv = client.get("/api/library/a1/export?format=csv")
    assert csv.status_code == 200 and "option,criterion" in csv.text


def test_ask_sessions_roundtrip(client, migrated_paths):
    from lighthouse_ai.modes.ask_store import save_session
    from lighthouse_ai.modes.quc import QUCSession

    s = QUCSession(id="s1", topic="weather")
    s.add("user", "is it raining?")
    s.add("assistant", "yes", citations=["c1"])
    save_session(migrated_paths.state_db, s, title="Weather chat")

    sessions = client.get("/api/ask/sessions").json()["sessions"]
    assert any(x["id"] == "s1" and x["turn_count"] == 2 for x in sessions)
    full = client.get("/api/ask/sessions/s1").json()
    assert full["turns"][1]["text"] == "yes"
    # Promote the assistant turn into a transcript artifact.
    r = client.post("/api/ask/sessions/s1/turns/1/promote")
    assert r.status_code == 200
    assert r.json()["artifact_type"] == "transcript"


def test_ask_session_404(client):
    assert client.get("/api/ask/sessions/nope").status_code == 404


def test_calibration_timeline_empty(client):
    r = client.get("/api/calibration/timeline").json()
    assert r["bucket"] == "week"
    assert r["buckets"] == []


# ============== mode-specific wizard inputs (UX sweep) ==============


def test_job_create_passes_survey_attributes(client):
    """Survey's evidence-table columns must reach job meta — without them the
    dispatcher falls back to a single placeholder 'summary' column."""
    r = client.post(
        "/api/jobs",
        json={
            "mode": "survey",
            "topic": "GLP-1 trials",
            "attributes": [
                {"label": "sample size", "keywords": ["patients", "n="]},
                {"label": "methodology", "keywords": []},
            ],
        },
    )
    assert r.status_code == 200
    meta = client.get(f"/api/jobs/{r.json()['id']}").json()["metadata"]
    assert [a["label"] for a in meta["attributes"]] == ["sample size", "methodology"]


def test_job_create_passes_adjudicate_draft(client):
    """Adjudicate's debate target must reach job meta — without it the engine
    debates the bare claim."""
    r = client.post(
        "/api/jobs",
        json={
            "mode": "adjudicate",
            "topic": "The rollout is safe",
            "draft": "Our analysis concludes the rollout is safe because…",
        },
    )
    assert r.status_code == 200
    meta = client.get(f"/api/jobs/{r.json()['id']}").json()["metadata"]
    assert meta["draft"].startswith("Our analysis concludes")


# ===================== watch alerts + pause/resume =====================


def _make_monitor(client, url="https://example.com/page"):
    r = client.post("/api/watch/web", json={"url": url})
    assert r.status_code == 200, r.text
    return r.json()


def _insert_alert(state_db, monitor_id: str, url: str, reason: str) -> None:
    """Insert a fired alert the way the tick runner does (inline SQL)."""
    import uuid

    from lighthouse_ai.persistence import open_db

    conn = open_db(state_db)
    try:
        conn.execute(
            "INSERT INTO web_monitor_alerts "
            "(id, monitor_id, url, fired_at, reason, details_json) "
            "VALUES (?, ?, ?, ?, ?, '{}')",
            (uuid.uuid4().hex, monitor_id, url, "2026-06-10T12:00:00", reason),
        )
    finally:
        conn.close()


def test_watch_alerts_endpoint_lists_fired_alerts(client, migrated_paths):
    m = _make_monitor(client)
    _insert_alert(migrated_paths.state_db, m["id"], m["url"], "keyword 'recall' newly present")
    r = client.get("/api/watch/web/alerts")
    assert r.status_code == 200
    alerts = r.json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["reason"] == "keyword 'recall' newly present"
    # Filter by monitor id works too.
    assert client.get(f"/api/watch/web/alerts?monitor_id={m['id']}").json()["alerts"]
    assert client.get("/api/watch/web/alerts?monitor_id=nope").json()["alerts"] == []


def test_watch_pause_and_resume(client):
    m = _make_monitor(client)
    r = client.patch(f"/api/watch/web/{m['id']}", json={"status": "paused"})
    assert r.status_code == 200
    assert r.json()["status"] == "paused"
    listed = client.get("/api/watch/web").json()["monitors"]
    assert listed[0]["status"] == "paused"
    r2 = client.patch(f"/api/watch/web/{m['id']}", json={"status": "active"})
    assert r2.json()["status"] == "active"


def test_watch_pause_validates_input(client):
    m = _make_monitor(client)
    assert (
        client.patch(f"/api/watch/web/{m['id']}", json={"status": "destroyed"}).status_code == 422
    )
    assert client.patch("/api/watch/web/nope", json={"status": "paused"}).status_code == 404


def test_dashboard_alert_strip_surfaces_fired_watch_alerts(client, migrated_paths):
    m = _make_monitor(client)
    _insert_alert(migrated_paths.state_db, m["id"], m["url"], "page changed")
    dash = client.get("/api/dashboard").json()
    kinds = [a["kind"] for a in dash.get("alerts", [])]
    assert "watch" in kinds


def test_ask_session_dict_exposes_skill_audit_trail(client, migrated_paths):
    from lighthouse_ai.modes.ask_store import get_session_dict, save_session
    from lighthouse_ai.modes.quc import QUCSession, Turn

    s = QUCSession(id="a-ux1", topic="Rates")
    s.history.append(
        Turn(
            role="assistant",
            text="Answer [1].",
            citations=["c1"],
            skill_ids_used=["fred"],
            adjudicate_flag=True,
        )
    )
    save_session(migrated_paths.state_db, s)
    d = get_session_dict(migrated_paths.state_db, "a-ux1")
    assert d["turns"][0]["skill_ids_used"] == ["fred"]
    assert d["turns"][0]["adjudicate_flag"] is True
