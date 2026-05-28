"""SQLite connection helpers with Lighthouse robustness defaults.

Every ``.db`` file MUST open with the PRAGMAs defined in design §26.1.
``open_db`` applies them, asserts the result, and returns the connection.

Design rationale: Litestream requires WAL mode; ``synchronous = NORMAL`` is
safe in WAL mode and gives the best throughput/durability trade-off; foreign
keys are off by default in SQLite and must be enabled per connection.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class PragmaSpec:
    """Required PRAGMA values per §26.1."""

    journal_mode: str = "wal"
    busy_timeout_ms: int = 5000
    synchronous: str = "normal"
    foreign_keys: bool = True
    cache_size_pages: int = -64000  # negative ⇒ KiB; -64000 ⇒ 64 MiB
    temp_store: str = "memory"
    wal_autocheckpoint: int = 1000


DEFAULTS = PragmaSpec()

_SYNC_NAMES = {0: "off", 1: "normal", 2: "full", 3: "extra"}
_TEMP_NAMES = {0: "default", 1: "file", 2: "memory"}


def apply_pragmas(conn: sqlite3.Connection, spec: PragmaSpec = DEFAULTS) -> None:
    """Apply the Lighthouse PRAGMA defaults to an open connection."""
    cur = conn.cursor()
    cur.execute(f"PRAGMA journal_mode = {spec.journal_mode}")
    cur.execute(f"PRAGMA busy_timeout = {spec.busy_timeout_ms}")
    cur.execute(f"PRAGMA synchronous = {spec.synchronous}")
    cur.execute(f"PRAGMA foreign_keys = {'ON' if spec.foreign_keys else 'OFF'}")
    cur.execute(f"PRAGMA cache_size = {spec.cache_size_pages}")
    cur.execute(f"PRAGMA temp_store = {spec.temp_store}")
    cur.execute(f"PRAGMA wal_autocheckpoint = {spec.wal_autocheckpoint}")
    cur.close()


def read_pragmas(conn: sqlite3.Connection) -> dict[str, object]:
    """Read back every PRAGMA we set, in normalized form."""
    cur = conn.cursor()
    out: dict[str, object] = {}
    out["journal_mode"] = str(cur.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    out["busy_timeout"] = int(cur.execute("PRAGMA busy_timeout").fetchone()[0])
    sync_raw = int(cur.execute("PRAGMA synchronous").fetchone()[0])
    out["synchronous"] = _SYNC_NAMES.get(sync_raw, str(sync_raw))
    out["foreign_keys"] = bool(cur.execute("PRAGMA foreign_keys").fetchone()[0])
    out["cache_size"] = int(cur.execute("PRAGMA cache_size").fetchone()[0])
    temp_raw = int(cur.execute("PRAGMA temp_store").fetchone()[0])
    out["temp_store"] = _TEMP_NAMES.get(temp_raw, str(temp_raw))
    out["wal_autocheckpoint"] = int(cur.execute("PRAGMA wal_autocheckpoint").fetchone()[0])
    cur.close()
    return out


class PragmaAssertionError(RuntimeError):
    """Raised when readback does not match the PragmaSpec."""


def assert_pragmas(conn: sqlite3.Connection, spec: PragmaSpec = DEFAULTS) -> None:
    """Read the PRAGMAs back and confirm they match ``spec``.

    Memory databases (``:memory:``) refuse to switch to WAL — this is a SQLite
    limitation, not a Lighthouse one, so we tolerate ``memory`` journal mode on
    in-memory connections. Every on-disk file MUST be WAL.
    """
    got = read_pragmas(conn)
    expected = {
        "journal_mode": spec.journal_mode,
        "busy_timeout": spec.busy_timeout_ms,
        "synchronous": spec.synchronous,
        "foreign_keys": spec.foreign_keys,
        "cache_size": spec.cache_size_pages,
        "temp_store": spec.temp_store,
        "wal_autocheckpoint": spec.wal_autocheckpoint,
    }
    mismatches = {k: (got[k], expected[k]) for k in expected if got[k] != expected[k]}
    # In-memory DBs cannot use WAL.
    if mismatches.get("journal_mode") == ("memory", "wal"):
        mismatches.pop("journal_mode")
    if mismatches:
        raise PragmaAssertionError(f"PRAGMA mismatch: {mismatches}")


def open_db(path: str | Path, *, spec: PragmaSpec = DEFAULTS,
            check_same_thread: bool = False) -> sqlite3.Connection:
    """Open a SQLite database, apply Lighthouse PRAGMAs, and verify them.

    Parameters
    ----------
    path:
        Path to the database file. Use ``":memory:"`` for tests.
    spec:
        Override the PRAGMA defaults (mostly used by tests).
    check_same_thread:
        Passed through to ``sqlite3.connect``. Default ``False`` because the
        supervisor + FastAPI app live in different threads.
    """
    if not isinstance(path, str) or path != ":memory:":
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        path = str(p)
    conn = sqlite3.connect(path, check_same_thread=check_same_thread, isolation_level=None)
    apply_pragmas(conn, spec)
    assert_pragmas(conn, spec)
    return conn


@contextmanager
def db(path: str | Path, *, spec: PragmaSpec = DEFAULTS) -> Iterator[sqlite3.Connection]:
    """Context manager wrapper around :func:`open_db`."""
    conn = open_db(path, spec=spec)
    try:
        yield conn
    finally:
        conn.close()


def integrity_check(conn: sqlite3.Connection) -> str:
    """Run ``PRAGMA integrity_check`` and return the single-row result."""
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    return ",".join(str(r[0]) for r in rows)
