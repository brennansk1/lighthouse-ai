"""Hypothesis tracking — minimal CRUD on the existing hypotheses table."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..persistence import open_db


@dataclass(frozen=True)
class Hypothesis:
    id: int
    statement: str
    status: str
    created_at: str


def add_hypothesis(db: Path, statement: str) -> int:
    conn = open_db(db)
    try:
        cur = conn.execute(
            "INSERT INTO hypotheses (statement) VALUES (?) RETURNING id",
            (statement,),
        )
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def update_hypothesis(db: Path, hid: int, status: str) -> None:
    if status not in {"open", "supported", "refuted", "retired"}:
        raise ValueError(f"bad status: {status!r}")
    conn = open_db(db)
    try:
        conn.execute("UPDATE hypotheses SET status = ? WHERE id = ?", (status, hid))
    finally:
        conn.close()


def list_hypotheses(db: Path, *, status: str | None = None) -> list[Hypothesis]:
    conn = open_db(db)
    try:
        if status:
            rows = conn.execute(
                "SELECT id, statement, status, created_at FROM hypotheses "
                "WHERE status = ? ORDER BY id",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, statement, status, created_at FROM hypotheses ORDER BY id"
            ).fetchall()
    finally:
        conn.close()
    return [Hypothesis(*r) for r in rows]
