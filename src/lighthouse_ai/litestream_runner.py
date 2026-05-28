"""Process manager for the long-running ``litestream replicate`` daemon.

Litestream replication is a persistent foreground process (§26.2): it must be
started alongside the supervisor and stopped on shutdown. This module owns its
lifecycle (start / stop / is_running) without coupling to a particular process
supervisor.

Why the spawner is injectable: starting a real subprocess in a unit test is
both slow and unsafe (it would attach to live databases). The default spawner
calls :func:`subprocess.Popen`, but tests inject a fake that returns a
controllable handle, so we exercise the state machine without any real I/O.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

from .paths import Paths
from .recovery import litestream_replicate_command


def litestream_installed() -> bool:
    """Probe whether the ``litestream`` binary is resolvable on ``PATH``."""
    return shutil.which("litestream") is not None


class Process(Protocol):
    """Minimal subset of :class:`subprocess.Popen` we depend on.

    Declared as a Protocol so test fakes need only implement these members
    rather than subclassing Popen.
    """

    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = ...) -> int: ...

    def kill(self) -> None: ...


# A spawner turns an argv into a running Process handle.
Spawner = Callable[[Sequence[str]], Process]


class LitestreamNotInstalled(RuntimeError):
    """Raised when asked to start replication without the binary present."""


def _default_spawner(argv: Sequence[str]) -> Process:
    """Spawn the real ``litestream replicate`` process.

    Isolated so tests can replace it; only production reaches this code.
    """
    return subprocess.Popen(list(argv))  # type: ignore[return-value]


@dataclass
class LitestreamRunner:
    """Start/stop manager for a single ``litestream replicate`` process.

    Not frozen because it owns mutable lifecycle state (the live process
    handle); the surrounding policy values are still set once at construction.
    """

    paths: Paths
    spawner: Spawner = field(default=_default_spawner)
    stop_timeout: float = 5.0
    _proc: Process | None = field(default=None, init=False, repr=False)

    def argv(self) -> list[str]:
        """The exact command this runner will spawn."""
        return litestream_replicate_command(self.paths)

    def is_running(self) -> bool:
        """True iff a process has been started and has not yet exited."""
        if self._proc is None:
            return False
        return self._proc.poll() is None

    def start(self) -> Process:
        """Start replication, returning the process handle.

        Idempotent-ish: starting while already running returns the existing
        handle rather than spawning a duplicate replicator (two replicators on
        the same db would fight over the WAL).
        """
        if self.is_running():
            assert self._proc is not None
            return self._proc
        if not litestream_installed():
            raise LitestreamNotInstalled(
                "litestream binary not found on PATH; cannot start replication."
            )
        self._proc = self.spawner(self.argv())
        return self._proc

    def stop(self) -> None:
        """Stop replication: ask politely, then force-kill on timeout.

        We escalate to ``kill`` so a wedged replicator cannot block shutdown,
        matching the supervisor's expectation of a bounded stop.
        """
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=self.stop_timeout)
            except Exception:
                self._proc.kill()
                try:
                    self._proc.wait(timeout=self.stop_timeout)
                except Exception:
                    pass
        self._proc = None
