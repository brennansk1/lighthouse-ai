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


# --- audit egress ---

def test_audit_egress_empty_reports_clean(initted_env):
    """With no fetch/egress events the report is the airplane-mode all-clear."""
    runner = CliRunner()
    r = runner.invoke(app, ["audit-egress"])
    assert r.exit_code == 0, r.stdout
    assert "No external network calls" in r.stdout


def test_audit_egress_surfaces_recorded_fetches(initted_env):
    """A recorded auto_fetch event MUST appear in the egress report.

    Regression: the query referenced a non-existent ``created_at`` column on
    ``audit_events`` (the real column is ``ts``); the resulting
    OperationalError was swallowed, so the command always printed the
    'no external network calls' all-clear even when egress had happened —
    a false negative for a security-relevant audit.
    """
    from lighthouse_ai.verification.audit_chain import append_event

    append_event(
        initted_env / "audit.db",
        actor="ingest",
        event_type="auto_fetch",
        payload={"url": "https://example.com/feed.xml"},
        data_dir=initted_env,
    )
    runner = CliRunner()
    r = runner.invoke(app, ["audit-egress"])
    assert r.exit_code == 0, r.stdout
    assert "No external network calls" not in r.stdout
    assert "auto_fetch" in r.stdout
    assert "example.com" in r.stdout


def test_audit_egress_summary_is_plain_english(initted_env):
    """--summary gives a one-paragraph verdict naming hosts, not a table."""
    from lighthouse_ai.verification.audit_chain import append_event

    for url in ("https://example.com/feed.xml",
                "https://example.com/page2",
                "https://api.crossref.org/works/x"):
        append_event(
            initted_env / "audit.db",
            actor="ingest",
            event_type="auto_fetch",
            payload={"url": url},
            data_dir=initted_env,
        )
    runner = CliRunner()
    r = runner.invoke(app, ["audit-egress", "--summary"])
    assert r.exit_code == 0, r.stdout
    # Collapse rich's console wrapping before asserting on phrases.
    flat = " ".join(r.stdout.split())
    assert "external network call" in flat
    assert "example.com (2)" in flat
    assert "api.crossref.org (1)" in flat
    # The verdict replaces the table — no per-event rows.
    assert "Egress audit" not in flat


def test_audit_egress_summary_empty_still_all_clear(initted_env):
    """--summary on a clean log keeps the airplane-mode all-clear message."""
    runner = CliRunner()
    r = runner.invoke(app, ["audit-egress", "--summary"])
    assert r.exit_code == 0, r.stdout
    assert "No external network calls" in r.stdout


# --- doctor: privacy & secrets section ----------------------------------

def test_doctor_reports_airgap_on(initted_env, monkeypatch):
    """With the kill switch set, doctor states plainly that egress is refused."""
    monkeypatch.setenv("LIGHTHOUSE_AIRGAP", "1")
    r = CliRunner().invoke(app, ["doctor", "check"])
    assert "airgap kill switch is ON" in r.stdout


def test_doctor_reports_airgap_off_with_howto(initted_env, monkeypatch):
    monkeypatch.delenv("LIGHTHOUSE_AIRGAP", raising=False)
    r = CliRunner().invoke(app, ["doctor", "check"])
    assert "airgap off" in r.stdout
    assert "LIGHTHOUSE_AIRGAP=1" in r.stdout


def test_doctor_reports_secrets_backend(initted_env):
    """Doctor names the effective secret storage (keychain or file fallback)."""
    r = CliRunner().invoke(app, ["doctor", "check"])
    assert "secrets:" in r.stdout


def test_doctor_flags_loose_secrets_file_permissions(initted_env):
    """A secrets.toml readable by other users is a hard issue (exit 1)."""
    import os

    fb = initted_env / "secrets.toml"
    fb.write_text('[secrets]\nk = "v"\n')
    os.chmod(fb, 0o644)
    r = CliRunner().invoke(app, ["doctor", "check"])
    assert r.exit_code == 1, r.stdout
    assert "permissions" in r.stdout


# --- init: zero-friction first run -------------------------------------

def _fake_profile(total_ram_gb: float, tier: str):
    """A HardwareProfile stand-in so init is deterministic + offline."""
    from lighthouse_ai.hardware import HardwareProfile
    return HardwareProfile(
        platform="darwin", arch="arm64", apple_silicon=True,
        total_ram_gb=total_ram_gb, free_ram_gb=total_ram_gb / 2,
        cpu_cores_physical=8, cpu_cores_logical=8,
        available_backends=["mlx", "ollama"], suggested_tier=tier,
    )


def test_init_writes_no_docker_default_config(cli_env, monkeypatch):
    """Cold init must produce a usable config with the in-memory vector store —
    no Docker/Qdrant required. Offline: probe() is mocked."""
    import lighthouse_ai.cli as cli
    monkeypatch.setattr(cli, "probe", lambda: _fake_profile(16.0, "T1"))

    runner = CliRunner()
    r = runner.invoke(app, ["init", "--data-dir", str(cli_env),
                            "--no-install-service"])
    assert r.exit_code == 0, r.stdout

    cfg_text = (cli_env / "config.toml").read_text()
    # The default vector store is the in-memory/SQLite spine, not Qdrant. Check
    # the actual active assignment (ignore the explanatory comment lines).
    active = [ln for ln in cfg_text.splitlines()
              if ln.strip().startswith("vector_store")]
    assert active == ['vector_store = "memory"'], active
    # Qdrant is explicitly optional in the generated config.
    assert "OPTIONAL" in cfg_text or "optional" in cfg_text

    # ...and the printed next-steps say so plainly.
    assert "No Docker needed to start" in r.stdout


def test_init_prints_ram_appropriate_model_recommendation(cli_env, monkeypatch):
    """init must auto-select a RAM-appropriate model via recommend_models and
    print the single `ollama pull <tag>` the user still needs — not a hardcoded
    qwen3:14b on a smaller box."""
    import lighthouse_ai.cli as cli
    # 16 GB box → T1; the budget-aware tag ladder lands below 14b.
    monkeypatch.setattr(cli, "probe", lambda: _fake_profile(16.0, "T1"))

    runner = CliRunner()
    r = runner.invoke(app, ["init", "--data-dir", str(cli_env),
                            "--no-install-service"])
    assert r.exit_code == 0, r.stdout

    # A model recommendation + the single pull command are printed.
    assert "recommended model" in r.stdout
    assert "ollama pull" in r.stdout
    # RAM-appropriate, not the hardcoded 14b ceiling for a 16 GB box.
    assert "qwen3:14b" not in r.stdout


def test_init_pull_tag_scales_with_ram(cli_env, monkeypatch):
    """The printed pull tag tracks the detected RAM: a bigger box gets a bigger
    tag than a smaller one (proves it isn't hardcoded)."""
    import lighthouse_ai.cli as cli

    def _run(ram, tier):
        monkeypatch.setattr(cli, "probe", lambda: _fake_profile(ram, tier))
        out = CliRunner().invoke(
            app, ["init", "--data-dir", str(cli_env),
                  "--no-install-service", "--force"])
        assert out.exit_code == 0, out.stdout
        return out.stdout

    small = _run(16.0, "T1")
    large = _run(64.0, "T4")
    # 16 GB → an 8b-class tag; 64 GB → a 32b-class tag. Different picks.
    assert "qwen3:8b" in small
    assert "qwen3:32b" in large


def test_init_prints_three_step_card(cli_env, monkeypatch):
    """init ends with the three-step first-run card and the dashboard URL."""
    import lighthouse_ai.cli as cli
    monkeypatch.setattr(cli, "probe", lambda: _fake_profile(16.0, "T1"))

    runner = CliRunner()
    r = runner.invoke(app, ["init", "--data-dir", str(cli_env),
                            "--no-install-service"])
    assert r.exit_code == 0, r.stdout
    assert "three steps" in r.stdout
    assert "lighthouse start" in r.stdout
    assert "lighthouse research" in r.stdout
    assert "http://localhost:8765" in r.stdout
    assert "lighthouse doctor" in r.stdout


def test_init_honors_data_dir_env(cli_env, monkeypatch):
    """Without --data-dir, init must honor $LIGHTHOUSE_DATA_DIR like every
    other command (it used to silently write to ~/.lighthouse instead)."""
    import lighthouse_ai.cli as cli
    monkeypatch.setattr(cli, "probe", lambda: _fake_profile(16.0, "T1"))

    runner = CliRunner()
    r = runner.invoke(app, ["init", "--no-install-service"])
    assert r.exit_code == 0, r.stdout
    # cli_env IS the $LIGHTHOUSE_DATA_DIR set by the fixture.
    assert (cli_env / "config.toml").exists()


def test_init_model_recommendation_is_best_effort(cli_env, monkeypatch):
    """If model selection blows up, init still completes (never a hard fail)."""
    import lighthouse_ai.cli as cli
    monkeypatch.setattr(cli, "probe", lambda: _fake_profile(16.0, "T1"))

    import lighthouse_ai.gateway as gw
    monkeypatch.setattr(gw, "recommend_pull_tag",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    runner = CliRunner()
    r = runner.invoke(app, ["init", "--data-dir", str(cli_env),
                            "--no-install-service"])
    assert r.exit_code == 0, r.stdout
    assert "init complete" in r.stdout
    assert "model recommendation unavailable" in r.stdout
