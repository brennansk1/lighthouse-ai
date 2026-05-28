"""Position Registry — every claim + its WEP gets a row, then we score later.

Per design §22.4: every emitted high-confidence claim is recorded with a
WEP band; when the underlying question resolves, the position is scored
by Brier and the running calibration curve updated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..persistence import open_db
from .brier import brier_score
from .wep import WEPBand, band_for_probability, parse_band


@dataclass(frozen=True)
class Position:
    id: int
    claim: str
    wep_band: str
    confidence: float
    outcome: bool | None = None
    brier: float | None = None


_EXTRA_COLUMNS_SQL = """
ALTER TABLE positions ADD COLUMN outcome INTEGER;
ALTER TABLE positions ADD COLUMN brier REAL;
ALTER TABLE positions ADD COLUMN resolved_at TEXT;
"""


def _ensure_extras(positions_db: Path) -> None:
    conn = open_db(positions_db)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(positions)")}
        statements = []
        if "outcome" not in cols:
            statements.append("ALTER TABLE positions ADD COLUMN outcome INTEGER")
        if "brier" not in cols:
            statements.append("ALTER TABLE positions ADD COLUMN brier REAL")
        if "resolved_at" not in cols:
            statements.append("ALTER TABLE positions ADD COLUMN resolved_at TEXT")
        for s in statements:
            conn.execute(s)
    finally:
        conn.close()


def record_position(positions_db: Path, *, claim: str, probability: float,
                    band: str | None = None) -> Position:
    _ensure_extras(positions_db)
    if band is None:
        wep = band_for_probability(probability)
    else:
        wep = parse_band(band)
    conn = open_db(positions_db)
    try:
        cur = conn.execute(
            "INSERT INTO positions (claim, wep_band, confidence) "
            "VALUES (?, ?, ?) RETURNING id", (claim, wep.name, probability),
        )
        rid = cur.fetchone()[0]
    finally:
        conn.close()
    return Position(id=rid, claim=claim, wep_band=wep.name, confidence=probability)


def resolve_position(positions_db: Path, position_id: int, outcome: bool) -> Position:
    _ensure_extras(positions_db)
    conn = open_db(positions_db)
    try:
        row = conn.execute(
            "SELECT id, claim, wep_band, confidence FROM positions WHERE id = ?",
            (position_id,),
        ).fetchone()
        if not row:
            raise KeyError(f"position {position_id} not found")
        prob = float(row[3])
        bs = brier_score(prob, outcome)
        conn.execute(
            "UPDATE positions SET outcome = ?, brier = ?, "
            "resolved_at = datetime('now') WHERE id = ?",
            (1 if outcome else 0, bs, position_id),
        )
    finally:
        conn.close()
    return Position(id=row[0], claim=row[1], wep_band=row[2], confidence=row[3],
                    outcome=outcome, brier=bs)


def score_all(positions_db: Path) -> dict[str, float]:
    """Aggregate calibration metrics across all resolved positions."""
    _ensure_extras(positions_db)
    conn = open_db(positions_db)
    try:
        rows = conn.execute(
            "SELECT confidence, outcome, brier FROM positions "
            "WHERE outcome IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return {"n": 0, "mean_brier": 0.0, "calibration_error": 0.0}
    n = len(rows)
    mean_brier = sum(b for _, _, b in rows) / n
    mean_prob = sum(p for p, _, _ in rows) / n
    mean_outcome = sum(o for _, o, _ in rows) / n
    return {
        "n": float(n),
        "mean_brier": mean_brier,
        "mean_probability": mean_prob,
        "mean_outcome_rate": mean_outcome,
        "calibration_error": abs(mean_prob - mean_outcome),
    }
