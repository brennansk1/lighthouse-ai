"""Per-file quarantine manifest, backed by ``quarantine.db`` under data_dir.

Records every download Lighthouse saw and the verdict pipeline assigned.

Quota / eviction
----------------
Pass ``max_bytes`` to ``Quarantine.__init__`` to set a storage cap.  After
every ``record(...)`` call the quota is enforced automatically: the oldest
rows (by ``seen_at``) whose on-disk payloads would push total stored bytes
over the limit are evicted — their files are deleted and their DB row is
updated to ``evicted=1, saved_path=NULL``.

WORM protection
---------------
Any record tagged with ``worm=True`` (via ``mark_worm(sha256)`` or the
``worm=`` keyword on ``record()``) is **never** evicted, regardless of age or
quota pressure.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..persistence import open_db

_QUARANTINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS quarantine (
    sha256 TEXT PRIMARY KEY,
    url TEXT,
    filename TEXT,
    content_type TEXT,
    verdict TEXT NOT NULL,                  -- admit | quarantine | reject
    reasons_json TEXT,
    bytes_size INTEGER NOT NULL,
    saved_path TEXT,                        -- absolute path under data_dir
    seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    worm INTEGER NOT NULL DEFAULT 0,        -- 1 = WORM-protected, never evict
    evicted INTEGER NOT NULL DEFAULT 0      -- 1 = payload removed by quota eviction
);
CREATE INDEX IF NOT EXISTS idx_quarantine_verdict ON quarantine (verdict);
CREATE INDEX IF NOT EXISTS idx_quarantine_seen ON quarantine (seen_at);
"""


@dataclass(frozen=True)
class QuarantineRecord:
    sha256: str
    url: str | None
    filename: str | None
    content_type: str | None
    verdict: str
    reasons: list[dict]
    bytes_size: int
    saved_path: str | None
    seen_at: str
    worm: bool = field(default=False)
    evicted: bool = field(default=False)


class Quarantine:
    """Quarantine manifest with optional storage-quota enforcement.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.
    root:
        Directory tree where persisted payloads are stored.
    max_bytes:
        Optional storage cap (bytes).  ``None`` (default) means unbounded —
        no eviction ever occurs.  When set, :meth:`enforce_quota` is called
        automatically after every successful :meth:`record` call.
    """

    def __init__(self, db_path: Path, root: Path, max_bytes: int | None = None) -> None:
        self.db_path = db_path
        self.root = root
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        conn = open_db(db_path)
        try:
            conn.executescript(_QUARANTINE_SCHEMA)
            _ensure_worm_column(conn)
            _ensure_evicted_column(conn)
        finally:
            conn.close()

    @staticmethod
    def hash_bytes(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def record(
        self,
        *,
        sha256: str,
        url: str | None,
        filename: str | None,
        content_type: str | None,
        verdict: str,
        reasons: list[dict],
        payload: bytes,
        persist: bool = True,
        worm: bool = False,
    ) -> QuarantineRecord:
        saved_path: str | None = None
        if persist and verdict != "reject":
            sub = self.root / verdict
            sub.mkdir(parents=True, exist_ok=True)
            dst = sub / f"{sha256}{_ext_for(filename, content_type)}"
            dst.write_bytes(payload)
            saved_path = str(dst)
        conn = open_db(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO quarantine
                    (sha256, url, filename, content_type, verdict, reasons_json,
                     bytes_size, saved_path, worm)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    verdict = excluded.verdict,
                    reasons_json = excluded.reasons_json,
                    saved_path = excluded.saved_path,
                    seen_at = datetime('now'),
                    worm = MAX(worm, excluded.worm),
                    evicted = 0
                """,
                (
                    sha256,
                    url,
                    filename,
                    content_type,
                    verdict,
                    json.dumps(reasons),
                    len(payload),
                    saved_path,
                    int(worm),
                ),
            )
            row = conn.execute(
                "SELECT seen_at, worm, evicted FROM quarantine WHERE sha256 = ?",
                (sha256,),
            ).fetchone()
        finally:
            conn.close()
        rec = QuarantineRecord(
            sha256=sha256,
            url=url,
            filename=filename,
            content_type=content_type,
            verdict=verdict,
            reasons=reasons,
            bytes_size=len(payload),
            saved_path=saved_path,
            seen_at=row[0] if row else "",
            worm=bool(row[1]) if row else worm,
            evicted=bool(row[2]) if row else False,
        )
        if self.max_bytes is not None:
            self.enforce_quota()
        return rec

    def mark_worm(self, sha256: str) -> None:
        """Mark a record as WORM-protected so it is never evicted by quota."""
        conn = open_db(self.db_path)
        try:
            conn.execute(
                "UPDATE quarantine SET worm = 1 WHERE sha256 = ?",
                (sha256,),
            )
        finally:
            conn.close()

    def enforce_quota(self) -> int:
        """Evict oldest non-WORM records until total stored bytes <= max_bytes.

        Returns the number of records evicted.  Safe to call when
        ``max_bytes`` is ``None`` — it immediately returns 0.

        Eviction touches only rows where ``saved_path IS NOT NULL`` and
        ``worm = 0`` and ``evicted = 0``, ordered oldest-first by ``seen_at``.
        On eviction the on-disk file is deleted and the row is updated to
        ``evicted=1, saved_path=NULL``.
        """
        if self.max_bytes is None:
            return 0

        conn = open_db(self.db_path)
        try:
            # Current total stored bytes (non-evicted rows with a file).
            total_row = conn.execute(
                "SELECT COALESCE(SUM(bytes_size), 0) FROM quarantine "
                "WHERE saved_path IS NOT NULL AND evicted = 0"
            ).fetchone()
            total: int = int(total_row[0])

            if total <= self.max_bytes:
                return 0

            # Candidates: non-WORM, non-evicted, has a file, oldest first.
            candidates = conn.execute(
                "SELECT sha256, saved_path, bytes_size FROM quarantine "
                "WHERE saved_path IS NOT NULL AND worm = 0 AND evicted = 0 "
                "ORDER BY seen_at ASC"
            ).fetchall()
        finally:
            conn.close()

        evicted_count = 0
        for sha256, saved_path, bytes_size in candidates:
            if total <= self.max_bytes:
                break
            # Delete on-disk file.
            if saved_path:
                try:
                    Path(saved_path).unlink()
                except FileNotFoundError:
                    pass
            # Mark row evicted.
            conn2 = open_db(self.db_path)
            try:
                conn2.execute(
                    "UPDATE quarantine SET evicted = 1, saved_path = NULL WHERE sha256 = ?",
                    (sha256,),
                )
            finally:
                conn2.close()
            total -= bytes_size
            evicted_count += 1

        return evicted_count

    def list(self, *, verdict: str | None = None, limit: int = 100) -> list[dict]:
        conn = open_db(self.db_path)
        try:
            if verdict:
                rows = conn.execute(
                    "SELECT sha256, url, filename, content_type, verdict, "
                    "reasons_json, bytes_size, saved_path, seen_at, worm, evicted "
                    "FROM quarantine WHERE verdict = ? "
                    "ORDER BY seen_at DESC LIMIT ?",
                    (verdict, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT sha256, url, filename, content_type, verdict, "
                    "reasons_json, bytes_size, saved_path, seen_at, worm, evicted "
                    "FROM quarantine ORDER BY seen_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        finally:
            conn.close()
        out = []
        for r in rows:
            out.append(
                {
                    "sha256": r[0],
                    "url": r[1],
                    "filename": r[2],
                    "content_type": r[3],
                    "verdict": r[4],
                    "reasons": json.loads(r[5]) if r[5] else [],
                    "bytes_size": r[6],
                    "saved_path": r[7],
                    "seen_at": r[8],
                    "worm": bool(r[9]),
                    "evicted": bool(r[10]),
                }
            )
        return out

    def restore(self, sha256: str, dest: Path) -> Path:
        """Copy a quarantined artifact into ``dest`` (admit elevation)."""
        conn = open_db(self.db_path)
        try:
            row = conn.execute(
                "SELECT saved_path FROM quarantine WHERE sha256 = ?",
                (sha256,),
            ).fetchone()
        finally:
            conn.close()
        if not row or not row[0]:
            raise FileNotFoundError(f"no quarantine record for {sha256}")
        src = Path(row[0])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        return dest

    def purge(self, verdict: str = "quarantine") -> int:
        """Delete the on-disk artifacts AND DB rows for a verdict class."""
        rows = self.list(verdict=verdict, limit=10_000)
        for r in rows:
            if r["saved_path"]:
                try:
                    Path(r["saved_path"]).unlink()
                except FileNotFoundError:
                    pass
        conn = open_db(self.db_path)
        try:
            cur = conn.execute("DELETE FROM quarantine WHERE verdict = ?", (verdict,))
        finally:
            conn.close()
        return cur.rowcount or 0


# ---------------------------------------------------------------------------
# Schema helpers — idempotent ALTER TABLE for in-place DB upgrades
# ---------------------------------------------------------------------------


def _ensure_worm_column(conn: object) -> None:  # type: ignore[type-arg]
    """Add the ``worm`` column to an existing DB that predates it."""
    import sqlite3 as _sqlite3

    assert isinstance(conn, _sqlite3.Connection)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(quarantine)")}
    if "worm" not in cols:
        conn.execute("ALTER TABLE quarantine ADD COLUMN worm INTEGER NOT NULL DEFAULT 0")


def _ensure_evicted_column(conn: object) -> None:  # type: ignore[type-arg]
    """Add the ``evicted`` column to an existing DB that predates it."""
    import sqlite3 as _sqlite3

    assert isinstance(conn, _sqlite3.Connection)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(quarantine)")}
    if "evicted" not in cols:
        conn.execute("ALTER TABLE quarantine ADD COLUMN evicted INTEGER NOT NULL DEFAULT 0")


def _ext_for(filename: str | None, content_type: str | None) -> str:
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix:
            return suffix
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return ".pdf"
    if "html" in ct:
        return ".html"
    if "zip" in ct:
        return ".zip"
    if "svg" in ct:
        return ".svg"
    return ".bin"
