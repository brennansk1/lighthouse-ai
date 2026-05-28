"""Unit tests for the FastAPI control plane (in-process via TestClient)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lighthouse_ai.controlplane import create_app


def test_health_with_no_dbs_returns_payload(tmp_paths):
    """Pre-migration, /health still responds and reports DBs as absent."""
    client = TestClient(create_app(tmp_paths))
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["version"]
    assert body["supervisor"]["status"] in {"uninitialized", "unmigrated"}
    assert set(body["databases"].keys()) == {"state", "audit", "intents", "positions", "hypotheses"}
    for v in body["databases"].values():
        assert v["present"] is False


def test_health_after_migration_reports_integrity_ok(migrated_paths):
    client = TestClient(create_app(migrated_paths))
    body = client.get("/health").json()
    for kind, info in body["databases"].items():
        assert info["present"], kind
        assert info["integrity_check"] == "ok"
    assert body["supervisor"]["status"] == "running"


def test_governor_stub_returns_zero_depth(migrated_paths):
    client = TestClient(create_app(migrated_paths))
    body = client.get("/governor").json()
    assert body == {"outbox_depth": 0, "degradation_tier": "green", "kill_switched": False}


def test_governor_outbox_depth_reflects_intents(migrated_paths):
    from lighthouse_ai.persistence import open_db
    conn = open_db(migrated_paths.intents_db)
    try:
        for i in range(3):
            conn.execute(
                "INSERT INTO intents (idempotency_key,target,op,payload_json) "
                "VALUES (?, 't', 'o', '{}')", (f"k{i}",),
            )
    finally:
        conn.close()
    client = TestClient(create_app(migrated_paths))
    assert client.get("/governor").json()["outbox_depth"] == 3


def test_root_redirects_to_ui(tmp_paths):
    """Sprint 15 added a web dashboard at /ui/; `/` is now a redirect."""
    client = TestClient(create_app(tmp_paths))
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (301, 302, 307)
    assert "/ui" in r.headers["location"]
