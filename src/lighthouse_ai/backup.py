"""restic backup wrapper for the §26.3 backup matrix.

``restic`` is an out-of-band binary (like Litestream): the operator installs
it separately and we shell out to it. We never embed credentials here — the
repo passphrase is passed explicitly by the caller (sourced from the OS
keychain in production per §26.3).

Why an injectable ``runner``: backups touch a real on-disk repository and the
network, neither of which is appropriate in a unit test. By defaulting the
runner to :func:`subprocess.run` but allowing it to be overridden, tests can
assert on the exact argv we build without spawning ``restic`` at all.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# A runner takes the argv list and returns something with .returncode/.stdout.
# subprocess.run matches this shape; tests pass a fake recording callable.
Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


class ResticUnavailable(RuntimeError):
    """Raised when the ``restic`` binary cannot be found on ``PATH``.

    We fail loudly rather than silently skipping backups: a missing backup
    tool is an operational emergency for a system whose audit/intent records
    are explicitly "not regenerable" (§26.3), so callers must handle it.
    """


def restic_installed() -> bool:
    """Probe whether the ``restic`` binary is resolvable on ``PATH``."""
    return shutil.which("restic") is not None


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run ``restic`` for real, capturing output as text.

    Kept tiny and side-effecting so tests can replace it wholesale; production
    code paths are the only ones that ever reach it.
    """
    return subprocess.run(list(argv), capture_output=True, text=True, check=False)


@dataclass(frozen=True)
class ResticBackup:
    """Thin, testable wrapper around the ``restic`` CLI.

    Subprocess execution is funneled through ``runner`` so tests can assert on
    the argv we build without spawning ``restic``. The repo and passphrase are
    accepted per-call (matching the §26.3 operational model where the repo path
    and Keychain-sourced passphrase are supplied at invocation time).
    """

    runner: Runner = field(default=_default_runner)

    @staticmethod
    def _base_argv(repo: str) -> list[str]:
        """Common ``restic`` prefix carrying the repo selector.

        The passphrase is never placed on the argv — restic reads it from the
        ``RESTIC_PASSWORD`` environment variable in production. Keeping secrets
        out of the argv means tests can assert on commands safely and the
        passphrase never leaks into process listings.
        """
        return ["restic", "--repo", repo]

    def _run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if not restic_installed():
            raise ResticUnavailable(
                "restic binary not found on PATH; install restic to enable "
                "the §26.3 backup matrix (e.g. `brew install restic`)."
            )
        return self.runner(list(argv))

    def init_argv(self, repo: str) -> list[str]:
        """Build the argv to initialize a fresh repository."""
        return [*self._base_argv(repo), "init"]

    def backup_argv(self, repo: str, paths: Sequence[str | Path]) -> list[str]:
        """Build the argv to back up ``paths`` into ``repo``."""
        if not paths:
            raise ValueError("backup requires at least one path")
        return [*self._base_argv(repo), "backup", *[str(p) for p in paths]]

    def check_argv(self, repo: str) -> list[str]:
        """Build the argv to verify repository integrity (§26.5)."""
        return [*self._base_argv(repo), "check"]

    def snapshots_argv(self, repo: str) -> list[str]:
        """Build the argv to list snapshots as JSON."""
        return [*self._base_argv(repo), "snapshots", "--json"]

    def init(self, repo: str, passphrase: str) -> subprocess.CompletedProcess[str]:
        """Initialize the restic repository.

        ``passphrase`` is accepted to mirror the operational contract; it is
        passed to restic via the environment by the real runner, never argv.
        """
        return self._run(self.init_argv(repo))

    def backup(self, paths: Sequence[str | Path], *, repo: str
               ) -> subprocess.CompletedProcess[str]:
        """Back up the given filesystem paths into ``repo``."""
        return self._run(self.backup_argv(repo, paths))

    def check(self, repo: str) -> subprocess.CompletedProcess[str]:
        """Run ``restic check`` to validate stored data integrity."""
        return self._run(self.check_argv(repo))

    def snapshots(self, repo: str) -> subprocess.CompletedProcess[str]:
        """List repository snapshots (JSON)."""
        return self._run(self.snapshots_argv(repo))


def install_hint() -> str:
    """Operator-facing instructions for installing restic."""
    return (
        "Install restic:\n"
        "  macOS:  brew install restic\n"
        "  Linux:  https://restic.readthedocs.io/en/stable/020_installation.html\n"
        "Then init a repo: restic --repo /var/lighthouse/backups/restic init"
    )
