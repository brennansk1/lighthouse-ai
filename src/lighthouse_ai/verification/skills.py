"""Skills — small reusable procedures the curator auto-creates and the
researcher invokes (§23.2). Sprint 13 ships the storage; full skill execution
runtime arrives later. Lives in state.db under ``skills``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..persistence import open_db

_SKILLS_SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    body_json TEXT NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT
);
"""


@dataclass(frozen=True)
class Skill:
    id: int
    name: str
    description: str | None
    body: dict
    use_count: int


def _ensure(state_db: Path) -> None:
    conn = open_db(state_db)
    try:
        conn.executescript(_SKILLS_SCHEMA)
    finally:
        conn.close()


def add_skill(state_db: Path, *, name: str, description: str | None, body: dict) -> int:
    _ensure(state_db)
    conn = open_db(state_db)
    try:
        cur = conn.execute(
            "INSERT INTO skills (name, description, body_json) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET description=excluded.description, "
            "body_json=excluded.body_json RETURNING id",
            (name, description, json.dumps(body, sort_keys=True)),
        )
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def list_skills(state_db: Path) -> list[Skill]:
    _ensure(state_db)
    conn = open_db(state_db)
    try:
        rows = conn.execute(
            "SELECT id, name, description, body_json, use_count FROM skills "
            "ORDER BY use_count DESC, id"
        ).fetchall()
    finally:
        conn.close()
    return [
        Skill(id=r[0], name=r[1], description=r[2], body=json.loads(r[3]), use_count=r[4])
        for r in rows
    ]


def increment_use(state_db: Path, skill_id: int) -> None:
    _ensure(state_db)
    conn = open_db(state_db)
    try:
        conn.execute(
            "UPDATE skills SET use_count = use_count + 1, "
            "last_used_at = datetime('now') WHERE id = ?",
            (skill_id,),
        )
    finally:
        conn.close()
