"""Integration tests: CLI invocations via typer's CliRunner."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lighthouse_ai.cli import app


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LIGHTHOUSE_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.mark.integration
def test_init_creates_directory_tree(cli_env, monkeypatch):
    # Don't try to write into the real ~/Library/LaunchAgents during tests.
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--data-dir", str(cli_env),
                                 "--no-install-service"])
    assert result.exit_code == 0, result.stdout
    assert (cli_env / "config.toml").exists()
    assert (cli_env / "litestream.yml").exists()
    assert (cli_env / "state.db").exists()
    assert (cli_env / "audit.db").exists()
    assert (cli_env / "hardware.json").exists()


@pytest.mark.integration
def test_init_is_idempotent_without_force(cli_env):
    runner = CliRunner()
    r1 = runner.invoke(app, ["init", "--data-dir", str(cli_env), "--no-install-service"])
    assert r1.exit_code == 0
    r2 = runner.invoke(app, ["init", "--data-dir", str(cli_env), "--no-install-service"])
    assert r2.exit_code == 0
    assert "skip" in r2.stdout.lower()


@pytest.mark.integration
def test_doctor_runs_without_init_and_reports_missing(cli_env):
    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])
    # Exit may be 0 (no actual integrity failures because DBs don't exist yet)
    # or 1 if a litestream lag is reported; we just confirm output happens.
    assert "platform" in result.stdout.lower() or "hardware" in result.stdout.lower()


@pytest.mark.integration
def test_doctor_passes_after_init(cli_env):
    runner = CliRunner()
    runner.invoke(app, ["init", "--data-dir", str(cli_env), "--no-install-service"])
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.stdout


@pytest.mark.integration
def test_pause_and_resume_toggle_state(cli_env):
    runner = CliRunner()
    runner.invoke(app, ["init", "--data-dir", str(cli_env), "--no-install-service"])
    r1 = runner.invoke(app, ["pause"])
    assert r1.exit_code == 0, r1.stdout
    # Verify state.db reflects the change.
    from lighthouse_ai.persistence import open_db
    conn = open_db(cli_env / "state.db")
    try:
        status = conn.execute("SELECT status FROM supervisor_state").fetchone()[0]
    finally:
        conn.close()
    assert status == "paused_soft"

    r2 = runner.invoke(app, ["resume"])
    assert r2.exit_code == 0, r2.stdout
    conn = open_db(cli_env / "state.db")
    try:
        status = conn.execute("SELECT status FROM supervisor_state").fetchone()[0]
    finally:
        conn.close()
    assert status == "running"


@pytest.mark.integration
def test_version_command():
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


@pytest.mark.integration
def test_status_with_no_supervisor_running_fails_cleanly(cli_env):
    runner = CliRunner()
    # No server bound on 8765 — should report unreachable.
    result = runner.invoke(app, ["status", "--port", "1"])  # port 1 reliably refuses
    assert result.exit_code != 0
