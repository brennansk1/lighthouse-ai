"""Skills — reusable research strategies the agent distils from its own
successful runs and applies to future questions (§23.2, self-learning loop).

Sprint 13 shipped the storage; the self-learning loop (distil → store →
retrieve → apply → reinforce → prune) builds on it. A *skill* is a small,
versioned JSON ``body`` describing a research strategy that worked — the
question type it suits, trigger keywords, a decomposition template, evidence
domains, retrieval hints, and the quality it achieved. Skills only shape
*planning prompts* (read-only influence); they never take actions.

Lives in state.db under ``skills`` (+ ``skill_applications`` for per-use
provenance and reinforcement). Effectiveness is tracked so good strategies are
reinforced and poor ones archived (never hard-deleted — auditability)."""

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
    question_type TEXT NOT NULL DEFAULT '',
    applied_count INTEGER NOT NULL DEFAULT 0,
    win_count INTEGER NOT NULL DEFAULT 0,
    avg_coverage REAL NOT NULL DEFAULT 0.0,
    score REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,
    last_applied_at TEXT
);
CREATE TABLE IF NOT EXISTS skill_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id INTEGER NOT NULL,
    job_id TEXT,
    applied_at TEXT NOT NULL DEFAULT (datetime('now')),
    outcome_coverage REAL,
    outcome_passed INTEGER,
    completed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_skill_apps_skill ON skill_applications (skill_id);
CREATE INDEX IF NOT EXISTS idx_skills_status ON skills (status, score);
"""

# Columns added after the original 7-column table shipped; each is added
# idempotently for pre-existing databases (mirrors the logseq_synced_at pattern).
_ADDED_COLUMNS = {
    "question_type": "TEXT NOT NULL DEFAULT ''",
    "applied_count": "INTEGER NOT NULL DEFAULT 0",
    "win_count": "INTEGER NOT NULL DEFAULT 0",
    "avg_coverage": "REAL NOT NULL DEFAULT 0.0",
    "score": "REAL NOT NULL DEFAULT 0.0",
    "status": "TEXT NOT NULL DEFAULT 'active'",
    "last_applied_at": "TEXT",
}

# Skill body schema version — bump if the body shape changes incompatibly.
BODY_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Skill:
    id: int
    name: str
    description: str | None
    body: dict
    use_count: int
    question_type: str = ""
    applied_count: int = 0
    win_count: int = 0
    avg_coverage: float = 0.0
    score: float = 0.0
    status: str = "active"
    last_applied_at: str | None = None

    @property
    def win_rate(self) -> float:
        return self.win_count / self.applied_count if self.applied_count else 0.0

    @property
    def decomposition(self) -> list[str]:
        d = self.body.get("decomposition")
        return list(d) if isinstance(d, list) else []

    @property
    def trigger_keywords(self) -> list[str]:
        kw = self.body.get("trigger_keywords")
        return [str(k).lower() for k in kw] if isinstance(kw, list) else []


def compute_score(applied_count: int, win_count: int, avg_coverage: float) -> float:
    """Effectiveness score in [0, 1] from observed outcomes.

    Blends win-rate (did applying the skill yield a passing, well-sourced run?)
    with average citation coverage, scaled by a confidence factor that ramps up
    with the number of trials so a single lucky/unlucky run doesn't dominate.
    Deterministic (no clock) so it's testable; recency is applied separately at
    retrieval time. Returns 0.0 for never-applied skills — callers seed an
    initial score from the distilled quality instead.
    """
    if applied_count <= 0:
        return 0.0
    win_rate = win_count / applied_count
    confidence = min(applied_count / 5.0, 1.0)
    base = 0.6 * win_rate + 0.4 * max(0.0, min(avg_coverage, 1.0))
    return round(base * (0.5 + 0.5 * confidence), 4)


def _ensure(state_db: Path) -> None:
    conn = open_db(state_db)
    try:
        conn.executescript(_SKILLS_SCHEMA)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(skills)")}
        for name, decl in _ADDED_COLUMNS.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE skills ADD COLUMN {name} {decl}")
    finally:
        conn.close()


def _row_to_skill(r: tuple) -> Skill:
    return Skill(
        id=r[0], name=r[1], description=r[2], body=json.loads(r[3]),
        use_count=r[4], question_type=r[5] or "", applied_count=r[6] or 0,
        win_count=r[7] or 0, avg_coverage=r[8] or 0.0, score=r[9] or 0.0,
        status=r[10] or "active", last_applied_at=r[11],
    )


_SELECT = (
    "SELECT id, name, description, body_json, use_count, question_type, "
    "applied_count, win_count, avg_coverage, score, status, last_applied_at "
    "FROM skills"
)


def add_skill(state_db: Path, *, name: str, description: str | None,
              body: dict, question_type: str = "", score: float = 0.0,
              status: str = "active") -> int:
    """Insert or update a skill by unique name. Returns its id.

    ``score`` lets a freshly distilled skill start with an optimistic prior
    (e.g. the run's citation coverage) so it gets a fair chance to be tried
    before any reinforcement data exists.
    """
    _ensure(state_db)
    conn = open_db(state_db)
    try:
        cur = conn.execute(
            "INSERT INTO skills (name, description, body_json, question_type, "
            "score, status) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET description=excluded.description, "
            "body_json=excluded.body_json, question_type=excluded.question_type, "
            "score=excluded.score, status=excluded.status RETURNING id",
            (name, description, json.dumps(body, sort_keys=True),
             question_type, score, status),
        )
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def list_skills(state_db: Path, *, status: str | None = None) -> list[Skill]:
    _ensure(state_db)
    conn = open_db(state_db)
    try:
        if status:
            rows = conn.execute(
                _SELECT + " WHERE status = ? ORDER BY score DESC, use_count DESC, id",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                _SELECT + " ORDER BY score DESC, use_count DESC, id"
            ).fetchall()
    finally:
        conn.close()
    return [_row_to_skill(r) for r in rows]


def get_skill(state_db: Path, skill_id: int) -> Skill | None:
    _ensure(state_db)
    conn = open_db(state_db)
    try:
        row = conn.execute(_SELECT + " WHERE id = ?", (skill_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_skill(row) if row else None


def increment_use(state_db: Path, skill_id: int) -> None:
    _ensure(state_db)
    conn = open_db(state_db)
    try:
        conn.execute(
            "UPDATE skills SET use_count = use_count + 1, "
            "last_used_at = datetime('now') WHERE id = ?", (skill_id,),
        )
    finally:
        conn.close()


# --- self-learning: retrieval, application tracking, reinforcement, pruning ---


def _overlap(a: list[str], b: list[str]) -> float:
    """Jaccard overlap of two keyword lists (0..1)."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def relevant_skills(state_db: Path, *, question_type: str,
                    keywords: list[str], k: int = 3,
                    status: str = "active") -> list[Skill]:
    """Return up to ``k`` active skills most relevant to a question.

    Ranks by: exact question-type match (strong), trigger-keyword overlap, and
    effectiveness score, with recency as the final tiebreaker. Freshly distilled
    skills (score seeded from their distilled quality) can surface before any
    reinforcement data exists, so the loop can actually try what it learned.
    """
    kws = [w.lower() for w in keywords]
    candidates = list_skills(state_db, status=status)

    def rank(s: Skill) -> tuple:
        type_match = 1 if question_type and s.question_type == question_type else 0
        overlap = _overlap(kws, s.trigger_keywords)
        return (type_match, round(overlap, 4), s.score, s.last_applied_at or "")

    ranked = sorted(candidates, key=rank, reverse=True)
    # Only return skills with at least a type match or some keyword overlap —
    # never inject an unrelated strategy.
    out = [s for s in ranked
           if (question_type and s.question_type == question_type)
           or _overlap(kws, s.trigger_keywords) > 0]
    return out[:k]


def record_application(state_db: Path, *, skill_id: int,
                       job_id: str | None) -> int:
    """Log that ``skill_id`` was applied to ``job_id``; bump applied_count.

    Returns the application row id so the caller can complete it with the
    run's outcome once known.
    """
    _ensure(state_db)
    conn = open_db(state_db)
    try:
        cur = conn.execute(
            "INSERT INTO skill_applications (skill_id, job_id) VALUES (?, ?) "
            "RETURNING id", (skill_id, job_id),
        )
        app_id = int(cur.fetchone()[0])
        conn.execute(
            "UPDATE skills SET applied_count = applied_count + 1, "
            "last_applied_at = datetime('now') WHERE id = ?", (skill_id,),
        )
    finally:
        conn.close()
    return app_id


def complete_application(state_db: Path, *, skill_id: int, job_id: str | None,
                         coverage: float, passed: bool) -> None:
    """Record the outcome of an applied skill and recompute its stats.

    Matches the most recent open application for (skill_id, job_id); if none is
    open (e.g. application wasn't logged) it still recomputes from history.
    """
    _ensure(state_db)
    conn = open_db(state_db)
    try:
        row = conn.execute(
            "SELECT id FROM skill_applications WHERE skill_id = ? "
            "AND (job_id = ? OR (? IS NULL AND job_id IS NULL)) "
            "AND completed = 0 ORDER BY id DESC LIMIT 1",
            (skill_id, job_id, job_id),
        ).fetchone()
        if row is not None:
            conn.execute(
                "UPDATE skill_applications SET outcome_coverage = ?, "
                "outcome_passed = ?, completed = 1 WHERE id = ?",
                (coverage, 1 if passed else 0, row[0]),
            )
        # Recompute aggregate stats from completed applications.
        agg = conn.execute(
            "SELECT COUNT(*), "
            "       COALESCE(SUM(outcome_passed), 0), "
            "       COALESCE(AVG(outcome_coverage), 0.0) "
            "FROM skill_applications WHERE skill_id = ? AND completed = 1",
            (skill_id,),
        ).fetchone()
        n, wins, avg_cov = int(agg[0]), int(agg[1]), float(agg[2])
        new_score = compute_score(n, wins, avg_cov)
        conn.execute(
            "UPDATE skills SET win_count = ?, avg_coverage = ?, score = ? "
            "WHERE id = ?",
            (wins, round(avg_cov, 4), new_score, skill_id),
        )
    finally:
        conn.close()


def set_skill_status(state_db: Path, skill_id: int, status: str) -> None:
    _ensure(state_db)
    conn = open_db(state_db)
    try:
        conn.execute("UPDATE skills SET status = ? WHERE id = ?",
                     (status, skill_id))
    finally:
        conn.close()


def prune_skills(state_db: Path, *, min_trials: int = 5,
                 min_winrate: float = 0.3) -> list[int]:
    """Archive skills that have had enough trials but underperform.

    Returns the ids archived. Never hard-deletes (status='archived') so the
    audit trail and provenance survive. Idempotent.
    """
    _ensure(state_db)
    conn = open_db(state_db)
    archived: list[int] = []
    try:
        rows = conn.execute(
            _SELECT + " WHERE status = 'active'",
        ).fetchall()
        for r in rows:
            s = _row_to_skill(r)
            if s.applied_count >= min_trials and s.win_rate < min_winrate:
                conn.execute("UPDATE skills SET status = 'archived' WHERE id = ?",
                             (s.id,))
                archived.append(s.id)
    finally:
        conn.close()
    return archived
