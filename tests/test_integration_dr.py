"""Disaster recovery test: corrupt mid-write, recover from Litestream replica.

Litestream binary is not always installed in CI; when absent we still test
the equivalent property via SQLite ``.backup`` + WAL replay, which exercises
the same recovery primitive: open the live DB while writes are happening,
copy it, kill the writer, verify the copy is self-consistent.

If ``litestream`` is on PATH we additionally do an end-to-end round trip.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import threading
import time

import pytest

from lighthouse_ai.persistence import integrity_check, open_db
from lighthouse_ai.schema import kinds_for, migrate_all


@pytest.mark.integration
def test_sqlite_backup_under_write_load_yields_consistent_copy(tmp_paths):
    """Continuous writes + concurrent .backup → restored DB integrity ok."""
    migrate_all(kinds_for(tmp_paths))

    stop = threading.Event()
    writer_errors: list[Exception] = []

    def writer():
        try:
            conn = open_db(tmp_paths.audit_db)
            i = 0
            while not stop.is_set():
                conn.execute(
                    "INSERT INTO audit_events (actor, event_type, payload_json) "
                    "VALUES (?, 'tick', '{}')",
                    (f"w{i}",),
                )
                i += 1
                # Small sleep so we don't peg the CPU.
                time.sleep(0.001)
            conn.close()
        except Exception as exc:
            writer_errors.append(exc)

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    time.sleep(0.1)  # let some rows accrue

    backup_path = tmp_paths.replicas_dir / "audit-db.bak"
    src = open_db(tmp_paths.audit_db)
    dst = sqlite3.connect(str(backup_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    # Stop writer (simulates crash *after* the snapshot).
    stop.set()
    t.join(timeout=2)
    assert not writer_errors, writer_errors

    # Now: open the backup with Lighthouse PRAGMAs and verify integrity.
    recovered = open_db(backup_path)
    try:
        assert integrity_check(recovered) == "ok"
        # At least one event must have made it into the backup.
        n = recovered.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        assert n > 0
    finally:
        recovered.close()


@pytest.mark.integration
@pytest.mark.litestream
def test_litestream_end_to_end_round_trip(tmp_paths):
    if not shutil.which("litestream"):
        pytest.skip("litestream binary not on PATH")

    migrate_all(kinds_for(tmp_paths))

    # Seed some data.
    conn = open_db(tmp_paths.audit_db)
    try:
        for i in range(10):
            conn.execute(
                "INSERT INTO audit_events (actor, event_type, payload_json) "
                "VALUES (?, 'seed', '{}')",
                (f"s{i}",),
            )
    finally:
        conn.close()

    # Render config and run `litestream replicate` briefly.
    from lighthouse_ai.litestream import write_litestream_config

    cfg = write_litestream_config(tmp_paths)
    proc = subprocess.Popen(
        ["litestream", "replicate", "-config", str(cfg)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(3)  # let it take an initial snapshot
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    # Restore into a fresh path.
    target = tmp_paths.data_dir / "audit.restored.db"
    if target.exists():
        target.unlink()
    # -config is required: without it litestream looks for /etc/litestream.yml
    # (found live on litestream 0.5.12 — the no-config form errors out).
    subprocess.run(
        ["litestream", "restore", "-config", str(cfg), "-o", str(target), str(tmp_paths.audit_db)],
        check=True,
        capture_output=True,
    )
    assert target.exists()
    conn = open_db(target)
    try:
        assert integrity_check(conn) == "ok"
        n = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        assert n >= 10
    finally:
        conn.close()


@pytest.mark.integration
def test_wal_persists_across_reopen(tmp_paths):
    """Confirms WAL durability — write, close without checkpoint, reopen, read."""
    migrate_all(kinds_for(tmp_paths))
    conn = open_db(tmp_paths.state_db)
    try:
        conn.execute("INSERT INTO jobs (id, mode, status) VALUES ('j1','mon','queued')")
    finally:
        conn.close()
    # Reopen — value must still be there.
    conn = open_db(tmp_paths.state_db)
    try:
        row = conn.execute("SELECT status FROM jobs WHERE id='j1'").fetchone()
    finally:
        conn.close()
    assert row == ("queued",)
