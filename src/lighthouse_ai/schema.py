"""Per-database schemas applied via simple, idempotent migrations.

Sprint 1 only requires minimal tables: the supervisor lifecycle state,
the audit log spine, and stubs for intents/positions/hypotheses so they
exist on disk and integrity-check cleanly. Real schemas land in
Sprints 2, 3, and later.

We use a hand-rolled, additive migration runner rather than Alembic for v1
of these tables. The migration set per DB is a list of (id, sql) pairs; each
DB tracks applied ids in ``schema_migrations``. Adding migrations is just
appending tuples. Switching to Alembic later is a drop-in replacement.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .persistence import open_db


@dataclass(frozen=True)
class Migration:
    id: str
    sql: str


# --- state.db: supervisor lifecycle, pause/resume state, job index ---
STATE_MIGRATIONS: list[Migration] = [
    Migration(
        "0001_initial",
        """
        CREATE TABLE supervisor_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            status TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running','paused_soft','paused_hard','kill_switched')),
            pid INTEGER,
            started_at TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT OR IGNORE INTO supervisor_state (id, status) VALUES (1, 'running');

        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            metadata_json TEXT
        );
        CREATE INDEX idx_jobs_status ON jobs (status);
        """,
    ),
    Migration(
        "0002_dashboard_surfaces",
        """
        -- Drafts: staged research outputs awaiting #approve (§22.6).
        CREATE TABLE drafts (
            id TEXT PRIMARY KEY,
            job_id TEXT,
            topic TEXT NOT NULL,
            title TEXT NOT NULL,
            body_html TEXT NOT NULL DEFAULT '',
            wep_band TEXT,
            wep_phrase TEXT,
            confidence REAL,
            source_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'staged'
                CHECK (status IN ('staged','published','rejected')),
            reject_reason TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_drafts_status ON drafts (status);

        -- Topics: standing watches the user defines (§22.4).
        CREATE TABLE topics (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'Monitor',
            cadence TEXT NOT NULL DEFAULT 'continuous',
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','paused')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Sources: per-topic feeds with a grade (§22.4 Sources tab).
        CREATE TABLE sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'rss',
            grade TEXT NOT NULL DEFAULT 'C'
                CHECK (grade IN ('A','B','C','D')),
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','paused')),
            last_fetch_at TEXT,
            error_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_sources_topic ON sources (topic_id);

        -- Perspectives: debate viewpoints (§22.7 Settings tab).
        CREATE TABLE perspectives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            stance TEXT NOT NULL DEFAULT '',
            prompt_template TEXT NOT NULL DEFAULT '',
            builtin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    Migration(
        "0003_monitor_sessions",
        """
        -- Event-monitor sessions: time-bounded watches over one or more
        -- sources. Run by the supervisor's subconscious loop. A session ends
        -- at ends_at, or auto-stops after consecutive_quiet >= quiet_cycles,
        -- or when it exceeds its max duration.
        CREATE TABLE monitor_sessions (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            source_urls_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            starts_at TEXT,
            ends_at TEXT,
            auto_stop INTEGER NOT NULL DEFAULT 1,
            quiet_cycles INTEGER NOT NULL DEFAULT 3,
            salience_floor REAL NOT NULL DEFAULT 0.5,
            max_duration_s INTEGER NOT NULL DEFAULT 86400,
            poll_interval_s INTEGER NOT NULL DEFAULT 300,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','paused','ended')),
            consecutive_quiet INTEGER NOT NULL DEFAULT 0,
            last_salience REAL,
            last_polled_at TEXT,
            cycles INTEGER NOT NULL DEFAULT 0,
            ended_reason TEXT
        );
        CREATE INDEX idx_monitor_sessions_status ON monitor_sessions (status);

        -- Items surfaced by a session, deduplicated per session.
        CREATE TABLE monitor_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES monitor_sessions(id) ON DELETE CASCADE,
            dedup_key TEXT NOT NULL,
            url TEXT,
            title TEXT NOT NULL DEFAULT '',
            salience REAL NOT NULL DEFAULT 0.0,
            category TEXT,
            is_alert INTEGER NOT NULL DEFAULT 0,
            cycle INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (session_id, dedup_key)
        );
        CREATE INDEX idx_monitor_items_session ON monitor_items (session_id);
        """,
    ),
    Migration(
        "0004_artifacts_and_transcripts",
        """
        -- Typed artifacts: every staged draft now declares what kind of
        -- artifact it is (report/table/timeline/matrix/verdict/transcript).
        -- body_json carries the structured payload for non-prose artifacts;
        -- body_html stays for prose and for a rendered fallback.
        ALTER TABLE drafts ADD COLUMN artifact_type TEXT NOT NULL DEFAULT 'report';
        ALTER TABLE drafts ADD COLUMN body_json TEXT;
        CREATE INDEX idx_drafts_artifact_type ON drafts (artifact_type, status);

        -- Ask sessions: persisted conversational Q&A transcripts so an Ask
        -- run shows up in the Library as a re-openable transcript artifact.
        CREATE TABLE ask_sessions (
            id TEXT PRIMARY KEY,
            job_id TEXT,
            topic TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            turns_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open','archived')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_ask_sessions_status ON ask_sessions (status);
        """,
    ),
]

# --- audit.db: append-only audit spine; HMAC chain in later sprint ---
AUDIT_MIGRATIONS: list[Migration] = [
    Migration(
        "0001_initial",
        """
        CREATE TABLE audit_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (datetime('now')),
            actor TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            prev_hmac TEXT,
            hmac TEXT
        );
        CREATE INDEX idx_audit_event_type ON audit_events (event_type);
        CREATE INDEX idx_audit_ts ON audit_events (ts);
        """,
    ),
]

# --- intents.db: outbox/saga (§25.2) ---
INTENTS_MIGRATIONS: list[Migration] = [
    Migration(
        "0001_initial",
        """
        CREATE TABLE intents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            target TEXT NOT NULL,
            op TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','in_flight','applied','failed','dead')),
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            claimed_at TEXT
        );
        CREATE INDEX idx_intents_status ON intents (status);
        CREATE INDEX idx_intents_target ON intents (target, status);

        CREATE TABLE dead_intents (
            id INTEGER PRIMARY KEY,
            original_id INTEGER NOT NULL,
            target TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            last_error TEXT,
            moved_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    Migration(
        "0002_saga_columns",
        """
        ALTER TABLE intents ADD COLUMN job_id TEXT;
        ALTER TABLE intents ADD COLUMN node_id TEXT;
        ALTER TABLE intents ADD COLUMN write_id TEXT;
        ALTER TABLE intents ADD COLUMN last_attempt_at TEXT;
        ALTER TABLE intents ADD COLUMN last_error TEXT;
        ALTER TABLE intents ADD COLUMN compensator_json TEXT;
        ALTER TABLE intents ADD COLUMN parent_intent_id INTEGER;
        ALTER TABLE intents ADD COLUMN applied_at TEXT;
        CREATE INDEX idx_intents_job ON intents (job_id);
        CREATE INDEX idx_intents_pending ON intents (target, status, last_attempt_at)
            WHERE status IN ('pending','in_flight');
        """,
    ),
]

# --- positions.db: position registry / calibration; expanded in later sprints ---
POSITIONS_MIGRATIONS: list[Migration] = [
    Migration(
        "0001_initial",
        """
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim TEXT NOT NULL,
            wep_band TEXT,
            confidence REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
]

# --- hypotheses.db: hypothesis tracking; expanded in later sprints ---
HYPOTHESES_MIGRATIONS: list[Migration] = [
    Migration(
        "0001_initial",
        """
        CREATE TABLE hypotheses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            statement TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open','supported','refuted','retired')),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
]


_MIGRATIONS_BY_DB: dict[str, list[Migration]] = {
    "state": STATE_MIGRATIONS,
    "audit": AUDIT_MIGRATIONS,
    "intents": INTENTS_MIGRATIONS,
    "positions": POSITIONS_MIGRATIONS,
    "hypotheses": HYPOTHESES_MIGRATIONS,
}


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def applied_migrations(conn: sqlite3.Connection) -> set[str]:
    _ensure_migrations_table(conn)
    rows = conn.execute("SELECT id FROM schema_migrations").fetchall()
    return {r[0] for r in rows}


def _split_statements(sql: str) -> list[str]:
    """Split a migration body into individual statements on ``;`` boundaries.

    SQLite's ``executescript`` cannot be used inside a caller-controlled
    transaction (it force-commits any pending one), which is exactly what
    breaks atomic rollback. We therefore execute statements one at a time
    under our own BEGIN/COMMIT. The migration DDL here is plain (no triggers
    with embedded ``;``), so a simple split on ``;`` is sufficient; comment
    lines are dropped so they don't become empty statements.
    """
    out: list[str] = []
    for raw in sql.split(";"):
        # Strip ``--`` comment lines so a comment-only fragment isn't executed.
        lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        if stmt:
            out.append(stmt)
    return out


def apply_migrations(conn: sqlite3.Connection, migrations: list[Migration]) -> list[str]:
    """Apply any not-yet-applied migrations in order. Returns ids applied.

    Each migration is applied as **one atomic transaction**: every statement
    in the migration body plus the ``schema_migrations`` insert run under a
    single explicit ``BEGIN``/``COMMIT``. If any statement fails the whole
    migration is rolled back, so a partially-applied migration can never leave
    orphan tables/columns behind that would wedge a later re-run.

    We deliberately do *not* use ``executescript`` here: it force-commits any
    pending transaction, which would silently break the atomicity guarantee.
    """
    _ensure_migrations_table(conn)
    already = applied_migrations(conn)
    applied: list[str] = []
    for m in migrations:
        if m.id in already:
            continue
        conn.execute("BEGIN")
        try:
            for stmt in _split_statements(m.sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (id) VALUES (?)", (m.id,)
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(m.id)
    return applied


def migrate_path(db_path: Path, kind: str) -> list[str]:
    """Open ``db_path`` with Lighthouse PRAGMAs and apply ``kind`` migrations."""
    if kind not in _MIGRATIONS_BY_DB:
        raise KeyError(f"Unknown db kind: {kind!r}")
    conn = open_db(db_path)
    try:
        return apply_migrations(conn, _MIGRATIONS_BY_DB[kind])
    finally:
        conn.close()


def migrate_all(paths_map: dict[str, Path]) -> dict[str, list[str]]:
    """Apply migrations across every DB in ``paths_map`` (kind → path)."""
    out: dict[str, list[str]] = {}
    for kind, path in paths_map.items():
        out[kind] = migrate_path(path, kind)
    return out


def kinds_for(paths) -> dict[str, Path]:  # type: ignore[no-untyped-def]
    """Map kind name to file path on a :class:`lighthouse_ai.paths.Paths`."""
    return {
        "state": paths.state_db,
        "audit": paths.audit_db,
        "intents": paths.intents_db,
        "positions": paths.positions_db,
        "hypotheses": paths.hypotheses_db,
    }
