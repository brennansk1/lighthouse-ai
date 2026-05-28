"""Per-file quarantine manifest, backed by ``quarantine.db`` under data_dir.

Records every download Lighthouse saw and the verdict pipeline assigned.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
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
    seen_at TEXT NOT NULL DEFAULT (datetime('now'))
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


class Quarantine:
    def __init__(self, db_path: Path, root: Path):
        self.db_path = db_path
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        conn = open_db(db_path)
        try:
            conn.executescript(_QUARANTINE_SCHEMA)
        finally:
            conn.close()

    @staticmethod
    def hash_bytes(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def record(self, *, sha256: str, url: str | None, filename: str | None,
               content_type: str | None, verdict: str,
               reasons: list[dict], payload: bytes,
               persist: bool = True) -> QuarantineRecord:
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
                     bytes_size, saved_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    verdict = excluded.verdict,
                    reasons_json = excluded.reasons_json,
                    saved_path = excluded.saved_path,
                    seen_at = datetime('now')
                """,
                (sha256, url, filename, content_type, verdict,
                 json.dumps(reasons), len(payload), saved_path),
            )
            row = conn.execute(
                "SELECT seen_at FROM quarantine WHERE sha256 = ?", (sha256,),
            ).fetchone()
        finally:
            conn.close()
        return QuarantineRecord(
            sha256=sha256, url=url, filename=filename, content_type=content_type,
            verdict=verdict, reasons=reasons, bytes_size=len(payload),
            saved_path=saved_path, seen_at=row[0] if row else "",
        )

    def list(self, *, verdict: str | None = None,
             limit: int = 100) -> list[dict]:
        conn = open_db(self.db_path)
        try:
            if verdict:
                rows = conn.execute(
                    "SELECT sha256, url, filename, content_type, verdict, "
                    "reasons_json, bytes_size, saved_path, seen_at "
                    "FROM quarantine WHERE verdict = ? "
                    "ORDER BY seen_at DESC LIMIT ?", (verdict, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT sha256, url, filename, content_type, verdict, "
                    "reasons_json, bytes_size, saved_path, seen_at "
                    "FROM quarantine ORDER BY seen_at DESC LIMIT ?", (limit,),
                ).fetchall()
        finally:
            conn.close()
        out = []
        for r in rows:
            out.append({
                "sha256": r[0], "url": r[1], "filename": r[2],
                "content_type": r[3], "verdict": r[4],
                "reasons": json.loads(r[5]) if r[5] else [],
                "bytes_size": r[6], "saved_path": r[7], "seen_at": r[8],
            })
        return out

    def restore(self, sha256: str, dest: Path) -> Path:
        """Copy a quarantined artifact into ``dest`` (admit elevation)."""
        conn = open_db(self.db_path)
        try:
            row = conn.execute(
                "SELECT saved_path FROM quarantine WHERE sha256 = ?", (sha256,),
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
