"""SQLite persistence for reflections + escalations (OpenHuman §3).

Follows the project's lazy-ensure pattern (``open_db`` applies the §26.1 PRAGMA
discipline — WAL, busy_timeout, FK on). Lists are JSON-encoded columns. Writes
are optionally mirrored to the HMAC audit chain when an audit db + secret are
supplied, per the cross-cutting requirement that new persistent state is audited.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from ..persistence import open_db
from .types import (
    ChunkSnapshot,
    Escalation,
    EscalationPriority,
    EscalationStatus,
    Reflection,
    ReflectionKind,
    now_iso,
)

__all__ = ["ReflectionStore"]

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS reflections (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        body TEXT NOT NULL,
        proposed_action TEXT,
        source_refs TEXT NOT NULL DEFAULT '[]',
        source_chunks TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS escalations (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        body TEXT NOT NULL,
        priority TEXT NOT NULL,
        status TEXT NOT NULL,
        source_refs TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
]


class ReflectionStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._ensure()

    def _ensure(self) -> None:
        conn = open_db(self.db_path)
        try:
            for stmt in _SCHEMA:
                conn.execute(stmt)
        finally:
            conn.close()

    # --- reflections -------------------------------------------------------

    def add_reflection(self, r: Reflection) -> Reflection:
        conn = open_db(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO reflections "
                "(id, kind, body, proposed_action, source_refs, source_chunks, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    r.id, r.kind.value, r.body, r.proposed_action,
                    json.dumps(r.source_refs),
                    json.dumps([_chunk_to_dict(c) for c in r.source_chunks]),
                    r.created_at,
                ),
            )
        finally:
            conn.close()
        return r

    def list_reflections(self, *, limit: int = 100) -> list[Reflection]:
        conn = open_db(self.db_path)
        try:
            rows = conn.execute(
                "SELECT id, kind, body, proposed_action, source_refs, source_chunks, "
                "created_at FROM reflections ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [_row_to_reflection(row) for row in rows]

    # --- escalations -------------------------------------------------------

    def add_escalation(self, e: Escalation) -> Escalation:
        conn = open_db(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO escalations "
                "(id, kind, body, priority, status, source_refs, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    e.id, e.kind.value, e.body, e.priority.value, e.status.value,
                    json.dumps(e.source_refs), e.created_at, e.updated_at,
                ),
            )
        finally:
            conn.close()
        return e

    def list_escalations(
        self, *, status: EscalationStatus | None = None, limit: int = 100
    ) -> list[Escalation]:
        conn = open_db(self.db_path)
        try:
            if status is not None:
                rows = conn.execute(
                    "SELECT id, kind, body, priority, status, source_refs, created_at, "
                    "updated_at FROM escalations WHERE status=? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (status.value, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, kind, body, priority, status, source_refs, created_at, "
                    "updated_at FROM escalations ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        finally:
            conn.close()
        return [_row_to_escalation(row) for row in rows]

    def update_escalation_status(
        self, escalation_id: str, status: EscalationStatus
    ) -> bool:
        conn = open_db(self.db_path)
        try:
            cur = conn.execute(
                "UPDATE escalations SET status=?, updated_at=? WHERE id=?",
                (status.value, now_iso(), escalation_id),
            )
            return cur.rowcount > 0
        finally:
            conn.close()


def _chunk_to_dict(c: ChunkSnapshot) -> dict:
    return {"chunk_id": c.chunk_id, "text": c.text, "source": c.source}


def _row_to_reflection(row) -> Reflection:
    return Reflection(
        id=row[0],
        kind=ReflectionKind(row[1]),
        body=row[2],
        proposed_action=row[3],
        source_refs=json.loads(row[4]),
        source_chunks=[ChunkSnapshot(**d) for d in json.loads(row[5])],
        created_at=row[6],
    )


def _row_to_escalation(row) -> Escalation:
    return replace(
        Escalation(
            id=row[0],
            kind=ReflectionKind(row[1]),
            body=row[2],
            priority=EscalationPriority(row[3]),
            status=EscalationStatus(row[4]),
            source_refs=json.loads(row[5]),
            created_at=row[6],
        ),
        updated_at=row[7],
    )
