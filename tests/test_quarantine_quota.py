"""Tests for quarantine storage quota and eviction (Sprint 6 — quota/eviction gap).

Covers:
1. Filling past quota → enforce_quota evicts oldest first until under quota,
   on-disk files deleted and rows marked evicted=True.
2. A WORM-tagged record is preserved even when it is the oldest.
3. quota=None → no eviction (back-compat).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from lighthouse_ai.sandbox.quarantine import Quarantine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PAYLOAD_SIZE = 100  # bytes per test payload


def _make_payload(seed: int, size: int = _PAYLOAD_SIZE) -> bytes:
    """Return a deterministic payload of exactly ``size`` bytes."""
    base = f"payload-{seed}-".encode()
    repeated = (base * ((size // len(base)) + 2))[:size]
    return repeated


def _record(q: Quarantine, seed: int, *, worm: bool = False, seen_at: str | None = None) -> str:
    """Record a synthetic payload; optionally override seen_at for ordering."""
    payload = _make_payload(seed)
    sha = Quarantine.hash_bytes(payload)
    q.record(
        sha256=sha,
        url=f"http://example.com/f{seed}",
        filename=f"file{seed}.bin",
        content_type="application/octet-stream",
        verdict="admit",
        reasons=[],
        payload=payload,
        worm=worm,
    )
    if seen_at is not None:
        # Backdate seen_at so tests can control eviction order deterministically.
        conn = sqlite3.connect(str(q.db_path))
        try:
            conn.execute(
                "UPDATE quarantine SET seen_at = ? WHERE sha256 = ?",
                (seen_at, sha),
            )
            conn.commit()
        finally:
            conn.close()
    return sha


# ---------------------------------------------------------------------------
# 1. Basic quota eviction — oldest first, files deleted, rows marked
# ---------------------------------------------------------------------------


def test_evict_oldest_first_until_under_quota(tmp_path: Path) -> None:
    """Records 5 × 100-byte payloads with quota=300 → 3 oldest must be evicted.

    Strategy: insert all records into a quota-less Quarantine (so auto-enforcement
    doesn't fire mid-setup), backdate seen_at, then switch to a quota-bearing
    Quarantine on the same DB and call enforce_quota() explicitly.
    """
    quota = 2 * _PAYLOAD_SIZE  # 200 bytes; 5 records=500 bytes -> evict 3 oldest

    # Phase 1: insert without quota so timestamps can be set cleanly.
    q_setup = Quarantine(tmp_path / "q.db", tmp_path / "store")
    shas = []
    for i in range(5):
        sha = _record(q_setup, seed=i, seen_at=f"2024-01-0{i + 1}T00:00:00")
        shas.append(sha)

    # Phase 2: enforce quota via a new Quarantine with max_bytes set.
    q = Quarantine(tmp_path / "q.db", tmp_path / "store", max_bytes=quota)
    q.enforce_quota()

    rows = {r["sha256"]: r for r in q.list(limit=100)}

    # Total non-evicted stored bytes must be <= quota.
    stored_bytes = sum(r["bytes_size"] for r in rows.values() if not r["evicted"])
    assert stored_bytes <= quota, f"stored_bytes={stored_bytes} exceeds quota={quota}"

    # The three oldest (shas[0..2]) must be evicted; the two newest (shas[3..4]) survive.
    for sha in shas[:3]:
        r = rows[sha]
        assert r["evicted"], f"{sha} should be evicted"
        assert r["saved_path"] is None, "evicted row must have saved_path=NULL"
        # The on-disk file must be gone.
        matches = list(tmp_path.rglob(f"{sha}*"))
        assert not matches, f"on-disk file for evicted {sha} still present: {matches}"

    for sha in shas[3:]:
        r = rows[sha]
        assert not r["evicted"], f"{sha} should NOT be evicted"
        assert r["saved_path"] is not None, "surviving row must still have saved_path"
        assert Path(r["saved_path"]).exists(), "surviving on-disk file must exist"


# ---------------------------------------------------------------------------
# 2. WORM records survive even when they are the oldest
# ---------------------------------------------------------------------------


def test_worm_record_survives_eviction(tmp_path: Path) -> None:
    """Oldest record is WORM-tagged; it must not be evicted despite pressure.

    Uses the two-phase approach: insert without quota, set timestamps, then
    enforce quota explicitly.
    """
    quota = 2 * _PAYLOAD_SIZE  # 200 bytes; 3 records = 300 bytes stored

    # Phase 1: insert without quota.
    q_setup = Quarantine(tmp_path / "q.db", tmp_path / "store")
    sha_worm = _record(q_setup, seed=0, worm=True, seen_at="2024-01-01T00:00:00")
    sha_mid = _record(q_setup, seed=1, seen_at="2024-01-02T00:00:00")
    sha_new = _record(q_setup, seed=2, seen_at="2024-01-03T00:00:00")

    # Phase 2: enforce quota.
    q = Quarantine(tmp_path / "q.db", tmp_path / "store", max_bytes=quota)
    q.enforce_quota()

    rows = {r["sha256"]: r for r in q.list(limit=100)}

    # WORM record must be preserved.
    assert not rows[sha_worm]["evicted"], "WORM record must not be evicted"
    assert rows[sha_worm]["saved_path"] is not None
    assert Path(rows[sha_worm]["saved_path"]).exists()

    # At least one of the non-WORM records must have been evicted to relieve pressure.
    non_worm_evicted = [sha for sha in (sha_mid, sha_new) if rows[sha]["evicted"]]
    assert non_worm_evicted, "at least one non-WORM record should be evicted"

    # Total stored (non-evicted) bytes must be <= quota.
    stored = sum(r["bytes_size"] for r in rows.values() if not r["evicted"])
    assert stored <= quota


def test_mark_worm_prevents_eviction(tmp_path: Path) -> None:
    """mark_worm() called after record() prevents subsequent eviction.

    Phase 1: insert the old record without quota so it won't be auto-evicted
    before the WORM flag is set.  Then WORM-tag it, add a second record via a
    quota-bearing Quarantine, and verify the WORM record survives.
    """
    quota = 1 * _PAYLOAD_SIZE  # only one payload fits

    # Phase 1: insert old record without quota.
    q_setup = Quarantine(tmp_path / "q.db", tmp_path / "store")
    sha_old = _record(q_setup, seed=0, seen_at="2024-01-01T00:00:00")
    q_setup.mark_worm(sha_old)

    # Phase 2: add second record with quota active — WORM-old must survive.
    q = Quarantine(tmp_path / "q.db", tmp_path / "store", max_bytes=quota)
    _record(q, seed=1, seen_at="2024-01-02T00:00:00")

    rows = {r["sha256"]: r for r in q.list(limit=100)}
    assert not rows[sha_old]["evicted"], "WORM-marked old record must survive"
    assert rows[sha_old]["saved_path"] is not None


# ---------------------------------------------------------------------------
# 3. quota=None — no eviction, back-compat
# ---------------------------------------------------------------------------


def test_no_quota_never_evicts(tmp_path: Path) -> None:
    """When max_bytes=None, enforce_quota is a no-op regardless of stored size."""
    q = Quarantine(tmp_path / "q.db", tmp_path / "store")  # no max_bytes

    shas = [_record(q, seed=i) for i in range(10)]

    result = q.enforce_quota()
    assert result == 0, "enforce_quota() must return 0 when max_bytes is None"

    rows = {r["sha256"]: r for r in q.list(limit=100)}
    for sha in shas:
        assert not rows[sha]["evicted"], f"{sha} must not be evicted when no quota"
        assert rows[sha]["saved_path"] is not None


# ---------------------------------------------------------------------------
# 4. Idempotency — enforce_quota twice is safe
# ---------------------------------------------------------------------------


def test_enforce_quota_is_idempotent(tmp_path: Path) -> None:
    """Calling enforce_quota multiple times must not over-evict or crash."""
    quota = 2 * _PAYLOAD_SIZE

    # Phase 1: insert without quota.
    q_setup = Quarantine(tmp_path / "q.db", tmp_path / "store")
    for i in range(4):
        _record(q_setup, seed=i, seen_at=f"2024-01-0{i + 1}T00:00:00")

    # Phase 2: enforce.
    q = Quarantine(tmp_path / "q.db", tmp_path / "store", max_bytes=quota)
    q.enforce_quota()
    second = q.enforce_quota()

    assert second == 0, "second call must evict nothing more"

    rows = q.list(limit=100)
    stored = sum(r["bytes_size"] for r in rows if not r["evicted"])
    assert stored <= quota


# ---------------------------------------------------------------------------
# 5. existing DB upgrade — worm / evicted columns added in-place
# ---------------------------------------------------------------------------


def test_existing_db_upgraded_in_place(tmp_path: Path) -> None:
    """A DB created without worm/evicted columns is upgraded transparently."""
    db_path = tmp_path / "old.db"
    root = tmp_path / "store"

    # Create a DB using the old schema (no worm/evicted columns).
    import sqlite3 as _sqlite3

    old_schema = """
    CREATE TABLE IF NOT EXISTS quarantine (
        sha256 TEXT PRIMARY KEY,
        url TEXT,
        filename TEXT,
        content_type TEXT,
        verdict TEXT NOT NULL,
        reasons_json TEXT,
        bytes_size INTEGER NOT NULL,
        saved_path TEXT,
        seen_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """
    conn = _sqlite3.connect(str(db_path))
    conn.executescript(old_schema)
    conn.execute(
        "INSERT INTO quarantine (sha256, url, filename, content_type, verdict, "
        "reasons_json, bytes_size, saved_path, seen_at) VALUES "
        "('abc123', NULL, 'x.bin', NULL, 'admit', '[]', 50, NULL, '2024-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    # Opening with Quarantine must not crash and must add the missing columns.
    q = Quarantine(db_path, root)
    rows = q.list(limit=10)
    assert len(rows) == 1
    assert rows[0]["sha256"] == "abc123"
    assert rows[0]["worm"] is False
    assert rows[0]["evicted"] is False
