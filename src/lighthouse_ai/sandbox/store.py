"""SandboxStore — the secured two-zone data store (SB1).

The Sandbox is the controlled place where two very different writers meet:

* **uploads** — files the *user* hands Lighthouse.  These are read-only to the
  LLM: an analysis skill may read an upload but may never write into the
  uploads zone.
* **workspace** — analysis artifacts the *LLM* produces (derived tables,
  chart data, notes).  This is the only zone an LLM writer may target.

Every byte that enters the store — from either zone — first passes through the
:class:`~lighthouse_ai.sandbox.broker.SandboxBroker`.  A ``REJECT`` verdict means
the bytes are never written to disk and ``add`` returns ``None``.  ``ADMIT`` and
``QUARANTINE`` are both stored (quarantined items are recorded but only readable
via an explicit opt-in flag), exactly as the broker already does for the
quarantine manifest.

Storage discipline mirrors :class:`~lighthouse_ai.sandbox.quarantine.Quarantine`:

* a small dedicated SQLite table (``sandbox.db``) holds metadata — it is *not*
  the quarantine database;
* on-disk payloads are written atomically (temp file + ``os.replace``) under a
  sha-derived filename so a caller-supplied ``filename`` can never cause a path
  collision or directory traversal;
* an optional ``max_bytes`` cap is enforced after every ``add`` by evicting the
  oldest non-pinned items LRU-style (``pin`` is the workspace analogue of
  quarantine's WORM flag — pinned items are never evicted);
* schema upgrades are idempotent ``_ensure_*`` helpers.

Determinism / offline: this module never calls ``datetime.now()`` — every
timestamp is passed in by the caller (``now=``), so tests and replay are
reproducible.

The configurable size cap lives here as the module default
:data:`DEFAULT_MAX_BYTES` plus the ``SandboxStore(max_bytes=...)`` constructor
parameter.  Wiring that knob to the API / settings layer is SB3's job.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ..ingest import extract_text
from ..persistence import open_db

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .broker import SandboxBroker

# Builtin aliases so annotations stay valid even though this class defines a
# ``list`` method (which shadows the builtin name at class-body scope).
_List = list
_Dict = dict

# Two zones live side-by-side under ``data_dir / "sandbox"``.
Zone = Literal["uploads", "workspace"]
ZONES: tuple[Zone, ...] = ("uploads", "workspace")

# Default storage cap for the whole sandbox (uploads + workspace), in bytes.
# Override per-instance with ``SandboxStore(max_bytes=...)``.  SB3 wires this to
# the settings / API layer; here it is just a sane module default.
DEFAULT_MAX_BYTES = 512 * 1024 * 1024  # 512 MiB

_SANDBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS sandbox_items (
    id TEXT PRIMARY KEY,                    -- opaque uuid4 hex
    sha256 TEXT NOT NULL,
    zone TEXT NOT NULL,                     -- uploads | workspace
    filename TEXT,                          -- original (untrusted) name
    content_type TEXT,
    size_bytes INTEGER NOT NULL,
    source TEXT NOT NULL,                   -- user | skill:<id> | run:<job> | ...
    scan_verdict TEXT NOT NULL,             -- admit | quarantine | reject
    preview_type TEXT,                      -- derived: text | binary | ...
    pinned INTEGER NOT NULL DEFAULT 0,      -- 1 = never evicted by quota
    evicted INTEGER NOT NULL DEFAULT 0,     -- 1 = payload removed by quota
    saved_path TEXT,                        -- absolute path under the zone dir
    created_at TEXT NOT NULL                -- caller-supplied timestamp
);
CREATE INDEX IF NOT EXISTS idx_sandbox_zone ON sandbox_items (zone);
CREATE INDEX IF NOT EXISTS idx_sandbox_created ON sandbox_items (created_at);
CREATE INDEX IF NOT EXISTS idx_sandbox_sha ON sandbox_items (sha256);
"""


@dataclass(frozen=True)
class SandboxItem:
    """Metadata for one stored payload.  ``saved_path`` is ``None`` once evicted."""

    id: str
    sha256: str
    zone: str
    filename: str | None
    content_type: str | None
    size_bytes: int
    source: str
    scan_verdict: str
    preview_type: str | None
    pinned: bool
    evicted: bool
    saved_path: str | None
    created_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "sha256": self.sha256,
            "zone": self.zone,
            "filename": self.filename,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "source": self.source,
            "scan_verdict": self.scan_verdict,
            "preview_type": self.preview_type,
            "pinned": self.pinned,
            "evicted": self.evicted,
            "saved_path": self.saved_path,
            "created_at": self.created_at,
        }


class SandboxStore:
    """Two-zone, broker-gated, quota-bounded artifact store.

    Parameters
    ----------
    data_dir:
        The Lighthouse data dir (``paths.data_dir``).  The sandbox lives under
        ``data_dir / "sandbox"`` with ``uploads/`` and ``workspace/`` subdirs
        and its own ``sandbox.db`` metadata database.
    max_bytes:
        Storage cap across both zones.  ``None`` ⇒ unbounded (no eviction).
        Defaults to :data:`DEFAULT_MAX_BYTES`.
    """

    def __init__(self, data_dir: Path,
                 max_bytes: int | None = DEFAULT_MAX_BYTES) -> None:
        self.root = (Path(data_dir) / "sandbox").resolve()
        self.db_path = self.root / "sandbox.db"
        self.max_bytes = max_bytes
        # Pre-resolve each zone root so ``_safe_path`` can do containment checks.
        self._zone_roots: dict[str, Path] = {}
        for zone in ZONES:
            zdir = (self.root / zone).resolve()
            zdir.mkdir(parents=True, exist_ok=True)
            self._zone_roots[zone] = zdir
        conn = open_db(self.db_path)
        try:
            conn.executescript(_SANDBOX_SCHEMA)
            _ensure_columns(conn)
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # Hashing / safe paths
    # ------------------------------------------------------------------ #

    @staticmethod
    def hash_bytes(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def _safe_path(self, zone: Zone, name: str) -> Path:
        """Resolve ``name`` strictly under ``zone``'s root.

        We never honor a caller-supplied path that escapes the zone: any
        ``..`` segment, absolute path, or symlink that would resolve outside
        the zone root raises ``ValueError``.  Callers should pass sha-derived
        leaf names; this is the last line of defence.
        """
        zone_root = self._zone_roots.get(zone)
        if zone_root is None:
            raise ValueError(f"unknown sandbox zone: {zone!r}")
        # Take only the final path component to strip any directory parts a
        # hostile filename smuggled in (``../../etc/x`` → ``x``), then resolve
        # and confirm the result is contained within the zone root.
        leaf = Path(name).name
        if not leaf or leaf in (".", ".."):
            raise ValueError(f"invalid sandbox filename: {name!r}")
        candidate = (zone_root / leaf).resolve()
        if candidate != zone_root and zone_root not in candidate.parents:
            raise ValueError(
                f"path escapes sandbox zone root: {name!r} -> {candidate}"
            )
        return candidate

    def _stored_name(self, sha256: str, filename: str | None,
                     content_type: str | None) -> str:
        """sha-derived, collision-free, traversal-proof on-disk leaf name."""
        return f"{sha256}{_ext_for(filename, content_type)}"

    @staticmethod
    def _atomic_write(dst: Path, payload: bytes) -> None:
        """Write ``payload`` to ``dst`` atomically (temp file + os.replace)."""
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f".{dst.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_bytes(payload)
            os.replace(tmp, dst)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    # ------------------------------------------------------------------ #
    # Add / write
    # ------------------------------------------------------------------ #

    def add(self, payload: bytes, *, zone: Zone, filename: str | None,
            content_type: str | None, source: str, broker: SandboxBroker,
            now: str, pinned: bool = False) -> SandboxItem | None:
        """Broker-gate, then store ``payload`` in ``zone``.

        The broker runs **first**.  ``REJECT`` ⇒ nothing is written and ``None``
        is returned.  ``ADMIT`` / ``QUARANTINE`` ⇒ the bytes are written
        atomically under a sha-derived leaf name in the zone, metadata is
        recorded with the verdict, and :meth:`enforce_quota` runs.

        ``now`` is a caller-supplied timestamp string (no ``datetime.now()``).
        """
        if zone not in self._zone_roots:
            raise ValueError(f"unknown sandbox zone: {zone!r}")

        outcome = broker.admit(payload, url=None, filename=filename,
                               content_type=content_type)
        verdict = outcome.verdict.value
        if verdict == "reject":
            return None

        sha = outcome.sha256
        leaf = self._stored_name(sha, filename, content_type)
        dst = self._safe_path(zone, leaf)
        self._atomic_write(dst, payload)

        preview_type = _preview_type(payload, content_type, filename)
        item_id = uuid.uuid4().hex

        conn = open_db(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO sandbox_items
                    (id, sha256, zone, filename, content_type, size_bytes,
                     source, scan_verdict, preview_type, pinned, evicted,
                     saved_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (item_id, sha, zone, filename, content_type, len(payload),
                 source, verdict, preview_type, int(pinned), str(dst), now),
            )
        finally:
            conn.close()

        self.enforce_quota()

        # Re-read so the returned record reflects post-quota state (an item can
        # in principle be evicted by its own insertion if it alone exceeds cap).
        item = self.stat(item_id)
        return item

    def write_artifact(self, payload: bytes, *, filename: str | None,
                       content_type: str | None, source: str,
                       broker: SandboxBroker, now: str,
                       pinned: bool = False) -> SandboxItem | None:
        """LLM-facing writer — artifacts may ONLY land in the workspace zone.

        This is the natural API expression of the uploads-are-read-only rule:
        a workspace writer simply has no parameter with which to target
        ``uploads``.  (Enforcing *which* callers may write is SB2's contract;
        the store just makes the safe path the only path.)
        """
        return self.add(payload, zone="workspace", filename=filename,
                        content_type=content_type, source=source,
                        broker=broker, now=now, pinned=pinned)

    # ------------------------------------------------------------------ #
    # Read / list / stat
    # ------------------------------------------------------------------ #

    def list(self, zone: Zone | None = None) -> _List[SandboxItem]:
        conn = open_db(self.db_path)
        try:
            if zone is not None:
                rows = conn.execute(
                    f"SELECT {_COLS} FROM sandbox_items WHERE zone = ? "
                    "ORDER BY created_at DESC, id DESC",
                    (zone,),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {_COLS} FROM sandbox_items "
                    "ORDER BY created_at DESC, id DESC"
                ).fetchall()
        finally:
            conn.close()
        return [_row_to_item(r) for r in rows]

    def stat(self, item_id: str) -> SandboxItem | None:
        conn = open_db(self.db_path)
        try:
            row = conn.execute(
                f"SELECT {_COLS} FROM sandbox_items WHERE id = ?", (item_id,),
            ).fetchone()
        finally:
            conn.close()
        return _row_to_item(row) if row else None

    def read(self, item_id: str, *, allow_quarantined: bool = False) -> bytes:
        """Return the on-disk bytes for an item.

        Only ``admit``-verdict items are readable by default; quarantined items
        require ``allow_quarantined=True`` (an explicit, auditable opt-in).
        Rejected items never exist in the store, so they can never be read.
        """
        item = self.stat(item_id)
        if item is None:
            raise KeyError(item_id)
        if item.evicted or not item.saved_path:
            raise FileNotFoundError(f"payload evicted: {item_id}")
        if item.scan_verdict == "quarantine" and not allow_quarantined:
            raise PermissionError(
                f"item {item_id} is quarantined; pass allow_quarantined=True "
                "to read it"
            )
        # Re-validate containment before touching disk (defence in depth).
        path = Path(item.saved_path).resolve()
        zone_root = self._zone_roots.get(item.zone)
        if zone_root is None or (
            path != zone_root and zone_root not in path.parents
        ):
            raise PermissionError(f"stored path escapes sandbox: {path}")
        return path.read_bytes()

    # ------------------------------------------------------------------ #
    # Mutation: pin / remove
    # ------------------------------------------------------------------ #

    def pin(self, item_id: str, pinned: bool = True) -> None:
        """Pin (or unpin) an item.  Pinned items are never evicted by quota."""
        conn = open_db(self.db_path)
        try:
            conn.execute(
                "UPDATE sandbox_items SET pinned = ? WHERE id = ?",
                (int(pinned), item_id),
            )
        finally:
            conn.close()

    def remove(self, item_id: str) -> bool:
        """Delete an item's on-disk payload and its metadata row."""
        item = self.stat(item_id)
        if item is None:
            return False
        if item.saved_path:
            try:
                Path(item.saved_path).unlink()
            except FileNotFoundError:
                pass
        conn = open_db(self.db_path)
        try:
            conn.execute("DELETE FROM sandbox_items WHERE id = ?", (item_id,))
        finally:
            conn.close()
        return True

    # ------------------------------------------------------------------ #
    # Quota
    # ------------------------------------------------------------------ #

    def enforce_quota(self) -> int:
        """Evict oldest non-pinned items until stored bytes <= ``max_bytes``.

        Mirrors :meth:`Quarantine.enforce_quota`: only live (``evicted = 0``,
        ``saved_path IS NOT NULL``) non-pinned rows are candidates, oldest
        first by ``created_at``.  On eviction the on-disk file is deleted and
        the row is marked ``evicted = 1, saved_path = NULL``.  Returns the count
        evicted.  Returns 0 immediately when ``max_bytes is None``.
        """
        if self.max_bytes is None:
            return 0

        conn = open_db(self.db_path)
        try:
            total_row = conn.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) FROM sandbox_items "
                "WHERE saved_path IS NOT NULL AND evicted = 0"
            ).fetchone()
            total = int(total_row[0])
            if total <= self.max_bytes:
                return 0
            candidates = conn.execute(
                "SELECT id, saved_path, size_bytes FROM sandbox_items "
                "WHERE saved_path IS NOT NULL AND pinned = 0 AND evicted = 0 "
                "ORDER BY created_at ASC, id ASC"
            ).fetchall()
        finally:
            conn.close()

        evicted = 0
        for item_id, saved_path, size_bytes in candidates:
            if total <= self.max_bytes:
                break
            if saved_path:
                try:
                    Path(saved_path).unlink()
                except FileNotFoundError:
                    pass
            conn2 = open_db(self.db_path)
            try:
                conn2.execute(
                    "UPDATE sandbox_items SET evicted = 1, saved_path = NULL "
                    "WHERE id = ?",
                    (item_id,),
                )
            finally:
                conn2.close()
            total -= int(size_bytes)
            evicted += 1
        return evicted

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #

    def usage(self) -> dict[str, object]:
        """Total live bytes, the cap, and a per-zone byte breakdown."""
        conn = open_db(self.db_path)
        try:
            total_row = conn.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) FROM sandbox_items "
                "WHERE evicted = 0"
            ).fetchone()
            zone_rows = conn.execute(
                "SELECT zone, COALESCE(SUM(size_bytes), 0) FROM sandbox_items "
                "WHERE evicted = 0 GROUP BY zone"
            ).fetchall()
        finally:
            conn.close()
        by_zone = {z: 0 for z in ZONES}
        for zone, nbytes in zone_rows:
            by_zone[zone] = int(nbytes)
        return {
            "used_bytes": int(total_row[0]),
            "max_bytes": self.max_bytes,
            "by_zone": by_zone,
        }

    def breakdown(self) -> _Dict[str, _List[_Dict[str, object]]]:
        """Count + bytes grouped by zone, content/preview type, and source.

        Shaped for the dashboard viz: three parallel lists of
        ``{key, count, bytes}`` rows under ``"by_zone"``, ``"by_type"``,
        ``"by_source"``.  Evicted rows are excluded (no live bytes).
        """
        conn = open_db(self.db_path)
        try:
            zone_rows = conn.execute(
                "SELECT zone, COUNT(*), COALESCE(SUM(size_bytes), 0) "
                "FROM sandbox_items WHERE evicted = 0 GROUP BY zone "
                "ORDER BY zone"
            ).fetchall()
            type_rows = conn.execute(
                "SELECT COALESCE(preview_type, 'unknown'), COUNT(*), "
                "COALESCE(SUM(size_bytes), 0) "
                "FROM sandbox_items WHERE evicted = 0 GROUP BY preview_type "
                "ORDER BY preview_type"
            ).fetchall()
            source_rows = conn.execute(
                "SELECT source, COUNT(*), COALESCE(SUM(size_bytes), 0) "
                "FROM sandbox_items WHERE evicted = 0 GROUP BY source "
                "ORDER BY source"
            ).fetchall()
        finally:
            conn.close()

        def _shape(rows: _List[Any]) -> _List[_Dict[str, object]]:
            return [
                {"key": r[0], "count": int(r[1]), "bytes": int(r[2])}
                for r in rows
            ]

        return {
            "by_zone": _shape(zone_rows),
            "by_type": _shape(type_rows),
            "by_source": _shape(source_rows),
        }


# --------------------------------------------------------------------------- #
# Module helpers
# --------------------------------------------------------------------------- #

_COLS = (
    "id, sha256, zone, filename, content_type, size_bytes, source, "
    "scan_verdict, preview_type, pinned, evicted, saved_path, created_at"
)


def _row_to_item(row: Any) -> SandboxItem:
    return SandboxItem(
        id=str(row[0]),
        sha256=str(row[1]),
        zone=str(row[2]),
        filename=str(row[3]) if row[3] is not None else None,
        content_type=str(row[4]) if row[4] is not None else None,
        size_bytes=int(row[5]),
        source=str(row[6]),
        scan_verdict=str(row[7]),
        preview_type=str(row[8]) if row[8] is not None else None,
        pinned=bool(row[9]),
        evicted=bool(row[10]),
        saved_path=str(row[11]) if row[11] is not None else None,
        created_at=str(row[12]),
    )


def _preview_type(payload: bytes, content_type: str | None,
                  filename: str | None) -> str:
    """Derive a coarse previewable type for the dashboard.

    Reuses :func:`lighthouse_ai.ingest.extract_text`: if we can pull any
    readable text out, the item is ``"text"``; otherwise ``"binary"``.  This is
    best-effort and never raises — extraction failures degrade to ``"binary"``.
    """
    try:
        text = extract_text(payload, content_type, filename)
    except Exception:
        return "binary"
    return "text" if text.strip() else "binary"


def _ext_for(filename: str | None, content_type: str | None) -> str:
    """sha-derived leaf suffix.  Mirrors quarantine's mapping for consistency."""
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
    if "json" in ct:
        return ".json"
    if "csv" in ct:
        return ".csv"
    if "text" in ct:
        return ".txt"
    return ".bin"


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Idempotent in-place schema upgrades for pre-existing sandbox DBs."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sandbox_items)")}
    upgrades = {
        "preview_type": "ALTER TABLE sandbox_items ADD COLUMN preview_type TEXT",
        "pinned": "ALTER TABLE sandbox_items ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0",
        "evicted": "ALTER TABLE sandbox_items ADD COLUMN evicted INTEGER NOT NULL DEFAULT 0",
        "saved_path": "ALTER TABLE sandbox_items ADD COLUMN saved_path TEXT",
    }
    for col, ddl in upgrades.items():
        if col not in cols:
            conn.execute(ddl)
