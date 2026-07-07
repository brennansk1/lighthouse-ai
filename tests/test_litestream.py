"""Unit tests for the Litestream config renderer and lag reporter."""

from __future__ import annotations

import time

from lighthouse_ai.litestream import (
    install_hint,
    litestream_installed,
    render_litestream_config,
    replica_lags,
    write_litestream_config,
)


def test_render_includes_all_five_dbs(tmp_paths):
    yml = render_litestream_config(tmp_paths)
    for db in (
        tmp_paths.state_db,
        tmp_paths.audit_db,
        tmp_paths.intents_db,
        tmp_paths.positions_db,
        tmp_paths.hypotheses_db,
    ):
        assert str(db) in yml
    assert str(tmp_paths.replicas_dir) in yml


def test_audit_replica_uses_longer_retention(tmp_paths):
    yml = render_litestream_config(tmp_paths)
    audit_block = yml.split("audit-db", 1)[1].split("\n  - path:", 1)[0]
    assert "90d" in audit_block


def test_write_litestream_config_writes_file(tmp_paths):
    p = write_litestream_config(tmp_paths)
    assert p.exists()
    assert "state-db" in p.read_text()


def test_replica_lags_empty_when_no_replicas_dir(tmp_path):
    from lighthouse_ai.paths import make_paths

    paths = make_paths(tmp_path, tmp_path / "does_not_exist")
    assert replica_lags(paths) == []


def test_replica_lags_reports_freshness(tmp_paths):
    sub = tmp_paths.replicas_dir / "state-db"
    sub.mkdir(parents=True)
    (sub / "snap.bin").write_bytes(b"x")
    time.sleep(0.05)
    lags = replica_lags(tmp_paths)
    names = {lag.name for lag in lags}
    assert "state-db" in names
    state_lag = next(lag for lag in lags if lag.name == "state-db")
    assert state_lag.lag_seconds is not None
    assert state_lag.lag_seconds >= 0


def test_install_hint_mentions_both_oses():
    hint = install_hint()
    assert "brew" in hint
    assert "litestream.io" in hint


def test_litestream_installed_is_boolean():
    # We don't assert which value — test runs both with and without binary.
    assert isinstance(litestream_installed(), bool)
