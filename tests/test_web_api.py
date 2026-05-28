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
            "'very likely', 23, ?)", (status,))
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
        conn.execute("INSERT INTO jobs (id, mode, status, metadata_json) "
                     "VALUES ('j1','Deep-Dive','review','{}')")
        conn.execute(
            "INSERT INTO drafts (id, job_id, topic, title, body_html, source_count, status) "
            "VALUES ('dj','j1','T','Ti','<p>b</p>',1,'staged')")
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
    r = client.post("/api/topics", json={"name": "EU AI Act", "mode": "Monitor",
                                         "sources": ["https://a/feed", "https://b/feed"]})
    tid = r.json()["id"]
    detail = client.get(f"/api/topics/{tid}").json()
    assert detail["name"] == "EU AI Act"
    assert len(detail["sources"]) == 2
    listing = client.get("/api/topics").json()["topics"]
    assert listing[0]["source_count"] == 2
    assert client.delete(f"/api/topics/{tid}").json()["deleted"] is True
    assert client.get(f"/api/topics/{tid}").status_code == 404


# ========================= POSITIONS ==========================

def test_positions_resolve_and_calibration(migrated_paths, client):
    from lighthouse_ai.verification.positions import record_position
    pos = record_position(migrated_paths.positions_db, claim="X happens",
                          probability=0.8)
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
    assert client.post("/api/positions/9999/resolve",
                       json={"outcome": "confirmed"}).status_code == 404


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
    assert "budget" in body
    assert "storage" in body
    assert "external" in body


def test_audit_verify_and_list(migrated_paths, client):
    from lighthouse_ai.verification.audit_chain import append_event
    append_event(migrated_paths.audit_db, actor="t", event_type="e",
                 payload={"k": 1}, data_dir=migrated_paths.data_dir)
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


def test_secrets_masked(migrated_paths, client):
    # Seed via a file-backed store so list() can enumerate it regardless of
    # whether a real OS keychain is present on the test machine.
    from lighthouse_ai.secrets import SecretStore
    SecretStore(migrated_paths.data_dir, prefer_keyring=False).put(
        "test.key", "supersecret")
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
