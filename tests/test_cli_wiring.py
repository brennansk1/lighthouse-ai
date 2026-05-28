"""Tests for Sprint-27 runtime wiring: replay/backup/integrity CLI commands,
research --url ingestion, and the notification hook."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lighthouse_ai.cli import app


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LIGHTHOUSE_DATA_DIR", str(tmp_path / "data"))
    runner = CliRunner()
    runner.invoke(app, ["init", "--data-dir", str(tmp_path / "data"),
                        "--no-install-service"])
    return tmp_path / "data"


def test_integrity_passes_on_fresh_dbs(env):
    r = CliRunner().invoke(app, ["integrity"])
    assert r.exit_code == 0
    assert "integrity ok" in r.stdout


def test_replay_graceful_when_no_job(env):
    r = CliRunner().invoke(app, ["replay", "nope"])
    assert r.exit_code == 0
    assert "no model calls" in r.stdout


def test_replay_reconstructs_recorded_trace(env):
    # seed a model_call audit row for a job
    import json
    from lighthouse_ai.persistence import open_db
    conn = open_db(env / "audit.db")
    try:
        conn.execute(
            "INSERT INTO audit_events (actor, event_type, payload_json) "
            "VALUES ('gateway:planner','model_call',?)",
            (json.dumps({"job_id": "j1", "model": "qwen3:14b",
                         "prompt_tokens": 10, "completion_tokens": 5,
                         "fingerprint": {"registry_digest_sha256": "abc"}}),))
    finally:
        conn.close()
    r = CliRunner().invoke(app, ["replay", "j1", "--allow-drift"])
    assert r.exit_code == 0
    assert "1 step" in r.stdout


def test_backup_refuses_without_restic(env, monkeypatch):
    # Force restic-absent path deterministically.
    import lighthouse_ai.backup as b
    monkeypatch.setattr(b, "restic_installed", lambda: False)
    r = CliRunner().invoke(app, ["backup"])
    assert r.exit_code == 1   # refused (message goes to stderr)


def test_research_url_ingests_via_sandbox(env, monkeypatch):
    """research --url fetches + sandbox-admits + ingests, offline synthesis."""
    import httpx
    import respx
    html = b"<html><body><p>Decoherence is the central challenge.</p></body></html>"
    with respx.mock:
        respx.get("https://x/page").mock(
            return_value=httpx.Response(200, content=html,
                                        headers={"content-type": "text/html"}))
        r = CliRunner().invoke(app, ["research", "what is the challenge?",
                                     "--url", "https://x/page", "--offline"])
    assert r.exit_code == 0, r.stdout
    assert "staged draft" in r.stdout


def test_notify_event_is_best_effort(env):
    """_notify_event never raises even with no config / no channels."""
    from lighthouse_ai.cli import _notify_event
    _notify_event("draft_ready", "t", "b")  # must not raise
