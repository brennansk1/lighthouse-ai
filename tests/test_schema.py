"""Unit tests for the migration runner and per-DB schemas."""

from __future__ import annotations

from pathlib import Path

import pytest

from lighthouse_ai.persistence import open_db
from lighthouse_ai.schema import (
    _MIGRATIONS_BY_DB,
    Migration,
    applied_migrations,
    apply_migrations,
    kinds_for,
    migrate_all,
    migrate_path,
)


def test_every_db_has_at_least_one_migration():
    for kind, migs in _MIGRATIONS_BY_DB.items():
        assert migs, f"{kind} has no migrations"


def test_migration_ids_are_unique_per_db():
    for kind, migs in _MIGRATIONS_BY_DB.items():
        ids = [m.id for m in migs]
        assert len(ids) == len(set(ids)), f"duplicate id in {kind}"


def test_migrate_path_creates_expected_tables(tmp_path: Path):
    db_path = tmp_path / "state.db"
    migrate_path(db_path, "state")
    conn = open_db(db_path)
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()
    assert "supervisor_state" in names
    assert "jobs" in names
    assert "schema_migrations" in names


def test_migrate_path_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "state.db"
    first = migrate_path(db_path, "state")
    second = migrate_path(db_path, "state")
    assert first[0] == "0001_initial"
    assert "0002_dashboard_surfaces" in first
    assert second == []  # nothing left to do


def test_migrate_all_runs_every_kind(migrated_paths):
    # Re-running yields no new migrations.
    again = migrate_all(kinds_for(migrated_paths))
    assert all(v == [] for v in again.values())


def test_unknown_kind_raises():
    with pytest.raises(KeyError):
        migrate_path(Path("/tmp/x"), "not-a-real-kind")


def test_supervisor_state_seeded(migrated_paths):
    conn = open_db(migrated_paths.state_db)
    try:
        row = conn.execute("SELECT id, status FROM supervisor_state").fetchone()
    finally:
        conn.close()
    assert row == (1, "running")


def test_intents_schema_has_status_check(migrated_paths):
    """The CHECK constraint on intents.status must reject bogus values."""
    conn = open_db(migrated_paths.intents_db)
    try:
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO intents (idempotency_key,target,op,payload_json,status) "
                "VALUES ('k','t','o','{}','bogus')"
            )
    finally:
        conn.close()


def test_apply_migrations_records_applied_ids(tmp_path: Path):
    db_path = tmp_path / "a.db"
    conn = open_db(db_path)
    try:
        apply_migrations(conn, [
            Migration("0001", "CREATE TABLE t (x);"),
            Migration("0002", "CREATE TABLE u (y);"),
        ])
        assert applied_migrations(conn) == {"0001", "0002"}
    finally:
        conn.close()


def test_new_migration_appended_runs_only_unseen(tmp_path: Path):
    db_path = tmp_path / "b.db"
    conn = open_db(db_path)
    try:
        apply_migrations(conn, [Migration("0001", "CREATE TABLE t (x);")])
        added = apply_migrations(conn, [
            Migration("0001", "CREATE TABLE t (x);"),  # already applied
            Migration("0002", "CREATE TABLE u (y);"),
        ])
        assert added == ["0002"]
    finally:
        conn.close()
