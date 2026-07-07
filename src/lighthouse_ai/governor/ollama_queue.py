"""Cross-process, RAM-aware admission queue for real Ollama calls.

The per-process :class:`SchedulerGate` semaphore caps *in-process* concurrency,
but it cannot stop two separate ``lighthouse`` processes from each loading a
model and exhausting RAM. This module is that missing backstop, and it aims for
a balance the user asked for explicitly: **utilise the hardware, but never OOM.**

How it strikes that balance: instead of one global one-at-a-time slot (which
serialises even cheap calls against a model that is already resident), each call
reserves the RAM it will actually *add*. A call against an already-resident
model — or a fine-grained MoE that pages from SSD — adds nothing, so it is
admitted immediately with no locking at all (the hot path). A call that must
load fresh weights reserves its estimated resident size in a small shared
*ledger*; it is admitted only when ``sum(reservations) + need + margin`` fits
live-available RAM. Concurrent cold loads therefore can never stack up and
swap the machine, while concurrent hot calls run fully in parallel.

The ledger is guarded by a **briefly-held, platform-native file mutex**:
``fcntl.flock`` on POSIX (macOS/Linux), ``msvcrt.locking`` on Windows. Both
release automatically when the holding process dies, so a crash mid-call can
never wedge the queue; stale reservations from dead PIDs are pruned on the next
acquire. The mutex is held only for the microsecond ledger read-modify-write,
never around the multi-second model call itself.

Disable with ``LIGHTHOUSE_OLLAMA_QUEUE=off`` (e.g. on a dedicated server where
Ollama's own ``OLLAMA_MAX_LOADED_MODELS`` already bounds memory).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

try:  # POSIX (macOS, Linux)
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows only
    fcntl = None  # type: ignore[assignment]

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX only
    msvcrt = None  # type: ignore[assignment]

__all__ = ["AdmissionConfig", "ollama_slot"]

_FALSY = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class AdmissionConfig:
    """Tunables for the admission queue.

    ``wait_timeout_s`` is how long a cold-load call waits for RAM headroom to
    appear before giving up and signalling the caller to use the low-memory
    mock instead of forcing a swap. ``margin_gb`` is left free after every
    admitted load so the OS and our own process keep breathing.
    """

    enabled: bool = True
    wait_timeout_s: float = 15.0
    poll_s: float = 0.5
    margin_gb: float = 1.5

    @classmethod
    def from_env(cls) -> AdmissionConfig:
        raw = os.environ.get("LIGHTHOUSE_OLLAMA_QUEUE")
        enabled = not (raw is not None and raw.strip().lower() in _FALSY)
        out = cls(enabled=enabled)
        timeout = os.environ.get("LIGHTHOUSE_OLLAMA_QUEUE_TIMEOUT")
        if timeout is not None:
            try:
                out = replace_timeout(out, float(timeout))
            except ValueError:
                pass
        return out


def replace_timeout(cfg: AdmissionConfig, wait_timeout_s: float) -> AdmissionConfig:
    return AdmissionConfig(
        enabled=cfg.enabled,
        wait_timeout_s=wait_timeout_s,
        poll_s=cfg.poll_s,
        margin_gb=cfg.margin_gb,
    )


# --- platform-native brief mutex ----------------------------------------


@contextmanager
def _file_mutex(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive OS lock on ``lock_path`` for the duration of the body.

    POSIX uses ``fcntl.flock``; Windows uses ``msvcrt.locking``. Both are
    advisory locks tied to the open file descriptor, so they release on
    ``close`` *and* on process death — a crash inside the body cannot leave the
    queue permanently locked. Intended to wrap only the tiny ledger update.
    """
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows only
            os.lseek(fd, 0, os.SEEK_SET)
            # LK_LOCK blocks (retrying) until the 1-byte region is ours.
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows only
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)


def _have_file_lock() -> bool:
    return fcntl is not None or msvcrt is not None


# --- reservation ledger --------------------------------------------------


def _pid_alive(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception:
        # Best effort without psutil: signal 0 probes the process.
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        except Exception:
            return True
        return True


def _ledger_path(lock_path: Path) -> Path:
    return lock_path.with_name(lock_path.name + ".ledger.json")


def _read_ledger(path: Path) -> list[dict]:
    """Return live reservations, dropping any whose owning process has died."""
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return []
    except OSError:
        return []
    try:
        entries = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict) and "pid" in e and _pid_alive(int(e["pid"]))]


def _write_ledger(path: Path, entries: list[dict]) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(entries))
    os.replace(tmp, path)  # atomic on POSIX and Windows


def _reserved_gb(entries: list[dict]) -> float:
    return sum(float(e.get("gb", 0.0)) for e in entries)


def _available_gb() -> float:
    try:
        import psutil

        return psutil.virtual_memory().available / 1e9
    except Exception:
        return float("inf")  # can't measure → don't block (caller's RAM guard still applies)


@contextmanager
def ollama_slot(
    lock_path: Path | str,
    model: str,
    *,
    need_gb_fn: Callable[[str], float],
    cfg: AdmissionConfig | None = None,
    sleep: Callable[[float], None] = time.sleep,
    available_gb_fn: Callable[[], float] = _available_gb,
) -> Iterator[bool]:
    """Reserve RAM headroom for one Ollama call; yield whether it was admitted.

    ``need_gb_fn(model) -> float`` is how much *new* resident RAM this call will
    add: ``0`` (or less) for an already-loaded model or an SSD-paging MoE, else
    the estimated weight size. A zero-need call is admitted instantly with no
    locking. A positive-need call is admitted once
    ``reserved + need + margin <= available``; until then it polls up to
    ``cfg.wait_timeout_s`` and otherwise yields ``False`` so the caller can fall
    back to the low-memory mock instead of forcing a swap.

    When the queue is disabled or no OS file lock is available, this degrades to
    a single in-place headroom check with no cross-process coordination.
    """
    cfg = cfg or AdmissionConfig()
    need = need_gb_fn(model)

    # Hot path: nothing new to load → no RAM to guard, no lock to take.
    if need <= 0:
        yield True
        return

    if not cfg.enabled or not _have_file_lock():
        # Best-effort single check; no ledger, no cross-process guarantee.
        yield need + cfg.margin_gb <= available_gb_fn()
        return

    lock_path = Path(lock_path)
    ledger = _ledger_path(lock_path)
    rid = f"{os.getpid()}:{uuid.uuid4().hex}"
    deadline = time.monotonic() + cfg.wait_timeout_s

    # The file mutex below serialises sibling threads too (independent fds
    # mutually exclude under flock), so the ledger read-modify-write is safe
    # without a separate in-process lock — and nothing is held during the call.
    while True:
        admitted = False
        with _file_mutex(lock_path):
            entries = _read_ledger(ledger)
            if _reserved_gb(entries) + need + cfg.margin_gb <= available_gb_fn():
                entries.append(
                    {"rid": rid, "pid": os.getpid(), "gb": need, "model": model, "ts": time.time()}
                )
                _write_ledger(ledger, entries)
                admitted = True
        if admitted:
            break
        if time.monotonic() >= deadline:
            yield False
            return
        sleep(cfg.poll_s)

    try:
        yield True
    finally:
        with _file_mutex(lock_path):
            entries = [e for e in _read_ledger(ledger) if e.get("rid") != rid]
            _write_ledger(ledger, entries)
