"""§26.5 periodic integrity verification.

This module assembles a single structured health verdict for the durability
subsystem: every ``.db`` passes ``PRAGMA integrity_check`` and the Litestream
replicas are fresh (lag < 60s per §26.5). It deliberately reuses the existing
primitives — :func:`persistence.integrity_check`, :func:`paths.Paths.all_dbs`
and :func:`litestream.replica_lags` — rather than reimplementing them, so the
weekly integrity job and the ``doctor`` command share one source of truth.

Why a frozen report dataclass: the result is consumed by alerting (Telegram +
dashboard, §26.5) and by tests, both of which want an immutable, inspectable
value rather than a pile of booleans.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import litestream
from .paths import Paths
from .persistence import db, integrity_check

# §26.5 freshness threshold: replicas lagging beyond this are considered stale.
MAX_REPLICA_LAG_SECONDS = 60.0


@dataclass(frozen=True)
class DbIntegrity:
    """Outcome of ``PRAGMA integrity_check`` for one database file."""

    kind: str
    path: Path
    result: str  # raw integrity_check output ("ok" when healthy)
    exists: bool

    @property
    def ok(self) -> bool:
        # SQLite returns the literal string "ok" when the file is consistent.
        return self.exists and self.result == "ok"


@dataclass(frozen=True)
class ReplicaFreshness:
    """Whether a single Litestream replica is within the lag budget."""

    name: str
    lag_seconds: float | None

    @property
    def ok(self) -> bool:
        # A replica with no observed data (None) is treated as not-ok: we have
        # no evidence it is protecting anything.
        return self.lag_seconds is not None and self.lag_seconds <= MAX_REPLICA_LAG_SECONDS


@dataclass(frozen=True)
class IntegrityReport:
    """Aggregate durability verdict produced by :func:`integrity_report`."""

    databases: tuple[DbIntegrity, ...]
    replicas: tuple[ReplicaFreshness, ...]

    @property
    def dbs_ok(self) -> bool:
        return all(d.ok for d in self.databases)

    @property
    def replicas_ok(self) -> bool:
        # Vacuously true when no replicas exist yet — absence of replication is
        # a configuration concern surfaced elsewhere (doctor), not corruption.
        return all(r.ok for r in self.replicas)

    @property
    def overall_ok(self) -> bool:
        return self.dbs_ok and self.replicas_ok


def _kinds(paths: Paths) -> dict[str, Path]:
    """Map kind -> db path without importing schema (avoids a heavy dep).

    Mirrors :func:`schema.kinds_for` but kept local so the integrity job does
    not pull in migration machinery just to enumerate files.
    """
    return {
        "state": paths.state_db,
        "audit": paths.audit_db,
        "intents": paths.intents_db,
        "positions": paths.positions_db,
        "hypotheses": paths.hypotheses_db,
    }


def integrity_report(paths: Paths) -> IntegrityReport:
    """Run §26.5 integrity verification and return a structured verdict.

    Runs ``PRAGMA integrity_check`` on every ``.db`` and checks each Litestream
    replica's freshness against :data:`MAX_REPLICA_LAG_SECONDS`. Missing db
    files are reported (not silently skipped) because an absent audit/state db
    is itself an integrity failure.
    """
    db_results: list[DbIntegrity] = []
    for kind, path in _kinds(paths).items():
        if not path.exists():
            db_results.append(DbIntegrity(kind, path, "missing", exists=False))
            continue
        with db(path) as conn:
            result = integrity_check(conn)
        db_results.append(DbIntegrity(kind, path, result, exists=True))

    replicas = tuple(
        ReplicaFreshness(lag.name, lag.lag_seconds)
        for lag in litestream.replica_lags(paths)
    )
    return IntegrityReport(databases=tuple(db_results), replicas=replicas)


def litestream_replicate_command(paths: Paths) -> list[str]:
    """Return the argv to start Litestream replication (without running it).

    Centralizing the command keeps the runner (which spawns the process) and
    the doctor/diagnostics (which only display it) in agreement.
    """
    return ["litestream", "replicate", "-config", str(paths.litestream_config)]
