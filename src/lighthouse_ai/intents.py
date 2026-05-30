"""Outbox + saga: the durable intent log per design §25.

Public API:
    write_intent(...) -> int
        Insert a pending intent; returns row id.
    claim_one(target=None) -> Intent | None
        Atomically claim the oldest pending intent for an effector worker.
    mark_applied(intent_id)
        Mark a claimed intent as applied.
    mark_failed(intent_id, error, *, dead=False)
        Bump attempts; either re-queue or move to dead_intents.
    requeue_stuck(db_path, *, older_than_seconds=300)
        Reset orphaned ``in_flight`` intents (crashed mid-apply) back to
        ``pending`` so they are retried rather than silently lost.

Idempotency: every intent has a user-supplied ``idempotency_key`` enforced
UNIQUE by the schema. Repeated writes with the same key collapse to one row.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .persistence import open_db


@dataclass(frozen=True)
class Intent:
    id: int
    idempotency_key: str
    target: str
    op: str
    payload: dict[str, Any]
    status: str
    attempts: int
    job_id: str | None = None
    node_id: str | None = None
    write_id: str | None = None
    compensator: dict[str, Any] | None = None


def _row_to_intent(row: sqlite3.Row | tuple) -> Intent:
    (
        rid, key, target, op, payload, status, attempts,
        job_id, node_id, write_id, compensator,
    ) = row
    return Intent(
        id=rid, idempotency_key=key, target=target, op=op,
        payload=json.loads(payload) if payload else {},
        status=status, attempts=attempts,
        job_id=job_id, node_id=node_id, write_id=write_id,
        compensator=json.loads(compensator) if compensator else None,
    )


_SELECT_COLS = (
    "id, idempotency_key, target, op, payload_json, status, attempts, "
    "job_id, node_id, write_id, compensator_json"
)


def derive_idempotency_key(job_id: str, node_id: str, write_id: str) -> str:
    """Convention from §25.1: ``{job_id}:{node_id}:{write_id}``."""
    return f"{job_id}:{node_id}:{write_id}"


def derive_point_uuid(idempotency_key: str) -> str:
    """UUIDv5 derived from the idempotency key — used by Qdrant adapter (§25.3)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"lighthouse:intent:{idempotency_key}"))


def write_intent(
    db_path: Path,
    *,
    target: str,
    op: str,
    payload: dict[str, Any],
    idempotency_key: str,
    job_id: str | None = None,
    node_id: str | None = None,
    write_id: str | None = None,
    compensator: dict[str, Any] | None = None,
) -> int:
    """Insert a pending intent; on duplicate key, return the existing row id."""
    conn = open_db(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO intents (
                idempotency_key, target, op, payload_json,
                job_id, node_id, write_id, compensator_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(idempotency_key) DO NOTHING
            RETURNING id
            """,
            (idempotency_key, target, op, json.dumps(payload),
             job_id, node_id, write_id,
             json.dumps(compensator) if compensator else None),
        )
        row = cur.fetchone()
        if row:
            return int(row[0])
        # Existing row — fetch its id.
        row = conn.execute(
            "SELECT id FROM intents WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def claim_one(db_path: Path, target: str | None = None) -> Intent | None:
    """Atomically claim the oldest pending intent. Returns None if queue empty.

    Uses ``BEGIN IMMEDIATE`` to acquire the write lock before reading, so two
    concurrent effectors cannot claim the same row.
    """
    conn = open_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if target:
                row = conn.execute(
                    f"SELECT {_SELECT_COLS} FROM intents "
                    "WHERE status = 'pending' AND target = ? "
                    "ORDER BY id LIMIT 1", (target,),
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT {_SELECT_COLS} FROM intents "
                    "WHERE status = 'pending' ORDER BY id LIMIT 1"
                ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return None
            intent = _row_to_intent(row)
            conn.execute(
                "UPDATE intents SET status = 'in_flight', claimed_at = datetime('now'), "
                "attempts = attempts + 1 WHERE id = ?", (intent.id,),
            )
            conn.execute("COMMIT")
            # Return the post-update view: status flipped, attempts bumped.
            from dataclasses import replace
            return replace(intent, status="in_flight", attempts=intent.attempts + 1)
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def mark_applied(db_path: Path, intent_id: int) -> None:
    conn = open_db(db_path)
    try:
        conn.execute(
            "UPDATE intents SET status = 'applied', applied_at = datetime('now'), "
            "updated_at = datetime('now') WHERE id = ?", (intent_id,),
        )
    finally:
        conn.close()


def mark_failed(db_path: Path, intent_id: int, error: str, *, dead: bool = False) -> None:
    conn = open_db(db_path)
    try:
        if dead:
            # The dead-letter move (insert into dead_intents + flip status to
            # 'dead') must be ONE atomic transaction: a crash between the two
            # writes would otherwise leave the intent stuck in_flight while a
            # dead_intents row exists, and a later requeue+retry would create a
            # *duplicate* dead_intents row. We also guard against re-dead-
            # lettering an intent already marked 'dead'.
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT target, payload_json, status FROM intents WHERE id = ?",
                    (intent_id,),
                ).fetchone()
                if row and row[2] != "dead":
                    conn.execute(
                        "INSERT INTO dead_intents "
                        "(original_id, target, payload_json, last_error) "
                        "VALUES (?, ?, ?, ?)", (intent_id, row[0], row[1], error),
                    )
                conn.execute(
                    "UPDATE intents SET status = 'dead', last_error = ?, "
                    "last_attempt_at = datetime('now'), updated_at = datetime('now') "
                    "WHERE id = ?", (error, intent_id),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        else:
            conn.execute(
                "UPDATE intents SET status = 'pending', last_error = ?, "
                "last_attempt_at = datetime('now'), updated_at = datetime('now') "
                "WHERE id = ?", (error, intent_id),
            )
    finally:
        conn.close()


def requeue_stuck(db_path: Path, *, older_than_seconds: int = 300) -> int:
    """Reset orphaned ``in_flight`` intents back to ``pending``. Returns # reset.

    A crash (or a killed effector) between :func:`claim_one` marking an intent
    ``in_flight`` and the eventual :func:`mark_applied`/:func:`mark_failed`
    leaves the row stuck in ``in_flight`` forever: :func:`claim_one` only ever
    selects ``pending`` rows, so the side effect is neither applied nor
    dead-lettered. This is the standard outbox recovery step — run it at
    supervisor startup (before any effector starts) to reclaim such rows.

    Only intents whose ``claimed_at`` is older than ``older_than_seconds`` are
    reclaimed, so an intent a *live* effector is actively working is left
    alone. ``attempts`` is intentionally not decremented: a requeued intent
    has genuinely consumed an attempt, preserving the dead-letter bound.
    """
    conn = open_db(db_path)
    try:
        cur = conn.execute(
            "UPDATE intents SET status = 'pending', updated_at = datetime('now') "
            "WHERE status = 'in_flight' "
            "AND (claimed_at IS NULL "
            "     OR claimed_at <= datetime('now', ?))",
            (f"-{int(older_than_seconds)} seconds",),
        )
        return int(cur.rowcount)
    finally:
        conn.close()


def list_dead(db_path: Path) -> list[dict[str, Any]]:
    conn = open_db(db_path)
    try:
        rows = conn.execute(
            "SELECT id, original_id, target, payload_json, last_error, moved_at "
            "FROM dead_intents ORDER BY moved_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [
        {"id": r[0], "original_id": r[1], "target": r[2],
         "payload": json.loads(r[3]) if r[3] else {},
         "last_error": r[4], "moved_at": r[5]}
        for r in rows
    ]


def outbox_depth(db_path: Path) -> int:
    conn = open_db(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM intents WHERE status IN ('pending','in_flight')"
        ).fetchone()
    finally:
        conn.close()
    return int(row[0])


def intents_for_job(db_path: Path, job_id: str) -> list[Intent]:
    conn = open_db(db_path)
    try:
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM intents WHERE job_id = ? ORDER BY id",
            (job_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_intent(r) for r in rows]
