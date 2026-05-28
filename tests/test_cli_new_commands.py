"""Tests for the Sprint 21 CLI additions (models, quarantine, audit, sandbox, secrets)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from lighthouse_ai.cli import app


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LIGHTHOUSE_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def initted_env(cli_env):
    """Cold-init a data dir so audit/quarantine/etc. have something to look at."""
    runner = CliRunner()
    r = runner.invoke(app, ["init", "--data-dir", str(cli_env), "--no-install-service"])
    assert r.exit_code == 0, r.stdout
    return cli_env


@pytest.fixture
def mock_ollama():
    """Stub the Ollama HTTP API for `models` commands."""
    with respx.mock(base_url="http://127.0.0.1:11434",
                    assert_all_called=False) as mock:
        yield mock


# --- secrets ---

def test_secrets_set_and_get(initted_env):
    runner = CliRunner()
    r1 = runner.invoke(app, ["secrets", "set", "test.key", "v1"])
    assert r1.exit_code == 0
    r2 = runner.invoke(app, ["secrets", "get", "test.key"])
    assert r2.exit_code == 0
    assert "v1" in r2.stdout


def test_secrets_rm_returns_zero_when_present(initted_env):
    runner = CliRunner()
    runner.invoke(app, ["secrets", "set", "test.key", "v1"])
    r = runner.invoke(app, ["secrets", "rm", "test.key"])
    assert r.exit_code == 0


def test_secrets_get_missing_exits_nonzero(initted_env):
    runner = CliRunner()
    r = runner.invoke(app, ["secrets", "get", "no-such-key"])
    assert r.exit_code != 0


# --- audit verify ---

def test_audit_verify_passes_on_empty_chain(initted_env):
    runner = CliRunner()
    r = runner.invoke(app, ["audit", "verify"])
    assert r.exit_code == 0


def test_audit_verify_passes_with_signed_events(initted_env):
    from lighthouse_ai.verification.audit_chain import append_event
    append_event(initted_env / "audit.db", actor="t", event_type="e",
                 payload={"k": 1}, data_dir=initted_env)
    runner = CliRunner()
    r = runner.invoke(app, ["audit", "verify"])
    assert r.exit_code == 0


def test_audit_verify_fails_on_broken_chain(initted_env):
    import json

    from lighthouse_ai.persistence import open_db
    from lighthouse_ai.verification.audit_chain import append_event
    append_event(initted_env / "audit.db", actor="t", event_type="e",
                 payload={"k": 1}, data_dir=initted_env)
    # Tamper.
    conn = open_db(initted_env / "audit.db")
    try:
        conn.execute("UPDATE audit_events SET payload_json = ? WHERE seq = 1",
                     (json.dumps({"k": 99}),))
    finally:
        conn.close()
    runner = CliRunner()
    r = runner.invoke(app, ["audit", "verify"])
    assert r.exit_code != 0


# --- sandbox redteam ---

def test_sandbox_redteam_passes(initted_env):
    runner = CliRunner()
    r = runner.invoke(app, ["sandbox", "redteam"])
    assert r.exit_code == 0, r.stdout
    assert "redteam ok" in r.stdout


# --- quarantine ---

def test_quarantine_list_empty(initted_env):
    runner = CliRunner()
    r = runner.invoke(app, ["quarantine", "list"])
    assert r.exit_code == 0
    assert "empty" in r.stdout.lower()


def test_quarantine_list_after_redteam(initted_env):
    runner = CliRunner()
    runner.invoke(app, ["sandbox", "redteam"])
    r = runner.invoke(app, ["quarantine", "list"])
    assert r.exit_code == 0
    # JS HTML + JS PDF are quarantined (not rejected) so they appear.
    assert "quarantine" in r.stdout.lower()


def test_quarantine_purge_requires_confirm(initted_env):
    runner = CliRunner()
    r = runner.invoke(app, ["quarantine", "purge"])
    assert r.exit_code != 0


def test_quarantine_purge_with_confirm(initted_env):
    runner = CliRunner()
    runner.invoke(app, ["sandbox", "redteam"])
    r = runner.invoke(app, ["quarantine", "purge", "--confirm"])
    assert r.exit_code == 0


# --- models (mocked HTTP) ---

def test_models_list_via_mocked_ollama(initted_env, mock_ollama):
    mock_ollama.get("/api/tags").respond(200, json={
        "models": [{"name": "qwen3:8b", "size": 5_500_000_000,
                    "digest": "sha256:abc", "modified_at": ""}]
    })
    runner = CliRunner()
    r = runner.invoke(app, ["models", "list"])
    assert r.exit_code == 0
    assert "qwen3:8b" in r.stdout


def test_models_list_handles_no_models(initted_env, mock_ollama):
    mock_ollama.get("/api/tags").respond(200, json={"models": []})
    runner = CliRunner()
    r = runner.invoke(app, ["models", "list"])
    assert r.exit_code == 0
    assert "no models" in r.stdout.lower()


def test_models_list_errors_when_ollama_down(initted_env, mock_ollama):
    mock_ollama.get("/api/tags").side_effect = httpx.ConnectError("nope")
    runner = CliRunner()
    r = runner.invoke(app, ["models", "list"])
    assert r.exit_code != 0


def _fake_disk(free_gb: float):
    """A shutil.disk_usage stand-in exposing .free in bytes."""
    from types import SimpleNamespace
    return lambda _p: SimpleNamespace(total=int(1000e9), used=0, free=int(free_gb * 1e9))


def test_models_pull_streams_status(initted_env, mock_ollama, monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", _fake_disk(200.0))  # plenty of disk
    mock_ollama.post("/api/pull").respond(200, text=(
        '{"status":"pulling manifest"}\n{"status":"success"}\n'
    ))
    runner = CliRunner()
    r = runner.invoke(app, ["models", "pull", "qwen3.5-9b", "--yes"])
    assert r.exit_code == 0, r.stdout
    assert "pulled qwen3.5-9b" in r.stdout


def test_models_pull_refuses_when_disk_low(initted_env, mock_ollama, monkeypatch):
    """The 35B-A3B pull (~17 GB) must be refused with only ~10 GB free —
    and must NOT hit the Ollama /api/pull endpoint at all."""
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", _fake_disk(10.0))
    pull_route = mock_ollama.post("/api/pull").respond(200, text='{"status":"success"}\n')
    runner = CliRunner()
    r = runner.invoke(app, ["models", "pull", "qwen3.6-35b-a3b"])
    assert r.exit_code == 1
    assert pull_route.call_count == 0  # never started the download (the key guard)


def test_models_pull_force_overrides_low_disk(initted_env, mock_ollama, monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", _fake_disk(10.0))
    mock_ollama.post("/api/pull").respond(200, text='{"status":"success"}\n')
    runner = CliRunner()
    r = runner.invoke(app, ["models", "pull", "qwen3.6-35b-a3b", "--force"])
    assert r.exit_code == 0, r.stdout
    assert "--force" in r.stdout


def test_models_pull_large_prompts_without_yes(initted_env, mock_ollama, monkeypatch):
    """A large pull asks for confirmation; declining aborts without download."""
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", _fake_disk(500.0))
    pull_route = mock_ollama.post("/api/pull").respond(200, text='{"status":"success"}\n')
    runner = CliRunner()
    r = runner.invoke(app, ["models", "pull", "deepseek-v4-flash"], input="n\n")
    assert r.exit_code == 0
    assert "aborted" in r.stdout
    assert pull_route.call_count == 0


def test_models_prune_succeeds_on_200(initted_env, mock_ollama):
    mock_ollama.delete("/api/delete").respond(200)
    runner = CliRunner()
    r = runner.invoke(app, ["models", "prune", "x"])
    assert r.exit_code == 0


# --- audit-egress (regression: column name + no false airplane-mode claim) ---

def test_audit_egress_runs_on_empty_log(initted_env):
    """A fresh log has no egress rows; the command must succeed (not crash on
    a bad column) and report the airplane-mode confirmation legitimately."""
    runner = CliRunner()
    r = runner.invoke(app, ["audit-egress"])
    assert r.exit_code == 0, r.stdout
    assert "No external network calls" in r.stdout


def test_audit_egress_surfaces_recorded_fetch(initted_env):
    """A recorded fetch event must actually appear — proving the query reads the
    real `ts` column instead of silently swallowing an OperationalError."""
    from lighthouse_ai.verification.audit_chain import append_event
    from lighthouse_ai.paths import paths_from_env
    paths = paths_from_env()
    append_event(paths.audit_db, actor="net", event_type="auto_fetch",
                 payload={"url": "https://arxiv.org/abs/1234"}, secret=b"k")
    runner = CliRunner()
    r = runner.invoke(app, ["audit-egress"])
    assert r.exit_code == 0, r.stdout
    assert "arxiv.org" in r.stdout
    # Must NOT falsely claim airplane-mode when a fetch is on record.
    assert "No external network calls" not in r.stdout


# --- skills (self-learning) ---

def test_skills_list_empty(initted_env):
    runner = CliRunner()
    r = runner.invoke(app, ["skills", "list"])
    assert r.exit_code == 0, r.stdout
    assert "No skills" in r.stdout


def test_skills_list_show_disable_prune(initted_env):
    from lighthouse_ai.learning import distill_skill
    from lighthouse_ai.paths import paths_from_env
    paths = paths_from_env()
    distill_skill(paths.state_db, question="A vs B on outcome X?",
                  question_type="comparative",
                  sub_questions=["What does A show?", "What does B show?", "Compare?"],
                  coverage=0.9, wep_phrase="likely", source_count=10)
    runner = CliRunner()
    r = runner.invoke(app, ["skills", "list"])
    assert r.exit_code == 0, r.stdout
    assert "comparative" in r.stdout

    r = runner.invoke(app, ["skills", "show", "1"])
    assert r.exit_code == 0, r.stdout
    assert "Decomposition that worked" in r.stdout

    r = runner.invoke(app, ["skills", "disable", "1"])
    assert r.exit_code == 0 and "disabled" in r.stdout
    # Disabled skill drops out of the default (active-only) list.
    r = runner.invoke(app, ["skills", "list"])
    assert "comparative" not in r.stdout
    # ...but is visible with --all.
    r = runner.invoke(app, ["skills", "list", "--all"])
    assert "comparative" in r.stdout

    r = runner.invoke(app, ["skills", "prune"])
    assert r.exit_code == 0


def test_skills_show_missing_id_errors(initted_env):
    runner = CliRunner()
    r = runner.invoke(app, ["skills", "show", "999"])
    assert r.exit_code == 1
