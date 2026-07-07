"""Zone V — calibration auto-resolver tests (gaps #9, #23).

Fully offline + deterministic: a fixed ``now`` drives deadline selection and a
fake ``research_fn`` drives the verdict, so no clock or network is touched.
"""

from __future__ import annotations

from datetime import UTC, datetime

from lighthouse_ai.persistence import open_db
from lighthouse_ai.verification.positions import record_position
from lighthouse_ai.verification.resolver import is_past_deadline, resolve_positions

# A clock far enough out that a 2020 deadline is in the past.
NOW = datetime(2026, 1, 1, 0, 0, 0)
PAST = "2020-01-01T00:00:00"
FUTURE = "2099-01-01T00:00:00"


def _outcome(positions_db, pos_id: int):
    conn = open_db(positions_db)
    try:
        return conn.execute(
            "SELECT outcome, brier FROM positions WHERE id = ?", (pos_id,)
        ).fetchone()
    finally:
        conn.close()


def test_record_position_stores_resolve_by_and_criterion(migrated_paths):
    pos = record_position(
        migrated_paths.positions_db,
        claim="Will drug X be approved by 2024?",
        probability=0.8,
        resolve_by=PAST,
        resolution_criterion="FDA marketing authorization granted",
    )
    assert pos.resolve_by == PAST
    assert pos.resolution_criterion == "FDA marketing authorization granted"

    conn = open_db(migrated_paths.positions_db)
    try:
        row = conn.execute(
            "SELECT resolve_by, resolution_criterion FROM positions WHERE id = ?",
            (pos.id,),
        ).fetchone()
    finally:
        conn.close()
    assert row == (PAST, "FDA marketing authorization granted")


def test_record_position_default_resolve_by_uses_injected_now(migrated_paths):
    pos = record_position(
        migrated_paths.positions_db, claim="Will it ship?", probability=0.7, now=NOW
    )
    due = datetime.fromisoformat(pos.resolve_by)
    assert (due - NOW).days == 90


def test_resolve_positions_resolves_past_leaves_future_and_human(migrated_paths):
    db = migrated_paths.positions_db

    past = record_position(
        db,
        claim="Will drug X be approved by 2024?",
        probability=0.8,
        resolve_by=PAST,
        resolution_criterion="FDA approval granted",
    )
    future = record_position(
        db, claim="Will drug Y be approved by 2030?", probability=0.6, resolve_by=FUTURE
    )
    human = record_position(
        db, claim="Should we prioritize economic growth?", probability=0.9, resolve_by=PAST
    )

    calls: list[tuple[str, str | None]] = []

    def fake_research(claim: str, criterion: str | None):
        calls.append((claim, criterion))
        return True, 0.92, "Approved per the registry."

    results = resolve_positions(db, research_fn=fake_research, now=NOW)

    # Only the past-deadline, machine-resolvable claim is attempted.
    assert [c[0] for c in calls] == ["Will drug X be approved by 2024?"]
    assert calls[0][1] == "FDA approval granted"
    assert len(results) == 1
    assert results[0].auto_resolved is True
    assert results[0].outcome is True

    # Past position scored; Brier = (0.8 - 1)^2 = 0.04.
    outcome, brier = _outcome(db, past.id)
    assert outcome == 1
    assert abs(brier - 0.04) < 1e-9

    # Future and human-only positions untouched.
    assert _outcome(db, future.id) == (None, None)
    assert _outcome(db, human.id) == (None, None)


def test_resolve_positions_defers_ambiguous(migrated_paths):
    db = migrated_paths.positions_db
    pos = record_position(
        db, claim="Will the merger close by 2024?", probability=0.7, resolve_by=PAST
    )

    def ambiguous_research(claim: str, criterion: str | None):
        return None, 0.0, "Conflicting reports; cannot determine."

    results = resolve_positions(db, research_fn=ambiguous_research, now=NOW)

    assert len(results) == 1
    assert results[0].auto_resolved is False
    assert results[0].outcome is None
    # Not force-resolved: still open in the DB.
    assert _outcome(db, pos.id) == (None, None)


def test_resolve_positions_defers_low_confidence(migrated_paths):
    db = migrated_paths.positions_db
    pos = record_position(
        db, claim="Will the satellite launch by 2024?", probability=0.7, resolve_by=PAST
    )

    def low_conf_research(claim: str, criterion: str | None):
        return True, 0.4, "Weak signal."  # below default threshold 0.7

    results = resolve_positions(db, research_fn=low_conf_research, now=NOW)
    assert results[0].auto_resolved is False
    assert _outcome(db, pos.id) == (None, None)


def test_resolve_positions_noop_without_fn_or_gateway(migrated_paths):
    db = migrated_paths.positions_db
    record_position(db, claim="Will it ship by 2024?", probability=0.7, resolve_by=PAST)
    assert resolve_positions(db, now=NOW) == []


# A tz-AWARE past deadline against a naive ``now``: the old code raised
# TypeError on ``ref >= due`` (can't compare naive vs aware), the bare except
# swallowed it, and the position NEVER resolved.
PAST_AWARE = "2020-01-01T00:00:00+00:00"


def test_is_past_deadline_tz_aware_resolve_by_past():
    # Aware resolve_by, naive now → must still recognize the deadline passed.
    assert is_past_deadline(PAST_AWARE, now=NOW) is True


def test_is_past_deadline_tz_aware_now_vs_naive_resolve_by():
    # Symmetric case: naive resolve_by, aware now.
    now_aware = datetime(2026, 1, 1, tzinfo=UTC)
    assert is_past_deadline(PAST, now=now_aware) is True


def test_resolve_positions_resolves_tz_aware_deadline(migrated_paths):
    db = migrated_paths.positions_db
    pos = record_position(
        db,
        claim="Will drug Z be approved by 2024?",
        probability=0.8,
        resolve_by=PAST_AWARE,
        resolution_criterion="FDA approval granted",
    )

    def fake_research(claim: str, criterion: str | None):
        return True, 0.92, "Approved per the registry."

    results = resolve_positions(db, research_fn=fake_research, now=NOW)

    assert len(results) == 1
    assert results[0].auto_resolved is True
    outcome, _ = _outcome(db, pos.id)
    assert outcome == 1
