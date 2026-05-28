"""HMAC-chained audit log helpers.

Each new ``audit_events`` row carries an ``hmac`` computed from
``HMAC(secret, prev_hmac || seq || ts || actor || event_type || payload)``.
The chain is breakable only with the secret, and any tampering of an old
row invalidates every subsequent row.

The chaining key lives in the OS keychain in production; tests pass an
explicit secret.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..persistence import open_db


def _hmac(secret: bytes, *parts: bytes) -> str:
    h = hmac.new(secret, digestmod=hashlib.sha256)
    for p in parts:
        h.update(p)
    return h.hexdigest()


def _row_to_bytes(seq: int, ts: str, actor: str, event_type: str,
                  payload_json: str, prev_hmac: str | None) -> tuple[bytes, ...]:
    return (
        (prev_hmac or "").encode(),
        str(seq).encode(),
        ts.encode(),
        actor.encode(),
        event_type.encode(),
        payload_json.encode(),
    )


@dataclass(frozen=True)
class AuditEvent:
    seq: int
    ts: str
    actor: str
    event_type: str
    payload: dict


def resolve_secret(secret: bytes | None, *, data_dir: Path | None = None) -> bytes:
    """Return ``secret`` if explicit; otherwise pull (or mint) from SecretStore.

    Sprint 21: callers that pass an explicit secret keep the existing behavior
    (used everywhere in tests). Production callers pass ``secret=None`` and
    let the Keychain own the value. The first lookup mints a fresh 32-byte
    random secret and stores it.
    """
    if secret is not None:
        return secret
    if data_dir is None:
        raise ValueError("secret=None requires data_dir to locate SecretStore")
    from ..secrets import AUDIT_CHAIN_KEY, SecretStore
    s = SecretStore(data_dir)
    hex_secret = s.get_or_create(AUDIT_CHAIN_KEY, nbytes=32)
    return bytes.fromhex(hex_secret)


def append_event(audit_db: Path, *, actor: str, event_type: str,
                 payload: dict, secret: bytes | None = None,
                 data_dir: Path | None = None) -> int:
    """Insert a new audit event and seal it into the HMAC chain.

    ``secret`` may be ``None`` if ``data_dir`` is given — in that case the
    chain key is resolved from the SecretStore (Keychain → file fallback).
    """
    secret = resolve_secret(secret, data_dir=data_dir)
    payload_json = json.dumps(payload, sort_keys=True)
    conn = open_db(audit_db)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT hmac FROM audit_events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev = row[0] if row else None
            cur = conn.execute(
                "INSERT INTO audit_events (actor, event_type, payload_json, prev_hmac) "
                "VALUES (?, ?, ?, ?) RETURNING seq, ts",
                (actor, event_type, payload_json, prev),
            )
            seq, ts = cur.fetchone()
            new_hmac = _hmac(secret, *_row_to_bytes(
                seq, ts, actor, event_type, payload_json, prev,
            ))
            conn.execute("UPDATE audit_events SET hmac = ? WHERE seq = ?",
                         (new_hmac, seq))
            conn.execute("COMMIT")
            return seq
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def seal_event_chain(audit_db: Path, *, secret: bytes) -> int:
    """Compute and write HMACs for any rows lacking one. Returns # rows sealed.

    Useful when migrating from pre-Sprint-13 unsigned events.
    """
    conn = open_db(audit_db)
    n = 0
    try:
        rows = conn.execute(
            "SELECT seq, ts, actor, event_type, payload_json, prev_hmac, hmac "
            "FROM audit_events ORDER BY seq"
        ).fetchall()
        prev: str | None = None
        for seq, ts, actor, et, pj, recorded_prev, existing in rows:
            # Honor any pre-existing chain: take prev from the row when set.
            effective_prev = recorded_prev if recorded_prev is not None else prev
            new_hmac = _hmac(secret, *_row_to_bytes(seq, ts, actor, et, pj,
                                                    effective_prev))
            if existing != new_hmac:
                conn.execute(
                    "UPDATE audit_events SET prev_hmac = ?, hmac = ? WHERE seq = ?",
                    (effective_prev, new_hmac, seq),
                )
                n += 1
            prev = new_hmac
    finally:
        conn.close()
    return n


def verify_audit_chain(audit_db: Path, *, secret: bytes) -> list[int]:
    """Return the list of seq numbers whose HMAC doesn't reverify.

    Empty list ⇒ chain intact.
    """
    bad: list[int] = []
    conn = open_db(audit_db)
    try:
        rows = conn.execute(
            "SELECT seq, ts, actor, event_type, payload_json, prev_hmac, hmac "
            "FROM audit_events ORDER BY seq"
        ).fetchall()
        prev: str | None = None
        for seq, ts, actor, et, pj, recorded_prev, existing in rows:
            if recorded_prev != prev:
                bad.append(seq)
                prev = existing
                continue
            expected = _hmac(secret, *_row_to_bytes(seq, ts, actor, et, pj, prev))
            if expected != existing:
                bad.append(seq)
            prev = existing
    finally:
        conn.close()
    return bad
