"""Tests for logseq_sync — pending_count, sync_drafts, _ensure_synced_col."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lighthouse_ai.compounding.logseq_sync import (
    SyncResult,
    _ensure_synced_col,
    pending_count,
    sync_drafts,
)
from lighthouse_ai.paths import Paths, make_paths
from lighthouse_ai.persistence import open_db
from lighthouse_ai.schema import kinds_for, migrate_all


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_paths(tmp_path: Path) -> Paths:
    paths = make_paths(tmp_path / "data", tmp_path / "replicas")
    paths.ensure()
    migrate_all(kinds_for(paths))
    return paths


def _insert_draft(
    paths: Paths,
    draft_id: str,
    status: str = "published",
    *,
    title: str = "Test Title",
    body_html: str = "<p>Hello world</p>",
    topic: str = "test-topic",
) -> None:
    conn = open_db(paths.state_db)
    try:
        conn.execute(
            "INSERT INTO drafts (id, job_id, topic, title, body_html, status) "
            "VALUES (?, NULL, ?, ?, ?, ?)",
            (draft_id, topic, title, body_html, status),
        )
    finally:
        conn.close()


def _get_synced_at(paths: Paths, draft_id: str) -> str | None:
    conn = open_db(paths.state_db)
    try:
        row = conn.execute(
            "SELECT logseq_synced_at FROM drafts WHERE id=?", (draft_id,)
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Tests: pending_count
# ---------------------------------------------------------------------------

def test_pending_count_no_published_drafts(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    assert pending_count(paths) == 0


def test_pending_count_staged_draft_not_counted(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    _insert_draft(paths, "staged-1", status="staged")
    assert pending_count(paths) == 0


def test_pending_count_published_unsynced(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    _insert_draft(paths, "pub-1", status="published")
    _insert_draft(paths, "pub-2", status="published")
    assert pending_count(paths) == 2


def test_pending_count_already_synced_not_counted(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    _insert_draft(paths, "pub-1", status="published")
    # Mark it as synced
    conn = open_db(paths.state_db)
    try:
        _ensure_synced_col(conn)
        conn.execute(
            "UPDATE drafts SET logseq_synced_at=datetime('now') WHERE id=?",
            ("pub-1",),
        )
    finally:
        conn.close()
    assert pending_count(paths) == 0


# ---------------------------------------------------------------------------
# Tests: sync_drafts
# ---------------------------------------------------------------------------

EXPORT_PATH = "lighthouse_ai.compounding.logseq_sync.export_draft"


def test_sync_drafts_exports_published_draft_and_marks_synced(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    _insert_draft(paths, "d1", status="published", title="Hello Draft")

    mock_page = MagicMock()
    with patch(EXPORT_PATH, return_value=mock_page) as mock_export:
        result = sync_drafts(paths, graph_dir)

    assert result.synced == 1
    assert result.failed == 0
    assert result.errors == []
    mock_export.assert_called_once()
    call_kwargs = mock_export.call_args
    assert call_kwargs.args[0] == graph_dir
    assert call_kwargs.kwargs["draft_id"] == "d1"
    assert call_kwargs.kwargs["title"] == "Hello Draft"

    # logseq_synced_at must be set
    assert _get_synced_at(paths, "d1") is not None


def test_sync_drafts_skips_already_synced_by_default(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    _insert_draft(paths, "d1", status="published")

    # Pre-mark as synced
    conn = open_db(paths.state_db)
    try:
        _ensure_synced_col(conn)
        conn.execute(
            "UPDATE drafts SET logseq_synced_at=datetime('now') WHERE id=?", ("d1",)
        )
    finally:
        conn.close()

    with patch(EXPORT_PATH) as mock_export:
        result = sync_drafts(paths, graph_dir, force=False)

    assert result.synced == 0
    mock_export.assert_not_called()


def test_sync_drafts_force_re_exports_already_synced(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    _insert_draft(paths, "d1", status="published")

    # Pre-mark as synced
    conn = open_db(paths.state_db)
    try:
        _ensure_synced_col(conn)
        conn.execute(
            "UPDATE drafts SET logseq_synced_at=datetime('now') WHERE id=?", ("d1",)
        )
    finally:
        conn.close()

    mock_page = MagicMock()
    with patch(EXPORT_PATH, return_value=mock_page) as mock_export:
        result = sync_drafts(paths, graph_dir, force=True)

    assert result.synced == 1
    mock_export.assert_called_once()


def test_sync_drafts_no_published_drafts_returns_zero(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()

    with patch(EXPORT_PATH) as mock_export:
        result = sync_drafts(paths, graph_dir)

    assert result.synced == 0
    assert result.failed == 0
    mock_export.assert_not_called()


def test_sync_drafts_failed_export_recorded_in_errors(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    _insert_draft(paths, "d1", status="published")

    with patch(EXPORT_PATH, side_effect=OSError("disk full")):
        result = sync_drafts(paths, graph_dir)

    assert result.synced == 0
    assert result.failed == 1
    assert len(result.errors) == 1
    assert result.errors[0][0] == "d1"
    assert "disk full" in result.errors[0][1]

    # draft must remain unsynced
    assert _get_synced_at(paths, "d1") is None


def test_sync_drafts_partial_failure(tmp_path: Path) -> None:
    """One draft succeeds, one fails — counts are independent."""
    paths = _make_paths(tmp_path)
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    _insert_draft(paths, "good", status="published", title="Good")
    _insert_draft(paths, "bad", status="published", title="Bad")

    mock_page = MagicMock()

    def _side_effect(gdir, *, draft_id, **kw):
        if draft_id == "bad":
            raise RuntimeError("boom")
        return mock_page

    with patch(EXPORT_PATH, side_effect=_side_effect):
        result = sync_drafts(paths, graph_dir)

    assert result.synced == 1
    assert result.failed == 1
    assert len(result.errors) == 1


# ---------------------------------------------------------------------------
# Tests: _ensure_synced_col idempotency
# ---------------------------------------------------------------------------

def test_ensure_synced_col_idempotent(tmp_path: Path) -> None:
    """Calling _ensure_synced_col twice must not raise."""
    paths = _make_paths(tmp_path)
    conn = open_db(paths.state_db)
    try:
        _ensure_synced_col(conn)
        _ensure_synced_col(conn)  # second call — must be a no-op
        cols = {row[1] for row in conn.execute("PRAGMA table_info(drafts)")}
        assert "logseq_synced_at" in cols
    finally:
        conn.close()
