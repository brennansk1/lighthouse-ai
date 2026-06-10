"""Persistence for Ask (QUC) sessions — the transcript artifact.

An Ask session is a conversation: a list of turns, each a role + text +
citations. This module serializes a ``QUCSession`` into the ``ask_sessions``
table (one row, ``turns_json`` holding the turn list) and reads it back, so a
conversation survives across requests and shows up in the Library as a
transcript artifact.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..persistence import open_db
from .quc import QUCSession, Turn


def _turns_to_json(session: QUCSession) -> str:
    # Every Turn field round-trips: dropping the Zone S additions
    # (skill_ids_used, adjudicate_flag) here silently erased the skill audit
    # trail on save/load. The loader tolerates their absence in old rows.
    return json.dumps([
        {"role": t.role, "text": t.text, "citations": list(t.citations),
         "skill_ids_used": list(t.skill_ids_used),
         "adjudicate_flag": t.adjudicate_flag}
        for t in session.history
    ])


def _turns_from_json(raw: str | None) -> list[Turn]:
    if not raw:
        return []
    out: list[Turn] = []
    for d in json.loads(raw):
        out.append(Turn(role=d.get("role", "user"), text=d.get("text", ""),
                        citations=list(d.get("citations", [])),
                        skill_ids_used=list(d.get("skill_ids_used", [])),
                        adjudicate_flag=bool(d.get("adjudicate_flag", False))))
    return out


def save_session(state_db, session: QUCSession, *, job_id: str | None = None,
                 title: str | None = None) -> str:
    """Upsert a session row, returning its id. Generates an id when absent."""
    sid = session.id or ("a-" + uuid.uuid4().hex[:6])
    turns_json = _turns_to_json(session)
    conn = open_db(state_db)
    try:
        existing = conn.execute(
            "SELECT id FROM ask_sessions WHERE id=?", (sid,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE ask_sessions SET turns_json=?, title=COALESCE(?, title), "
                "topic=COALESCE(?, topic), updated_at=datetime('now') WHERE id=?",
                (turns_json, title, session.topic, sid))
        else:
            conn.execute(
                "INSERT INTO ask_sessions (id, job_id, topic, title, turns_json, "
                "status) VALUES (?, ?, ?, ?, ?, 'open')",
                (sid, job_id, session.topic, title or session.topic or "Ask",
                 turns_json))
    finally:
        conn.close()
    return sid


def load_session(state_db, session_id: str) -> QUCSession | None:
    conn = open_db(state_db)
    try:
        row = conn.execute(
            "SELECT id, topic, turns_json FROM ask_sessions WHERE id=?",
            (session_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    session = QUCSession(id=row[0], topic=row[1])
    session.history.extend(_turns_from_json(row[2]))
    return session


def list_sessions(state_db, *, status: str | None = None) -> list[dict[str, Any]]:
    conn = open_db(state_db)
    try:
        if status:
            rows = conn.execute(
                "SELECT id, job_id, topic, title, status, created_at, updated_at, "
                "turns_json FROM ask_sessions WHERE status=? "
                "ORDER BY updated_at DESC", (status,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, job_id, topic, title, status, created_at, updated_at, "
                "turns_json FROM ask_sessions ORDER BY updated_at DESC").fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        turns = _turns_from_json(r[7])
        out.append({
            "id": r[0], "job_id": r[1], "topic": r[2], "title": r[3],
            "status": r[4], "created_at": r[5], "updated_at": r[6],
            "turn_count": len(turns),
        })
    return out


def get_session_dict(state_db, session_id: str) -> dict[str, Any] | None:
    """Full session including turns, for the transcript viewer."""
    conn = open_db(state_db)
    try:
        row = conn.execute(
            "SELECT id, job_id, topic, title, status, created_at, updated_at, "
            "turns_json FROM ask_sessions WHERE id=?", (session_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    turns = _turns_from_json(row[7])
    return {
        "id": row[0], "job_id": row[1], "topic": row[2], "title": row[3],
        "status": row[4], "created_at": row[5], "updated_at": row[6],
        "turns": [{"role": t.role, "text": t.text, "citations": t.citations,
                   "skill_ids_used": t.skill_ids_used,
                   "adjudicate_flag": t.adjudicate_flag}
                  for t in turns],
    }


def promote_turn(state_db, session_id: str, turn_index: int) -> str:
    """Promote one assistant turn into a standalone draft (transcript artifact).

    Returns the new draft id. Raises ``KeyError`` if the session or turn is
    missing.
    """
    session = load_session(state_db, session_id)
    if session is None or turn_index < 0 or turn_index >= len(session.history):
        raise KeyError(f"no turn {turn_index} in session {session_id}")
    turn = session.history[turn_index]
    draft_id = "d-" + uuid.uuid4().hex[:6]
    title = (session.topic or "Ask") + f" — turn {turn_index}"
    body_html = f"<p>{turn.text}</p>"
    body_json = json.dumps({"role": turn.role, "text": turn.text,
                            "citations": list(turn.citations)})
    conn = open_db(state_db)
    try:
        conn.execute(
            "INSERT INTO drafts (id, job_id, topic, title, body_html, body_json, "
            "artifact_type, source_count, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'transcript', ?, 'staged')",
            (draft_id, None, title[:60], title, body_html, body_json,
             len(turn.citations)))
    finally:
        conn.close()
    return draft_id
