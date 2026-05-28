"""Logseq daily sync — export all published drafts to the Logseq graph dir.

Tracks which drafts have been synced via a ``logseq_synced_at`` column added
to the drafts table on first use. Re-export can be forced with ``force=True``.
"""
from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from pathlib import Path

from ..paths import Paths
from ..persistence import open_db
from ..targets.logseq import export_draft

log = structlog.get_logger(__name__)

__all__ = ["SyncResult", "sync_drafts", "pending_count"]


@dataclass
class SyncResult:
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def _ensure_synced_col(conn) -> None:
    """Add logseq_synced_at column to drafts table if absent."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(drafts)")}
    if "logseq_synced_at" not in cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN logseq_synced_at TEXT")


def pending_count(paths: Paths) -> int:
    """Return number of published drafts not yet synced to Logseq."""
    conn = open_db(paths.state_db)
    try:
        _ensure_synced_col(conn)
        return conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE status='published' AND logseq_synced_at IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()


def sync_drafts(paths: Paths, graph_dir: Path, *, force: bool = False) -> SyncResult:
    """Export published drafts to Logseq.

    When ``force=False`` (default) only drafts with no ``logseq_synced_at``
    are exported. When ``force=True`` all published drafts are re-exported.
    """
    result = SyncResult()
    conn = open_db(paths.state_db)
    try:
        _ensure_synced_col(conn)
        if force:
            rows = conn.execute(
                "SELECT id, title, body_html, topic, wep_phrase, source_count "
                "FROM drafts WHERE status='published'"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, body_html, topic, wep_phrase, source_count "
                "FROM drafts WHERE status='published' AND logseq_synced_at IS NULL"
            ).fetchall()
    finally:
        conn.close()

    if not rows:
        return result

    for draft_id, title, body_html, topic, wep_phrase, source_count in rows:
        try:
            export_draft(
                graph_dir,
                draft_id=draft_id,
                title=title or draft_id,
                body_html=body_html or "",
                topic=topic or "",
                wep_phrase=wep_phrase,
                source_count=source_count or 0,
            )
            # Mark as synced
            conn2 = open_db(paths.state_db)
            try:
                conn2.execute(
                    "UPDATE drafts SET logseq_synced_at=datetime('now') WHERE id=?",
                    (draft_id,),
                )
            finally:
                conn2.close()
            result.synced += 1
            log.info("logseq_sync.exported", draft_id=draft_id, title=title)
        except Exception as exc:
            result.failed += 1
            result.errors.append((draft_id, str(exc)))
            log.warning("logseq_sync.failed", draft_id=draft_id, error=str(exc))

    result.skipped = 0  # force=False already filters; nothing truly "skipped"
    return result
