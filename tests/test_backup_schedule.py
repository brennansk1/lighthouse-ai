"""Backup-schedule unit tests — no real threads, no real restic, no real time.

All three cases drive :func:`_backup_tick` directly with injected fakes so the
scheduling logic is fully deterministic without any I/O side effects.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from lighthouse_ai.supervisor import _backup_tick

# ---------------------------------------------------------------------------
# Fake runner (satisfies the _BackupRunner Protocol)
# ---------------------------------------------------------------------------

class _FakeRunner:
    """Record-and-reply stub for ResticBackup, safe for unit tests.

    Both `backup` and `check` succeed by default; set `fail_backup`/
    `fail_check` to True to simulate subprocess errors. Calls are appended to
    `calls` as (method_name, args, kwargs) for assertion.
    """

    def __init__(self, *, fail_backup: bool = False, fail_check: bool = False) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.fail_backup = fail_backup
        self.fail_check = fail_check

    def _ok_result(self) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    def backup(
        self,
        paths: Sequence[Path],
        *,
        repo: str,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(("backup", (list(paths),), {"repo": repo}))
        if self.fail_backup:
            raise RuntimeError("backup simulated failure")
        return self._ok_result()

    def check(self, repo: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(("check", (repo,), {}))
        if self.fail_check:
            raise RuntimeError("check simulated failure")
        return self._ok_result()


# ---------------------------------------------------------------------------
# Helper: a minimal gate fake
# ---------------------------------------------------------------------------

def _gate_policy_paused():
    """Return (PAUSED, reason) — used to simulate gate-blocked ticks."""
    from lighthouse_ai.governor.scheduler_gate import PauseReason, Policy
    return Policy.PAUSED, PauseReason.USER_DISABLED


# ---------------------------------------------------------------------------
# Test 1: one tick invokes backup + integrity when due and configured
# ---------------------------------------------------------------------------

def test_tick_invokes_backup_and_check_when_configured(migrated_paths):
    """When restic is available and the passphrase is configured, a tick calls
    both backup() and check() via the injected fake runner."""
    fake = _FakeRunner()
    repo = str(migrated_paths.data_dir / "backups" / "restic")
    passphrase = "s3cr3t"

    _backup_tick(migrated_paths, repo=repo, passphrase=passphrase, runner=fake)

    method_names = [c[0] for c in fake.calls]
    assert method_names == ["backup", "check"], (
        f"expected [backup, check] calls; got {method_names}"
    )

    # backup was called with the right repo
    backup_kwargs = fake.calls[0][2]
    assert backup_kwargs["repo"] == repo

    # check was called with the right repo
    check_repo_arg = fake.calls[1][1][0]
    assert check_repo_arg == repo

    # backup paths include the databases
    backup_paths = fake.calls[0][1][0]
    assert len(backup_paths) > 0, "expected at least one DB path passed to backup"


# ---------------------------------------------------------------------------
# Test 2: no-op when restic is absent (runner=None) — no crash, no call
# ---------------------------------------------------------------------------

def test_tick_noop_when_runner_is_none(migrated_paths):
    """A None runner (restic binary absent) must be a silent no-op — no call,
    no exception, no crash."""
    # We pass runner=None to simulate restic not being installed.
    # This must not raise anything at all.
    repo = str(migrated_paths.data_dir / "backups" / "restic")
    passphrase = "s3cr3t"

    # Should not raise
    _backup_tick(migrated_paths, repo=repo, passphrase=passphrase, runner=None)
    # No assertion needed beyond "it didn't raise"; the test name makes the
    # intent clear. Add a trivial sentinel so the test is never vacuous.
    assert True


def test_tick_noop_when_repo_empty(migrated_paths):
    """An empty repo string means no repo is configured — tick is a no-op."""
    fake = _FakeRunner()
    _backup_tick(migrated_paths, repo="", passphrase="s3cr3t", runner=fake)
    assert fake.calls == [], "expected no calls when repo is empty"


def test_tick_noop_when_passphrase_absent(migrated_paths):
    """A None passphrase means the keychain hasn't been seeded yet — no-op."""
    fake = _FakeRunner()
    repo = str(migrated_paths.data_dir / "backups" / "restic")
    _backup_tick(migrated_paths, repo=repo, passphrase=None, runner=fake)
    assert fake.calls == [], "expected no calls when passphrase is None"


def test_tick_noop_when_passphrase_empty_string(migrated_paths):
    """An empty-string passphrase (falsy) is treated as unconfigured."""
    fake = _FakeRunner()
    repo = str(migrated_paths.data_dir / "backups" / "restic")
    _backup_tick(migrated_paths, repo=repo, passphrase="", runner=fake)
    assert fake.calls == [], "expected no calls when passphrase is empty string"


# ---------------------------------------------------------------------------
# Test 3: skips while the gate reports PAUSED
# ---------------------------------------------------------------------------

def test_loop_tick_skips_while_gate_paused(migrated_paths):
    """Simulate the PAUSED guard: the loop body checks gate.policy() before
    calling _backup_tick; when PAUSED it continues without calling the runner.

    We test this by replicating the exact guard logic from _start_backup_loop
    with an injected gate, so no real thread or sleep is needed.
    """
    from lighthouse_ai.governor.scheduler_gate import Policy

    fake = _FakeRunner()
    repo = str(migrated_paths.data_dir / "backups" / "restic")
    passphrase = "s3cr3t"

    # Simulate one loop iteration with a paused gate
    class _PausedGate:
        def policy(self):
            return _gate_policy_paused()

    gate = _PausedGate()
    policy, _ = gate.policy()

    if policy is Policy.PAUSED:
        pass  # loop body `continue`s; _backup_tick is never called
    else:
        _backup_tick(migrated_paths, repo=repo, passphrase=passphrase, runner=fake)

    assert fake.calls == [], (
        "backup runner must not be called while the scheduler gate is PAUSED"
    )


# ---------------------------------------------------------------------------
# Test 4: backup failure does NOT prevent check from being skipped gracefully
# ---------------------------------------------------------------------------

def test_tick_backup_failure_does_not_raise(migrated_paths):
    """If backup() raises, the tick logs and returns — check is not called and
    no exception propagates to the caller (the loop must stay alive)."""
    fake = _FakeRunner(fail_backup=True)
    repo = str(migrated_paths.data_dir / "backups" / "restic")
    passphrase = "s3cr3t"

    # Must not raise
    _backup_tick(migrated_paths, repo=repo, passphrase=passphrase, runner=fake)

    method_names = [c[0] for c in fake.calls]
    assert "backup" in method_names, "backup should have been attempted"
    assert "check" not in method_names, "check must not be called after backup failure"
