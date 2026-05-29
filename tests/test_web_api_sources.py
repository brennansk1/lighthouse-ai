"""Tests for Zone K — the web API for source selection.

Covers GET /api/sources (skill catalog), GET /api/recommend-sources (mode-aware
ranking, offline-safe), and POST /api/jobs persisting selected_skills into the
job's metadata. All offline-deterministic; no real LLM or network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lighthouse_ai.controlplane import create_app


@pytest.fixture
def client(migrated_paths):
    return TestClient(create_app(migrated_paths))


# ============================ SOURCES ============================

def test_sources_returns_catalog(client):
    """GET /api/sources returns the skill catalog with picker-ready fields."""
    body = client.get("/api/sources").json()
    assert "sources" in body
    sources = body["sources"]
    assert isinstance(sources, list)
    # Tolerate an empty library, but if seed skills are present validate shape.
    if sources:
        ids = {s["id"] for s in sources}
        # The four seed skills ship with the repo.
        assert {"arxiv", "general_web", "wikipedia", "youtube"} <= ids
        for s in sources:
            for key in ("id", "name", "description", "category", "tier",
                        "default_grade", "community", "enabled_by_default"):
                assert key in s, f"missing {key} in source payload"


# ======================= RECOMMEND-SOURCES =======================

def test_recommend_sources_returns_list(client):
    """GET /api/recommend-sources returns a ranked recommended list."""
    r = client.get("/api/recommend-sources",
                   params={"q": "What does arXiv say about transformers?",
                           "mode": "investigate"})
    assert r.status_code == 200
    body = r.json()
    assert "recommended" in body
    recs = body["recommended"]
    assert isinstance(recs, list)
    if recs:
        for rec in recs:
            assert set(rec) == {"skill_id", "score", "reason", "role"}
            assert isinstance(rec["score"], (int, float))


def test_recommend_sources_with_depth(client):
    """The optional depth param is accepted and stays offline-safe."""
    r = client.get("/api/recommend-sources",
                   params={"q": "history of the EU AI Act",
                           "mode": "reconstruct", "depth": "deep"})
    assert r.status_code == 200
    assert isinstance(r.json()["recommended"], list)


def test_recommend_sources_default_mode(client):
    """Mode defaults to investigate when omitted; still 200 with a list."""
    r = client.get("/api/recommend-sources", params={"q": "anything"})
    assert r.status_code == 200
    assert isinstance(r.json()["recommended"], list)


def test_recommend_sources_never_500(client):
    """Even an empty/degenerate question returns 200, not 500."""
    r = client.get("/api/recommend-sources", params={"q": "", "mode": "bogus"})
    assert r.status_code == 200
    assert isinstance(r.json()["recommended"], list)


# ===================== SELECTED_SKILLS ON JOBS ===================

def test_job_persists_selected_skills(client):
    """POST /api/jobs with selected_skills stores them in metadata.selected_skills."""
    r = client.post("/api/jobs", json={
        "mode": "investigate", "topic": "transformers",
        "selected_skills": ["arxiv", "general_web"]})
    assert r.status_code == 200
    jid = r.json()["id"]
    meta = client.get(f"/api/jobs/{jid}").json()["metadata"]
    assert meta["selected_skills"] == ["arxiv", "general_web"]


def test_job_without_selected_skills_omits_key(client):
    """Old clients (no selected_skills) are unaffected: key simply absent."""
    r = client.post("/api/jobs", json={"mode": "investigate", "topic": "x"})
    assert r.status_code == 200
    jid = r.json()["id"]
    meta = client.get(f"/api/jobs/{jid}").json()["metadata"]
    assert "selected_skills" not in meta
