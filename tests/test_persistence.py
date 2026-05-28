"""Unit tests for lighthouse_ai.persistence — covers §26.1 PRAGMA enforcement."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lighthouse_ai.persistence import (
    DEFAULTS,
    PragmaAssertionError,
    PragmaSpec,
    apply_pragmas,
    assert_pragmas,
    db,
    integrity_check,
    open_db,
    read_pragmas,
)


def test_defaults_match_design_spec():
    """The PRAGMA defaults must literally match design §26.1."""
    assert DEFAULTS.journal_mode == "wal"
    assert DEFAULTS.busy_timeout_ms == 5000
    assert DEFAULTS.synchronous == "normal"
    assert DEFAULTS.foreign_keys is True
    assert DEFAULTS.cache_size_pages == -64000
    assert DEFAULTS.temp_store == "memory"
    assert DEFAULTS.wal_autocheckpoint == 1000


def test_open_db_applies_all_pragmas(tmp_path: Path):
    p = tmp_path / "x.db"
    conn = open_db(p)
    try:
        got = read_pragmas(conn)
    finally:
        conn.close()
    assert got["journal_mode"] == "wal"
    assert got["busy_timeout"] == 5000
    assert got["synchronous"] == "normal"
    assert got["foreign_keys"] is True
    assert got["cache_size"] == -64000
    assert got["temp_store"] == "memory"
    assert got["wal_autocheckpoint"] == 1000


def test_open_db_creates_parent_directory(tmp_path: Path):
    p = tmp_path / "nested" / "deep" / "x.db"
    conn = open_db(p)
    conn.close()
    assert p.exists()


def test_open_db_returns_durable_connection(tmp_path: Path):
    """Writing then reopening preserves data — basic durability sanity."""
    p = tmp_path / "d.db"
    with db(p) as c:
        c.execute("CREATE TABLE t (x INTEGER)")
        c.execute("INSERT INTO t VALUES (42)")
    with db(p) as c:
        assert c.execute("SELECT x FROM t").fetchone() == (42,)


def test_context_manager_closes_connection(tmp_path: Path):
    p = tmp_path / "ctx.db"
    with db(p) as c:
        c.execute("CREATE TABLE t (x)")
    with pytest.raises(sqlite3.ProgrammingError):
        c.execute("SELECT 1")


def test_integrity_check_returns_ok(tmp_path: Path):
    p = tmp_path / "ok.db"
    with db(p) as c:
        c.execute("CREATE TABLE t (x)")
        c.execute("INSERT INTO t VALUES (1)")
        assert integrity_check(c) == "ok"


def test_memory_db_tolerated_for_journal_mode():
    """:memory: cannot use WAL; assert_pragmas must not complain about this."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    apply_pragmas(conn)
    # WAL is rejected for memory DBs, but assert_pragmas should pass.
    assert_pragmas(conn)
    conn.close()


def test_assert_pragmas_raises_on_real_mismatch(tmp_path: Path):
    p = tmp_path / "m.db"
    conn = open_db(p)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        with pytest.raises(PragmaAssertionError):
            assert_pragmas(conn)
    finally:
        conn.close()


def test_apply_pragmas_idempotent(tmp_path: Path):
    p = tmp_path / "i.db"
    conn = open_db(p)
    try:
        before = read_pragmas(conn)
        apply_pragmas(conn)
        after = read_pragmas(conn)
        assert before == after
    finally:
        conn.close()


def test_open_db_with_custom_spec_writes_values(tmp_path: Path):
    p = tmp_path / "c.db"
    spec = PragmaSpec(
        journal_mode="wal", busy_timeout_ms=10000, synchronous="normal",
        foreign_keys=True, cache_size_pages=-32000, temp_store="memory",
        wal_autocheckpoint=500,
    )
    conn = open_db(p, spec=spec)
    try:
        got = read_pragmas(conn)
    finally:
        conn.close()
    assert got["busy_timeout"] == 10000
    assert got["cache_size"] == -32000
    assert got["wal_autocheckpoint"] == 500


def test_read_pragmas_uses_normalized_names(tmp_path: Path):
    p = tmp_path / "n.db"
    with db(p) as c:
        got = read_pragmas(c)
    assert got["synchronous"] in {"off", "normal", "full", "extra"}
    assert got["temp_store"] in {"default", "file", "memory"}
