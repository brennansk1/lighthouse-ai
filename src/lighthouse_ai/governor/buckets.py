"""Hierarchical token buckets — atomic, SQLite-backed.

Per design §24.2: every spend dimension (USD, tool_calls, tokens) is gated
by four nested buckets: monthly → weekly → daily → per_job. A request only
succeeds when *every* level has headroom; a single atomic transaction
either debits all four or none.

Time windows roll over automatically: when a request is processed and the
period boundary has passed (calendar month, ISO week, calendar day in the
local TZ for now — UTC eventually), the bucket is reset to its configured
ceiling before the debit.

The implementation is intentionally schema-light: one row per
(dimension, period_kind) in the ``state.db`` (Sprint 1 already has it).
We create a new ``governor_buckets`` table here via a migration.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from ..persistence import open_db

DIMENSIONS: tuple[str, ...] = ("usd", "tool_calls", "tokens")
PERIODS: tuple[str, ...] = ("monthly", "weekly", "daily")


@dataclass(frozen=True)
class BudgetConfig:
    monthly_usd: float = 50.0
    weekly_usd: float = 15.0
    daily_usd: float = 3.0
    monthly_tool_calls: int = 150_000
    weekly_tool_calls: int = 35_000
    daily_tool_calls: int = 5_000
    monthly_tokens: int = 200_000_000
    weekly_tokens: int = 50_000_000
    daily_tokens: int = 8_000_000
    # Per-job ceilings (§24.2 row 4) — enforced separately, not through buckets.
    per_job_tool_calls: int = 1_500
    per_job_tokens: int = 2_000_000

    def ceiling(self, dimension: str, period: str) -> float:
        key = f"{period}_{dimension}"
        if not hasattr(self, key):
            raise KeyError(f"no budget configured for {key}")
        return float(getattr(self, key))


BUDGET_DEFAULTS = BudgetConfig()


@dataclass(frozen=True)
class GovernorDecision:
    allowed: bool
    reason: str = ""
    remaining: dict[str, float] = field(default_factory=dict)
    tier: str = "green"


class BudgetTripped(RuntimeError):
    """Raised when a spend request exceeds available budget."""


# --- bootstrap ---

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS governor_buckets (
    dimension   TEXT NOT NULL,
    period      TEXT NOT NULL,
    period_key  TEXT NOT NULL,
    remaining   REAL NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (dimension, period)
);
CREATE TABLE IF NOT EXISTS governor_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    kind TEXT NOT NULL,                -- 'spend' | 'trip' | 'reset' | 'tier_change'
    dimension TEXT,
    amount REAL,
    job_id TEXT,
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_gov_events_ts ON governor_events (ts);
"""


def ensure_schema(state_db: Path) -> None:
    conn = open_db(state_db)
    try:
        conn.executescript(_INIT_SQL)
    finally:
        conn.close()


# --- period keys ---

def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _period_key(period: str, now: _dt.datetime | None = None) -> str:
    n = now or _now_utc()
    if period == "monthly":
        return f"{n.year:04d}-{n.month:02d}"
    if period == "weekly":
        iso_year, iso_week, _ = n.isocalendar()
        return f"{iso_year:04d}-W{iso_week:02d}"
    if period == "daily":
        return f"{n.year:04d}-{n.month:02d}-{n.day:02d}"
    raise ValueError(f"unknown period {period!r}")


# --- degradation tier (pure function for testability) ---

def degradation_tier(remaining_pct: float) -> str:
    """Map remaining-monthly-budget percentage → tier name.

    Table per §24.3 (inverted because the design talks about *headroom*).
    """
    if remaining_pct >= 50:
        return "green"
    if remaining_pct >= 30:
        return "warn"
    if remaining_pct >= 15:
        return "degrade"
    if remaining_pct >= 5:
        return "local_only"
    if remaining_pct > 0:
        return "drain"
    return "tripped"


class Governor:
    """Atomic spend gate over the three bucket dimensions × three periods."""

    def __init__(self, state_db: Path, config: BudgetConfig = BUDGET_DEFAULTS):
        self.state_db = state_db
        self.config = config
        ensure_schema(state_db)

    # --- introspection ---
    def remaining(self) -> dict[str, dict[str, float]]:
        """Current remaining values keyed by ``[dimension][period]``."""
        now = _now_utc()
        conn = open_db(self.state_db)
        out: dict[str, dict[str, float]] = {d: {} for d in DIMENSIONS}
        try:
            for dim in DIMENSIONS:
                for period in PERIODS:
                    pk = _period_key(period, now)
                    row = conn.execute(
                        "SELECT period_key, remaining FROM governor_buckets "
                        "WHERE dimension = ? AND period = ?", (dim, period),
                    ).fetchone()
                    if not row or row[0] != pk:
                        out[dim][period] = self.config.ceiling(dim, period)
                    else:
                        out[dim][period] = float(row[1])
        finally:
            conn.close()
        return out

    def tier(self) -> str:
        """Current degradation tier (based on monthly USD remaining)."""
        rem = self.remaining()["usd"]["monthly"]
        pct = (rem / self.config.monthly_usd) * 100 if self.config.monthly_usd > 0 else 0
        return degradation_tier(pct)

    # --- atomic spend ---
    def try_spend(self, *, usd: float = 0.0, tool_calls: int = 0,
                  tokens: int = 0, job_id: str | None = None) -> GovernorDecision:
        """Attempt to debit all four buckets. All-or-nothing."""
        amounts = {"usd": usd, "tool_calls": tool_calls, "tokens": tokens}
        if all(v <= 0 for v in amounts.values()):
            return GovernorDecision(True, "no-op", self._flatten(self.remaining()), self.tier())

        now = _now_utc()
        conn = open_db(self.state_db)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                # Step 1: read current state for every (dim, period); reset on rollover.
                projected: dict[tuple[str, str], float] = {}
                for dim in DIMENSIONS:
                    spend = amounts[dim]
                    if spend <= 0:
                        continue
                    for period in PERIODS:
                        pk = _period_key(period, now)
                        row = conn.execute(
                            "SELECT period_key, remaining FROM governor_buckets "
                            "WHERE dimension = ? AND period = ?", (dim, period),
                        ).fetchone()
                        ceiling = self.config.ceiling(dim, period)
                        if not row or row[0] != pk:
                            current = ceiling
                        else:
                            current = float(row[1])
                        after = current - spend
                        if after < 0:
                            conn.execute("ROLLBACK")
                            self._log_trip(dim, period, spend, current, job_id)
                            return GovernorDecision(
                                False,
                                f"{dim} {period} would underflow "
                                f"(remaining {current}, requested {spend})",
                                self._flatten(self.remaining()),
                                self.tier(),
                            )
                        projected[(dim, period)] = after

                # Step 2: write all bucket rows + audit event.
                for (dim, period), after in projected.items():
                    pk = _period_key(period, now)
                    conn.execute(
                        """
                        INSERT INTO governor_buckets
                            (dimension, period, period_key, remaining, updated_at)
                            VALUES (?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(dimension, period) DO UPDATE SET
                            period_key = excluded.period_key,
                            remaining = excluded.remaining,
                            updated_at = excluded.updated_at
                        """,
                        (dim, period, pk, after),
                    )
                conn.execute(
                    "INSERT INTO governor_events (kind, dimension, amount, job_id, payload_json) "
                    "VALUES ('spend', NULL, NULL, ?, ?)",
                    (job_id, _json(amounts)),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

        rem = self.remaining()
        return GovernorDecision(True, "", self._flatten(rem), self.tier())

    def spend(self, *, usd: float = 0.0, tool_calls: int = 0,
              tokens: int = 0, job_id: str | None = None) -> GovernorDecision:
        decision = self.try_spend(usd=usd, tool_calls=tool_calls, tokens=tokens, job_id=job_id)
        if not decision.allowed:
            raise BudgetTripped(decision.reason)
        return decision

    # --- manual reset ---
    def reset(self, *, dimensions: Iterable[str] | None = None,
              periods: Iterable[str] | None = None) -> int:
        """Manual ``lighthouse budget reset`` — clears bucket rows so the
        next read returns the ceiling. Returns # rows cleared."""
        dims = tuple(dimensions) if dimensions else DIMENSIONS
        prds = tuple(periods) if periods else PERIODS
        conn = open_db(self.state_db)
        try:
            cur = conn.execute(
                f"DELETE FROM governor_buckets WHERE dimension IN "
                f"({','.join('?' * len(dims))}) AND period IN "
                f"({','.join('?' * len(prds))})",
                (*dims, *prds),
            )
            conn.execute(
                "INSERT INTO governor_events (kind, payload_json) VALUES ('reset', ?)",
                (_json({"dimensions": list(dims), "periods": list(prds)}),),
            )
        finally:
            conn.close()
        return cur.rowcount or 0

    def cost_report(self) -> dict:
        rem = self.remaining()
        tier = self.tier()
        return {
            "remaining": rem,
            "config": {k: getattr(self.config, k) for k in self.config.__dataclass_fields__},
            "tier": tier,
        }

    # --- internals ---
    def _log_trip(self, dim: str, period: str, spend: float, current: float,
                  job_id: str | None) -> None:
        conn = open_db(self.state_db)
        try:
            conn.execute(
                "INSERT INTO governor_events (kind, dimension, amount, job_id, payload_json) "
                "VALUES ('trip', ?, ?, ?, ?)",
                (dim, spend, job_id, _json({"period": period, "remaining": current})),
            )
        finally:
            conn.close()

    @staticmethod
    def _flatten(rem: dict[str, dict[str, float]]) -> dict[str, float]:
        out: dict[str, float] = {}
        for dim, periods in rem.items():
            for period, val in periods.items():
                out[f"{dim}.{period}"] = val
        return out


# --- internal json helper (json import deferred so the module is lean) ---

def _json(obj: object) -> str:
    import json
    return json.dumps(obj, sort_keys=True, default=str)
