"""SB3 — sandbox web API endpoints."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from lighthouse_ai.controlplane import create_app

EICAR = base64.b64encode(
    rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
).decode()


@pytest.fixture
def client(migrated_paths):
    return TestClient(create_app(migrated_paths))


def _b64(s: bytes) -> str:
    return base64.b64encode(s).decode()


def test_upload_admitted_then_listed(client):
    r = client.post(
        "/api/sandbox/upload",
        json={
            "filename": "notes.txt",
            "content_base64": _b64(b"hello sandbox world"),
            "content_type": "text/plain",
        },
    )
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["zone"] == "uploads" and item["scan_verdict"] == "admit"

    listing = client.get("/api/sandbox").json()
    assert any(i["id"] == item["id"] for i in listing["items"])
    assert listing["usage"]["used_bytes"] >= len(b"hello sandbox world")
    assert "by_zone" in listing["breakdown"]


def test_upload_eicar_rejected(client):
    r = client.post("/api/sandbox/upload", json={"filename": "x.com", "content_base64": EICAR})
    # REJECT → 422, never becomes a readable admitted upload.
    assert r.status_code == 422
    listing = client.get("/api/sandbox").json()
    assert listing["items"] == []


def test_bad_base64_400(client):
    r = client.post(
        "/api/sandbox/upload", json={"filename": "x.txt", "content_base64": "!!!not base64!!!"}
    )
    assert r.status_code == 400


def test_pin_then_delete(client):
    up = client.post(
        "/api/sandbox/upload", json={"filename": "a.txt", "content_base64": _b64(b"keep me")}
    ).json()
    rid = up["id"]
    rp = client.post(f"/api/sandbox/{rid}/pin", json={"pinned": True})
    assert rp.status_code == 200 and rp.json()["pinned"] is True
    rd = client.delete(f"/api/sandbox/{rid}")
    assert rd.status_code == 200 and rd.json()["removed"] is True
    assert client.delete(f"/api/sandbox/{rid}").status_code == 404


def test_config_roundtrip(client):
    assert client.get("/api/sandbox/config").status_code == 200
    r = client.put("/api/sandbox/config", json={"max_bytes": 1048576})
    assert r.status_code == 200 and r.json()["max_bytes"] == 1048576
    assert client.get("/api/sandbox/config").json()["max_bytes"] == 1048576
    # negative rejected
    assert client.put("/api/sandbox/config", json={"max_bytes": -1}).status_code == 400


def test_pin_unknown_item_404(client):
    assert client.post("/api/sandbox/nope/pin", json={"pinned": True}).status_code == 404
