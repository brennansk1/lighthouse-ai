"""Unit tests for the §26 durability/disaster-recovery helpers.

All subprocess work is faked: no real ``restic`` or ``litestream`` is ever
spawned, and no model is loaded. SQLite tests use real on-disk dbs under the
``tmp_paths`` fixture so ``PRAGMA integrity_check`` exercises actual files.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from lighthouse_ai import backup, litestream_runner
from lighthouse_ai.backup import ResticBackup, ResticUnavailable
from lighthouse_ai.litestream_runner import LitestreamNotInstalled, LitestreamRunner
from lighthouse_ai.persistence import open_db
from lighthouse_ai.recovery import (
    MAX_REPLICA_LAG_SECONDS,
    IntegrityReport,
    integrity_report,
    litestream_replicate_command,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeRunner:
    """Records argv (+ env, when injected) and returns a canned result."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.calls: list[list[str]] = []
        self.envs: list[dict | None] = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, argv, env=None):  # type: ignore[no-untyped-def]
        self.calls.append(list(argv))
        self.envs.append(env)
        return subprocess.CompletedProcess(
            list(argv), self.returncode, self.stdout, self.stderr)


class FakeProcess:
    """Controllable stand-in for subprocess.Popen."""

    def __init__(self) -> None:
        self.pid = 4242
        self._returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self):  # type: ignore[no-untyped-def]
        return self._returncode

    def terminate(self) -> None:
        self.terminated = True
        self._returncode = -15

    def kill(self) -> None:
        self.killed = True
        self._returncode = -9

    def wait(self, timeout=None):  # type: ignore[no-untyped-def]
        return self._returncode if self._returncode is not None else 0


def _seed_db(path: Path) -> None:
    conn = open_db(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.close()


def _seed_all(paths) -> None:  # type: ignore[no-untyped-def]
    for p in paths.all_dbs():
        _seed_db(p)


# ---------------------------------------------------------------------------
# backup.py
# ---------------------------------------------------------------------------


def test_restic_installed_returns_bool():
    assert isinstance(backup.restic_installed(), bool)


def test_init_argv_shape():
    rb = ResticBackup(runner=FakeRunner())
    assert rb.init_argv("/repo") == ["restic", "--repo", "/repo", "init"]


def test_backup_argv_includes_all_paths():
    rb = ResticBackup(runner=FakeRunner())
    argv = rb.backup_argv("/repo", ["/a", Path("/b")])
    assert argv == ["restic", "--repo", "/repo", "backup", "/a", "/b"]


def test_backup_argv_rejects_empty_paths():
    rb = ResticBackup(runner=FakeRunner())
    with pytest.raises(ValueError):
        rb.backup_argv("/repo", [])


def test_check_argv_shape():
    rb = ResticBackup(runner=FakeRunner())
    assert rb.check_argv("/repo") == ["restic", "--repo", "/repo", "check"]


def test_snapshots_argv_is_json():
    rb = ResticBackup(runner=FakeRunner())
    assert rb.snapshots_argv("/repo") == ["restic", "--repo", "/repo", "snapshots", "--json"]


def test_passphrase_never_appears_in_argv():
    rb = ResticBackup(runner=FakeRunner())
    for argv in (rb.init_argv("/r"), rb.backup_argv("/r", ["/x"]),
                 rb.check_argv("/r"), rb.snapshots_argv("/r")):
        assert "hunter2" not in " ".join(argv)


def test_init_invokes_runner_when_installed(monkeypatch):
    fake = FakeRunner(stdout="created")
    rb = ResticBackup(runner=fake)
    monkeypatch.setattr(backup, "restic_installed", lambda: True)
    res = rb.init("/repo", "hunter2")
    assert res.returncode == 0
    assert fake.calls == [["restic", "--repo", "/repo", "init"]]


def test_backup_invokes_runner_when_installed(monkeypatch):
    fake = FakeRunner()
    rb = ResticBackup(runner=fake)
    monkeypatch.setattr(backup, "restic_installed", lambda: True)
    rb.backup(["/data/state.db"], repo="/repo")
    assert fake.calls[0] == ["restic", "--repo", "/repo", "backup", "/data/state.db"]


def test_check_invokes_runner_when_installed(monkeypatch):
    fake = FakeRunner()
    rb = ResticBackup(runner=fake)
    monkeypatch.setattr(backup, "restic_installed", lambda: True)
    rb.check("/repo")
    assert fake.calls[0] == ["restic", "--repo", "/repo", "check"]


def test_snapshots_invokes_runner_when_installed(monkeypatch):
    fake = FakeRunner(stdout="[]")
    rb = ResticBackup(runner=fake)
    monkeypatch.setattr(backup, "restic_installed", lambda: True)
    res = rb.snapshots("/repo")
    assert res.stdout == "[]"


def test_passphrase_reaches_restic_via_env(monkeypatch):
    """Regression (live, 2026-06-10): the passphrase never reached restic —
    no RESTIC_PASSWORD in the child env, so real backups prompted/failed."""
    fake = FakeRunner()
    monkeypatch.setattr(backup, "restic_installed", lambda: True)

    rb = ResticBackup(runner=fake, passphrase="hunter2")
    rb.backup(["/x"], repo="/repo")
    assert fake.envs[0] is not None and fake.envs[0]["RESTIC_PASSWORD"] == "hunter2"

    # init's per-call passphrase wins and is injected too
    rb2 = ResticBackup(runner=fake)
    rb2.init("/repo", "callpw")
    assert fake.envs[-1] is not None and fake.envs[-1]["RESTIC_PASSWORD"] == "callpw"

    # ...and the secret still never appears on the argv
    assert all("hunter2" not in " ".join(c) and "callpw" not in " ".join(c)
               for c in fake.calls)


def test_no_passphrase_calls_runner_without_env(monkeypatch):
    fake = FakeRunner()
    monkeypatch.setattr(backup, "restic_installed", lambda: True)
    ResticBackup(runner=fake).check("/repo")
    assert fake.envs == [None]


def test_nonzero_exit_raises_restic_error(monkeypatch):
    """Regression (live, 2026-06-10): rc was never checked — failed backups
    logged backup_ok / printed 'backed up'. Non-zero must raise, with stderr."""
    fake = FakeRunner(returncode=1, stderr="Fatal: wrong password")
    monkeypatch.setattr(backup, "restic_installed", lambda: True)
    rb = ResticBackup(runner=fake, passphrase="pw")
    with pytest.raises(backup.ResticError, match="wrong password"):
        rb.backup(["/x"], repo="/repo")


def test_methods_raise_when_restic_absent(monkeypatch):
    rb = ResticBackup(runner=FakeRunner())
    monkeypatch.setattr(backup, "restic_installed", lambda: False)
    with pytest.raises(ResticUnavailable):
        rb.init("/repo", "pw")
    with pytest.raises(ResticUnavailable):
        rb.backup(["/x"], repo="/repo")
    with pytest.raises(ResticUnavailable):
        rb.check("/repo")
    with pytest.raises(ResticUnavailable):
        rb.snapshots("/repo")


def test_install_hint_mentions_restic():
    assert "restic" in backup.install_hint()


# ---------------------------------------------------------------------------
# recovery.py
# ---------------------------------------------------------------------------


def test_integrity_report_all_ok(tmp_paths):
    _seed_all(tmp_paths)
    report = integrity_report(tmp_paths)
    assert isinstance(report, IntegrityReport)
    assert len(report.databases) == 5
    assert report.dbs_ok
    assert all(d.ok and d.result == "ok" for d in report.databases)


def test_integrity_report_missing_db_is_not_ok(tmp_paths):
    # Seed only some dbs; the rest are missing.
    _seed_db(tmp_paths.state_db)
    report = integrity_report(tmp_paths)
    by_kind = {d.kind: d for d in report.databases}
    assert by_kind["state"].ok
    assert not by_kind["audit"].ok
    assert by_kind["audit"].result == "missing"
    assert not report.dbs_ok
    assert not report.overall_ok


def test_integrity_report_no_replicas_is_vacuously_ok(tmp_paths):
    _seed_all(tmp_paths)
    report = integrity_report(tmp_paths)
    assert report.replicas == ()
    assert report.replicas_ok
    assert report.overall_ok


def test_integrity_report_fresh_replica_ok(tmp_paths):
    _seed_all(tmp_paths)
    sub = tmp_paths.replicas_dir / "state-db"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "snap").write_text("x")
    report = integrity_report(tmp_paths)
    assert len(report.replicas) == 1
    assert report.replicas[0].ok
    assert report.replicas_ok
    assert report.overall_ok


def test_integrity_report_stale_replica_not_ok(tmp_paths):
    _seed_all(tmp_paths)
    sub = tmp_paths.replicas_dir / "audit-db"
    sub.mkdir(parents=True, exist_ok=True)
    f = sub / "snap"
    f.write_text("x")
    old = time.time() - (MAX_REPLICA_LAG_SECONDS + 120)
    import os
    os.utime(f, (old, old))
    report = integrity_report(tmp_paths)
    assert not report.replicas[0].ok
    assert not report.replicas_ok
    assert not report.overall_ok


def test_replica_with_no_data_is_not_ok(tmp_paths):
    _seed_all(tmp_paths)
    (tmp_paths.replicas_dir / "empty-db").mkdir(parents=True, exist_ok=True)
    report = integrity_report(tmp_paths)
    assert report.replicas[0].lag_seconds is None
    assert not report.replicas[0].ok


def test_integrity_report_is_frozen(tmp_paths):
    _seed_all(tmp_paths)
    report = integrity_report(tmp_paths)
    with pytest.raises(Exception):
        report.databases = ()  # type: ignore[misc]


def test_litestream_replicate_command(tmp_paths):
    argv = litestream_replicate_command(tmp_paths)
    assert argv[:3] == ["litestream", "replicate", "-config"]
    assert argv[3] == str(tmp_paths.litestream_config)


# ---------------------------------------------------------------------------
# litestream_runner.py
# ---------------------------------------------------------------------------


def test_litestream_installed_returns_bool():
    assert isinstance(litestream_runner.litestream_installed(), bool)


def test_runner_argv_matches_recovery_command(tmp_paths):
    runner = LitestreamRunner(tmp_paths, spawner=lambda argv: FakeProcess())
    assert runner.argv() == litestream_replicate_command(tmp_paths)


def test_runner_not_running_before_start(tmp_paths):
    runner = LitestreamRunner(tmp_paths, spawner=lambda argv: FakeProcess())
    assert not runner.is_running()


def test_runner_start_spawns_and_runs(tmp_paths, monkeypatch):
    monkeypatch.setattr(litestream_runner, "litestream_installed", lambda: True)
    spawned: list[FakeProcess] = []

    def spawn(argv):  # type: ignore[no-untyped-def]
        p = FakeProcess()
        spawned.append(p)
        return p

    runner = LitestreamRunner(tmp_paths, spawner=spawn)
    proc = runner.start()
    assert runner.is_running()
    assert proc is spawned[0]


def test_runner_start_is_idempotent(tmp_paths, monkeypatch):
    monkeypatch.setattr(litestream_runner, "litestream_installed", lambda: True)
    calls: list[int] = []

    def spawn(argv):  # type: ignore[no-untyped-def]
        calls.append(1)
        return FakeProcess()

    runner = LitestreamRunner(tmp_paths, spawner=spawn)
    first = runner.start()
    second = runner.start()
    assert first is second
    assert len(calls) == 1


def test_runner_start_raises_when_not_installed(tmp_paths, monkeypatch):
    monkeypatch.setattr(litestream_runner, "litestream_installed", lambda: False)
    runner = LitestreamRunner(tmp_paths, spawner=lambda argv: FakeProcess())
    with pytest.raises(LitestreamNotInstalled):
        runner.start()


def test_runner_stop_terminates(tmp_paths, monkeypatch):
    monkeypatch.setattr(litestream_runner, "litestream_installed", lambda: True)
    proc = FakeProcess()
    runner = LitestreamRunner(tmp_paths, spawner=lambda argv: proc)
    runner.start()
    runner.stop()
    assert proc.terminated
    assert not runner.is_running()


def test_runner_stop_is_safe_before_start(tmp_paths):
    runner = LitestreamRunner(tmp_paths, spawner=lambda argv: FakeProcess())
    runner.stop()  # must not raise
    assert not runner.is_running()


def test_runner_force_kills_on_timeout(tmp_paths, monkeypatch):
    monkeypatch.setattr(litestream_runner, "litestream_installed", lambda: True)

    class Stubborn(FakeProcess):
        def terminate(self) -> None:
            self.terminated = True  # refuses to die

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            if not self.killed:
                raise subprocess.TimeoutExpired(cmd="litestream", timeout=timeout or 0)
            return -9

    proc = Stubborn()
    runner = LitestreamRunner(tmp_paths, spawner=lambda argv: proc, stop_timeout=0.01)
    runner.start()
    runner.stop()
    assert proc.killed


def test_runner_is_not_frozen_allows_state(tmp_paths, monkeypatch):
    monkeypatch.setattr(litestream_runner, "litestream_installed", lambda: True)
    runner = LitestreamRunner(tmp_paths, spawner=lambda argv: FakeProcess())
    runner.start()
    assert runner.is_running()
    runner.stop()
    # Can start again after stop.
    runner.start()
    assert runner.is_running()
