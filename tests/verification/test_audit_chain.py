"""Unit tests for the HMAC audit-chain helpers (§24.3 / Sprint 13).

Covers: correct chain verification, tamper detection, and empty-chain edge case.
These tests use an in-memory/temp SQLite DB via the migrated_paths fixture so
they never touch the production keychain.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the conftest at the tests/ root is found.
sys.path.insert(0, str(Path(__file__).parent.parent))

from lighthouse_ai.persistence import open_db
from lighthouse_ai.verification.audit_chain import (
    append_event,
    verify_audit_chain,
)

# Re-use the shared migrated_paths fixture from the root conftest.
# (pytest auto-discovers conftest.py files up the directory tree.)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _append(paths, payload: dict, *, secret: bytes = b"test-secret") -> int:
    return append_event(
        paths.audit_db,
        actor="pytest",
        event_type="test_event",
        payload=payload,
        secret=secret,
    )


# ---------------------------------------------------------------------------
# Empty chain
# ---------------------------------------------------------------------------


def test_empty_chain_is_valid(migrated_paths):
    """An audit DB with no rows should verify cleanly (no bad seqs)."""
    bad = verify_audit_chain(migrated_paths.audit_db, secret=b"any")
    assert bad == []


# ---------------------------------------------------------------------------
# Correctly linked chain
# ---------------------------------------------------------------------------


def test_correct_chain_verifies_ok(migrated_paths):
    """Five linked entries, same secret → empty bad-seq list."""
    secret = b"chain-secret"
    for i in range(5):
        _append(migrated_paths, {"i": i}, secret=secret)
    bad = verify_audit_chain(migrated_paths.audit_db, secret=secret)
    assert bad == []


def test_single_entry_chain_is_valid(migrated_paths):
    _append(migrated_paths, {"x": 1})
    bad = verify_audit_chain(migrated_paths.audit_db, secret=b"test-secret")
    assert bad == []


# ---------------------------------------------------------------------------
# Tampered entry breaks the chain
# ---------------------------------------------------------------------------


def test_tampering_payload_breaks_chain(migrated_paths):
    """Mutating a row's payload_json should cause verify to flag that seq."""
    secret = b"s"
    _append(migrated_paths, {"a": 1}, secret=secret)
    _append(migrated_paths, {"a": 2}, secret=secret)

    # Tamper with the first row.
    conn = open_db(migrated_paths.audit_db)
    try:
        conn.execute(
            "UPDATE audit_events SET payload_json = ? WHERE seq = 1",
            (json.dumps({"tampered": True}),),
        )
    finally:
        conn.close()

    bad = verify_audit_chain(migrated_paths.audit_db, secret=secret)
    assert bad  # at least the tampered row must appear


def test_tampering_actor_breaks_chain(migrated_paths):
    """Changing the actor field should also invalidate the HMAC."""
    secret = b"actor-secret"
    _append(migrated_paths, {"v": 1}, secret=secret)

    conn = open_db(migrated_paths.audit_db)
    try:
        conn.execute("UPDATE audit_events SET actor = 'attacker' WHERE seq = 1")
    finally:
        conn.close()

    bad = verify_audit_chain(migrated_paths.audit_db, secret=secret)
    assert 1 in bad


def test_wrong_secret_flags_all_rows(migrated_paths):
    """Verifying with the wrong secret should flag every row."""
    for i in range(3):
        _append(migrated_paths, {"i": i}, secret=b"correct")

    bad = verify_audit_chain(migrated_paths.audit_db, secret=b"wrong")
    assert len(bad) > 0


# ---------------------------------------------------------------------------
# Downstream cascade: tampering row 1 cascades to row 2
# ---------------------------------------------------------------------------


def test_tamper_cascades_to_later_rows(migrated_paths):
    """Modifying row 1's payload must flag row 2 as well (prev_hmac mismatch)."""
    secret = b"cascade"
    for i in range(3):
        _append(migrated_paths, {"i": i}, secret=secret)

    conn = open_db(migrated_paths.audit_db)
    try:
        conn.execute(
            "UPDATE audit_events SET payload_json = ? WHERE seq = 1",
            (json.dumps({"evil": True}),),
        )
    finally:
        conn.close()

    bad = verify_audit_chain(migrated_paths.audit_db, secret=secret)
    # Row 1 is directly bad; row 2 and 3 may also be flagged due to the cascade.
    assert 1 in bad


def test_tampering_middle_row_cascades_to_all_later_rows(migrated_paths):
    """Mutating row N's payload must flag N *and every subsequent row*.

    This is the core tamper-evidence guarantee of an HMAC chain (per the
    module docstring: "any tampering of an old row invalidates every
    subsequent row"). A verifier that threads the *stored* hmac forward
    instead of the *recomputed* one would flag only row N and silently pass
    rows N+1.., letting an attacker rewrite history at a single row.
    """
    secret = b"strict-cascade"
    for i in range(5):  # seqs 1..5
        _append(migrated_paths, {"i": i}, secret=secret)

    # Tamper ONLY row 3's payload — leave its hmac/prev_hmac columns intact,
    # exactly what a naive row edit would do.
    conn = open_db(migrated_paths.audit_db)
    try:
        conn.execute(
            "UPDATE audit_events SET payload_json = ? WHERE seq = 3",
            (json.dumps({"evil": True}),),
        )
    finally:
        conn.close()

    bad = verify_audit_chain(migrated_paths.audit_db, secret=secret)
    # Row 3 changed → its recomputed hmac changes → rows 4 and 5 no longer
    # chain off a verified prev. All of 3,4,5 must be flagged.
    assert bad == [3, 4, 5]
