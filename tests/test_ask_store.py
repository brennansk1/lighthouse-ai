"""Ask (QUC) session persistence — turn round-trip fidelity."""

from __future__ import annotations

from lighthouse_ai.modes.ask_store import load_session, save_session
from lighthouse_ai.modes.quc import QUCSession, Turn


def test_session_round_trip_preserves_all_turn_fields(migrated_paths):
    """skill_ids_used and adjudicate_flag must survive save/load — they are
    the per-turn skill audit trail. Regression: serialization dropped them,
    silently resetting every reloaded turn to no-skills / no-adjudicate."""
    s = QUCSession(id="a-rt1", topic="Rates")
    s.history.append(Turn(role="user", text="How does the Fed set rates?"))
    s.history.append(Turn(
        role="assistant", text="Via the discount window [1].",
        citations=["c1"], skill_ids_used=["fred", "bls"],
        adjudicate_flag=True))
    save_session(migrated_paths.state_db, s, title="Rates chat")

    loaded = load_session(migrated_paths.state_db, "a-rt1")
    assert loaded is not None
    turn = loaded.history[-1]
    assert turn.citations == ["c1"]
    assert turn.skill_ids_used == ["fred", "bls"]
    assert turn.adjudicate_flag is True


def test_load_tolerates_rows_saved_before_zone_s_fields(migrated_paths):
    """Old rows (no skill_ids_used / adjudicate_flag keys) load with defaults."""
    import json

    from lighthouse_ai.persistence import open_db

    conn = open_db(migrated_paths.state_db)
    try:
        conn.execute(
            "INSERT INTO ask_sessions (id, topic, title, turns_json, status) "
            "VALUES ('a-old1', 't', 't', ?, 'open')",
            (json.dumps([{"role": "user", "text": "hi", "citations": []}]),))
    finally:
        conn.close()
    loaded = load_session(migrated_paths.state_db, "a-old1")
    assert loaded is not None
    assert loaded.history[0].skill_ids_used == []
    assert loaded.history[0].adjudicate_flag is False
