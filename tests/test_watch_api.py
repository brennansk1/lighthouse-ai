"""Tests for the Watch v2 API surface (/api/watch/...).

The verify endpoint's network fetch is monkeypatched at module scope so no
socket opens; the CRUD endpoints round-trip against the migrated state.db.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lighthouse_ai.controlplane import create_app


@pytest.fixture
def client(migrated_paths):
    return TestClient(create_app(migrated_paths))


class _FakeResp:
    def __init__(self, status_code=200, headers=None, content=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content


_GOOD_HTML = (
    b"<html><head><title>News</title></head><body>"
    + b"<p>" + (b"word " * 80) + b"</p>"
    + b"</body></html>"
)


# ---------------------------- verify ----------------------------


def test_verify_good(client, monkeypatch):
    def fake_fetch(url: str):
        return _FakeResp(
            200, {"content-type": "text/html", "etag": '"abc"'}, _GOOD_HTML
        )

    monkeypatch.setattr("lighthouse_ai.web.api._watch_fetch", fake_fetch)
    # A trusted (allowlisted) host so the verdict is reachable → can_watch True.
    r = client.post(
        "/api/watch/verify", json={"url": "https://en.wikipedia.org/wiki/News"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["can_watch"] is True
    assert body["status"] in {"good", "limited"}
    assert "watch" in body["headline"].lower()
    # No internal jargon leaks.
    for leak in ("extract_tier", "robots_ok", "verdict", "reachable"):
        assert leak not in body


def test_verify_blocked_no_readable_content(client, monkeypatch):
    # A trusted host (so reachable) that returns an empty body and no feed →
    # there is nothing to watch → blocked, plain-language.
    def fake_fetch(url: str):
        return _FakeResp(200, {"content-type": "text/html"}, b"")

    monkeypatch.setattr("lighthouse_ai.web.api._watch_fetch", fake_fetch)
    r = client.post(
        "/api/watch/verify", json={"url": "https://en.wikipedia.org/empty"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["can_watch"] is False
    assert body["status"] == "blocked"
    assert "nothing readable" in body["headline"].lower()
    # No internal jargon leaks.
    for leak in ("extract_tier", "robots_ok", "verdict", "reachable"):
        assert leak not in body


def test_verify_untrusted_host_prompts_trust(client, monkeypatch):
    # A reachable fetch but a host the user has NOT trusted → trust prompt.
    def fake_fetch(url: str):
        return _FakeResp(200, {"content-type": "text/html"}, _GOOD_HTML)

    monkeypatch.setattr("lighthouse_ai.web.api._watch_fetch", fake_fetch)
    r = client.post(
        "/api/watch/verify", json={"url": "https://newsite.example/page"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["can_watch"] is False
    assert body["needs_trust"] is True
    assert body["trust_hint"] == "newsite.example"
    assert "trusted sites" in body["headline"].lower()


def test_verify_egress_blocked_prompts_trust(client, monkeypatch):
    from lighthouse_ai.net import EgressBlocked

    def fake_fetch(url: str):
        raise EgressBlocked("host not on allowlist")

    monkeypatch.setattr("lighthouse_ai.web.api._watch_fetch", fake_fetch)
    r = client.post("/api/watch/verify", json={"url": "https://untrusted.test/x"})
    assert r.status_code == 200
    body = r.json()
    assert body["can_watch"] is False
    assert body["needs_trust"] is True
    assert "trusted sites" in body["headline"].lower()
    assert body["trust_hint"] == "untrusted.test"


def test_verify_requires_url(client):
    r = client.post("/api/watch/verify", json={"url": "  "})
    assert r.status_code == 422


# ---------------------------- web CRUD round-trip ----------------------------


def test_web_create_list_delete(client):
    r = client.post(
        "/api/watch/web",
        json={"url": "https://example.com/page", "name": "My Page"},
    )
    assert r.status_code == 200
    monitor = r.json()
    assert monitor["url"] == "https://example.com/page"
    assert monitor["name"] == "My Page"
    assert monitor["criteria"] == {"kind": "any_change"}
    assert monitor["cadence_seconds"] == 3600  # default 60 minutes
    mid = monitor["id"]

    listing = client.get("/api/watch/web").json()["monitors"]
    assert any(m["id"] == mid for m in listing)

    d = client.delete(f"/api/watch/web/{mid}")
    assert d.status_code == 200
    assert d.json() == {"deleted": mid}
    assert client.get("/api/watch/web").json()["monitors"] == []


def test_web_create_custom_cadence_and_criteria(client):
    r = client.post(
        "/api/watch/web",
        json={
            "url": "https://news.test",
            "criteria": {"kind": "keyword", "terms": ["recall"]},
            "cadence_minutes": 15,
        },
    )
    assert r.status_code == 200
    m = r.json()
    assert m["cadence_seconds"] == 900
    assert m["criteria"]["kind"] == "keyword"


def test_web_delete_missing_404(client):
    assert client.delete("/api/watch/web/nope").status_code == 404
