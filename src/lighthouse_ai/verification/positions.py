"""Position Registry — every claim + its WEP gets a row, then we score later.

Per design §22.4: every emitted high-confidence claim is recorded with a
WEP band; when the underlying question resolves, the position is scored
by Brier and the running calibration curve updated.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ..persistence import open_db
from .brier import brier_score
from .wep import band_for_probability, parse_band


@dataclass(frozen=True)
class Position:
    id: int
    claim: str
    wep_band: str
    confidence: float
    outcome: bool | None = None
    brier: float | None = None
    resolve_by: str | None = None
    resolution_criterion: str | None = None


_EXTRA_COLUMNS_SQL = """
ALTER TABLE positions ADD COLUMN outcome INTEGER;
ALTER TABLE positions ADD COLUMN brier REAL;
ALTER TABLE positions ADD COLUMN resolved_at TEXT;
ALTER TABLE positions ADD COLUMN resolve_by TEXT;
ALTER TABLE positions ADD COLUMN resolution_criterion TEXT;
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
        if "resolve_by" not in cols:
            statements.append("ALTER TABLE positions ADD COLUMN resolve_by TEXT")
        if "resolution_criterion" not in cols:
            statements.append("ALTER TABLE positions ADD COLUMN resolution_criterion TEXT")
        for s in statements:
            try:
                conn.execute(s)
            except sqlite3.OperationalError as exc:
                # First-run race: another thread (e.g. the resolver loop vs an
                # API request) added the same column between our PRAGMA read and
                # this ALTER. The column now exists — that's the desired state.
                if "duplicate column" not in str(exc).lower():
                    raise
    finally:
        conn.close()


def record_position(positions_db: Path, *, claim: str, probability: float,
                    band: str | None = None,
                    resolve_by: str | None = None,
                    resolution_criterion: str | None = None,
                    now: datetime | None = None) -> Position:
    """Record a high-confidence claim as a scoreable calibration position.

    ``resolve_by`` is the deadline at which the auto-resolver re-researches the
    claim (default: ``now`` + 90 days). ``resolution_criterion`` is an optional
    machine-checkable string describing what would make the claim TRUE/FALSE;
    the resolver hands it to its research function. ``now`` is injectable so the
    default deadline is deterministic in tests — ``datetime.now()`` is only ever
    called inside the function body, never at import.
    """
    _ensure_extras(positions_db)
    if resolve_by is None:
        base = now if now is not None else datetime.now()
        resolve_by = (base + timedelta(days=90)).isoformat()
    if band is None:
        wep = band_for_probability(probability)
    else:
        wep = parse_band(band)
    conn = open_db(positions_db)
    try:
        cur = conn.execute(
            "INSERT INTO positions (claim, wep_band, confidence, resolve_by, resolution_criterion) "
            "VALUES (?, ?, ?, ?, ?) RETURNING id",
            (claim, wep.name, probability, resolve_by, resolution_criterion),
        )
        rid = cur.fetchone()[0]
    finally:
        conn.close()
    return Position(id=rid, claim=claim, wep_band=wep.name, confidence=probability,
                    resolve_by=resolve_by, resolution_criterion=resolution_criterion)


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


def timeline(positions_db: Path, *, bucket: str = "week") -> list[dict]:
    """Calibration over time: resolved positions grouped into time buckets.

    Each bucket reports ``n``, ``mean_brier``, ``mean_probability`` and
    ``mean_outcome_rate`` so the dashboard can plot calibration drift. ``bucket``
    is ``day``, ``week`` (default) or ``month``; bucketing keys off
    ``resolved_at``. Buckets are returned in chronological order.
    """
    _ensure_extras(positions_db)
    fmt = {"day": "%Y-%m-%d", "month": "%Y-%m", "week": "%Y-%W"}.get(bucket, "%Y-%W")
    conn = open_db(positions_db)
    try:
        rows = conn.execute(
            f"SELECT strftime('{fmt}', resolved_at) AS b, "
            "COUNT(*), AVG(brier), AVG(confidence), AVG(outcome) "
            "FROM positions WHERE outcome IS NOT NULL AND resolved_at IS NOT NULL "
            "GROUP BY b ORDER BY b"
        ).fetchall()
    finally:
        conn.close()
    return [
        {"bucket": b, "n": int(n),
         "mean_brier": round(mb or 0.0, 4),
         "mean_probability": round(mp or 0.0, 4),
         "mean_outcome_rate": round(mo or 0.0, 4)}
        for b, n, mb, mp, mo in rows
    ]


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
