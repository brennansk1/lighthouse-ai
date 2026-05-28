"""Verification + compounding knowledge tests (Sprint 13-14)."""

from __future__ import annotations

import json

import pytest

from lighthouse_ai.verification import (
    WEP_BANDS,
    add_hypothesis,
    add_skill,
    append_event,
    band_for_probability,
    brier_score,
    increment_use,
    list_hypotheses,
    list_skills,
    mean_brier,
    parse_band,
    record_position,
    resolve_position,
    score_all,
    seal_event_chain,
    update_hypothesis,
    verify_audit_chain,
)

# --- WEP ---

def test_wep_bands_cover_zero_to_one():
    assert any(p in b for b in WEP_BANDS for p in [0.0, 0.05, 0.5, 0.95, 1.0])


@pytest.mark.parametrize("p,expected", [
    (0.05, "remote"), (0.2, "unlikely"), (0.5, "even"),
    (0.75, "likely"), (0.95, "almost_certain"), (1.0, "almost_certain"),
])
def test_band_for_probability(p, expected):
    assert band_for_probability(p).name == expected


def test_band_for_probability_rejects_out_of_range():
    with pytest.raises(ValueError):
        band_for_probability(1.5)


def test_parse_band_round_trip():
    assert parse_band("almost certain").name == "almost_certain"


# --- Brier ---

def test_brier_perfect_calibration():
    assert brier_score(1.0, True) == 0.0
    assert brier_score(0.0, False) == 0.0


def test_brier_max_error():
    assert brier_score(0.0, True) == 1.0
    assert brier_score(1.0, False) == 1.0


def test_mean_brier_aggregates():
    val = mean_brier([(0.8, True), (0.2, False), (0.5, True)])
    expected = (0.04 + 0.04 + 0.25) / 3
    assert abs(val - expected) < 1e-9


# --- Positions ---

def test_record_and_resolve_position(migrated_paths):
    pos = record_position(migrated_paths.positions_db, claim="X will happen",
                          probability=0.8)
    resolved = resolve_position(migrated_paths.positions_db, pos.id, outcome=True)
    assert resolved.outcome is True
    assert abs(resolved.brier - 0.04) < 1e-9


def test_score_all_handles_empty_set(migrated_paths):
    out = score_all(migrated_paths.positions_db)
    assert out["n"] == 0


def test_score_all_reports_calibration_error(migrated_paths):
    p1 = record_position(migrated_paths.positions_db, claim="A", probability=0.8)
    p2 = record_position(migrated_paths.positions_db, claim="B", probability=0.8)
    resolve_position(migrated_paths.positions_db, p1.id, outcome=True)
    resolve_position(migrated_paths.positions_db, p2.id, outcome=False)
    metrics = score_all(migrated_paths.positions_db)
    assert metrics["n"] == 2
    assert metrics["mean_probability"] == 0.8
    assert metrics["mean_outcome_rate"] == 0.5
    assert abs(metrics["calibration_error"] - 0.3) < 1e-9


def test_resolve_position_missing_raises(migrated_paths):
    with pytest.raises(KeyError):
        resolve_position(migrated_paths.positions_db, 9999, outcome=True)


def test_record_position_sets_resolve_by(migrated_paths):
    from datetime import datetime

    from lighthouse_ai.verification.positions import record_position
    pos = record_position(migrated_paths.positions_db, claim="X will happen", probability=0.8)
    assert pos.resolve_by is not None
    due = datetime.fromisoformat(pos.resolve_by)
    diff = abs((due - datetime.now()).days - 90)
    assert diff <= 1


def test_record_position_custom_resolve_by(migrated_paths):
    from lighthouse_ai.verification.positions import record_position
    pos = record_position(migrated_paths.positions_db, claim="Y", probability=0.7,
                          resolve_by="2099-01-01T00:00:00")
    assert pos.resolve_by == "2099-01-01T00:00:00"


# --- Audit chain ---

def test_append_and_verify_chain(migrated_paths):
    secret = b"secret-1"
    for i in range(5):
        append_event(migrated_paths.audit_db, actor="t",
                     event_type="test", payload={"i": i}, secret=secret)
    bad = verify_audit_chain(migrated_paths.audit_db, secret=secret)
    assert bad == []


def test_tampered_row_invalidates_chain(migrated_paths):
    secret = b"k"
    append_event(migrated_paths.audit_db, actor="a", event_type="t",
                 payload={"a": 1}, secret=secret)
    append_event(migrated_paths.audit_db, actor="a", event_type="t",
                 payload={"a": 2}, secret=secret)
    # Tamper with the first row.
    from lighthouse_ai.persistence import open_db
    conn = open_db(migrated_paths.audit_db)
    try:
        conn.execute("UPDATE audit_events SET payload_json = ? WHERE seq = 1",
                     (json.dumps({"tampered": True}),))
    finally:
        conn.close()
    bad = verify_audit_chain(migrated_paths.audit_db, secret=secret)
    assert bad  # at least one seq flagged


def test_wrong_secret_invalidates_chain(migrated_paths):
    append_event(migrated_paths.audit_db, actor="a", event_type="t",
                 payload={}, secret=b"good")
    bad = verify_audit_chain(migrated_paths.audit_db, secret=b"wrong")
    assert bad


def test_seal_chain_handles_preexisting_unsigned_rows(migrated_paths):
    from lighthouse_ai.persistence import open_db
    conn = open_db(migrated_paths.audit_db)
    try:
        for i in range(3):
            conn.execute(
                "INSERT INTO audit_events (actor, event_type, payload_json) "
                "VALUES (?, ?, ?)", ("legacy", "t", json.dumps({"i": i})),
            )
    finally:
        conn.close()
    n = seal_event_chain(migrated_paths.audit_db, secret=b"s")
    assert n == 3
    assert verify_audit_chain(migrated_paths.audit_db, secret=b"s") == []


# --- Hypotheses ---

def test_hypothesis_lifecycle(migrated_paths):
    hid = add_hypothesis(migrated_paths.hypotheses_db, "The sky is blue.")
    open_ = list_hypotheses(migrated_paths.hypotheses_db, status="open")
    assert len(open_) == 1
    update_hypothesis(migrated_paths.hypotheses_db, hid, "supported")
    supported = list_hypotheses(migrated_paths.hypotheses_db, status="supported")
    assert supported[0].id == hid


def test_hypothesis_status_validation(migrated_paths):
    hid = add_hypothesis(migrated_paths.hypotheses_db, "S")
    with pytest.raises(ValueError):
        update_hypothesis(migrated_paths.hypotheses_db, hid, "bogus")


# --- Skills ---

def test_add_and_list_skills(migrated_paths):
    sid = add_skill(migrated_paths.state_db, name="extract_table",
                    description="Pull tabular data out of PDFs",
                    body={"steps": ["open", "ocr", "parse"]})
    skills = list_skills(migrated_paths.state_db)
    assert len(skills) == 1
    assert skills[0].id == sid
    assert skills[0].body["steps"] == ["open", "ocr", "parse"]


def test_skill_use_count_increments(migrated_paths):
    sid = add_skill(migrated_paths.state_db, name="x", description=None, body={})
    for _ in range(3):
        increment_use(migrated_paths.state_db, sid)
    skills = list_skills(migrated_paths.state_db)
    assert skills[0].use_count == 3


def test_skill_upsert_on_same_name(migrated_paths):
    a = add_skill(migrated_paths.state_db, name="x", description="v1", body={"a": 1})
    b = add_skill(migrated_paths.state_db, name="x", description="v2", body={"a": 2})
    assert a == b
    skills = list_skills(migrated_paths.state_db)
    assert skills[0].body == {"a": 2}


# --- Resolver (Sprint 32) ---

def test_is_past_deadline_with_past_date():
    from lighthouse_ai.verification.resolver import is_past_deadline
    assert is_past_deadline("2020-01-01T00:00:00") is True

def test_is_past_deadline_with_future_date():
    from lighthouse_ai.verification.resolver import is_past_deadline
    assert is_past_deadline("2099-01-01T00:00:00") is False

def test_is_past_deadline_with_none():
    from lighthouse_ai.verification.resolver import is_past_deadline
    assert is_past_deadline(None) is False

def test_classify_machine_resolvable():
    from lighthouse_ai.verification.resolver import classify_resolution_kind
    assert classify_resolution_kind("Will drug X be FDA-approved by 2025?") == "machine"

def test_classify_human_only():
    from lighthouse_ai.verification.resolver import classify_resolution_kind
    assert classify_resolution_kind("Should we prioritize economic growth?") == "human"

def test_attempt_auto_resolve_without_gateway():
    from lighthouse_ai.verification.resolver import attempt_auto_resolve
    result = attempt_auto_resolve(1, "Will X happen?", 0.7, gateway=None)
    assert result.auto_resolved is False
    assert result.outcome is None

def test_attempt_auto_resolve_human_claim():
    from unittest.mock import MagicMock

    from lighthouse_ai.verification.resolver import attempt_auto_resolve
    gw = MagicMock()
    result = attempt_auto_resolve(1, "Should we invest in nuclear energy?", 0.6,
                                  gateway=gw)
    assert result.auto_resolved is False
    gw.complete.assert_not_called()

def test_attempt_auto_resolve_success():
    from unittest.mock import MagicMock

    from lighthouse_ai.verification.resolver import attempt_auto_resolve
    gw = MagicMock()
    gw.complete.return_value = MagicMock(
        text="TRUE: 0.85 — Drug X received FDA approval in Q2 2024."
    )
    result = attempt_auto_resolve(1, "Will drug X be approved by 2024?", 0.8, gateway=gw)
    assert result.auto_resolved is True
    assert result.outcome is True
    assert abs(result.confidence - 0.85) < 0.01
    assert result.brier is not None

def test_parse_resolution_true():
    from lighthouse_ai.verification.resolver import _parse_resolution
    outcome, conf, rationale = _parse_resolution("TRUE: 0.9 — Evidence confirmed.")
    assert outcome is True
    assert abs(conf - 0.9) < 0.01
    assert "confirmed" in rationale

def test_parse_resolution_false():
    from lighthouse_ai.verification.resolver import _parse_resolution
    outcome, conf, rationale = _parse_resolution("FALSE: 0.75 — Studies refuted it.")
    assert outcome is False

def test_parse_resolution_uncertain():
    from lighthouse_ai.verification.resolver import _parse_resolution
    outcome, conf, rationale = _parse_resolution("UNCERTAIN: — Not enough data.")
    assert outcome is None

def test_run_resolver_pass_no_past_deadline(migrated_paths):
    """No positions → empty results."""
    from lighthouse_ai.verification.resolver import run_resolver_pass
    results = run_resolver_pass(migrated_paths.positions_db, gateway=None)
    assert results == []
