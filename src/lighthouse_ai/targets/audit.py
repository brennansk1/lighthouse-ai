"""Audit target adapter: every applied intent appends to ``audit_events``.

The audit log is append-only; full HMAC chain is wired in Sprint 13/14.
Sprint 2 only needs the append path so we can prove cross-store atomicity.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..effector import register_target
from ..intents import Intent
from ..persistence import open_db
from ..sagas import register as register_compensator

NAME = "audit"


def make_applier(audit_db_path: Path):
    def applier(intent: Intent) -> None:
        conn = open_db(audit_db_path)
        try:
            conn.execute(
                "INSERT INTO audit_events (actor, event_type, payload_json) VALUES (?, ?, ?)",
                (intent.target, intent.op, json.dumps(intent.payload, sort_keys=True)),
            )
        finally:
            conn.close()

    return applier


def make_compensator(audit_db_path: Path):
    def compensator(intent: Intent) -> None:
        conn = open_db(audit_db_path)
        try:
            conn.execute(
                "INSERT INTO audit_events (actor, event_type, payload_json) VALUES (?, 'void', ?)",
                (intent.target, json.dumps({"void_of": intent.idempotency_key})),
            )
        finally:
            conn.close()

    return compensator


def install(audit_db_path: Path) -> None:
    register_target(NAME, make_applier(audit_db_path))
    register_compensator(NAME, make_compensator(audit_db_path))
