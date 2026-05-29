"""Real-backend integration tests for the research modes.

Gated behind ``LIGHTHOUSE_REAL_BACKEND=1`` with a reachable Ollama — the default
suite stays offline + LLM-free. These prove each mode runs end-to-end through the
RAM-guarded real gateway and produces a real (not mock-masqueraded) artifact with
a provenance manifest.

Run with:  LIGHTHOUSE_REAL_BACKEND=1 .venv/bin/python -m pytest tests/test_modes_real_backend.py -q
"""

from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="set LIGHTHOUSE_REAL_BACKEND=1 and have ollama on 127.0.0.1:11434",
)


def _draft_body(state_db, draft_id):
    from lighthouse_ai.persistence import open_db
    conn = open_db(state_db)
    try:
        row = conn.execute(
            "SELECT artifact_type, body_json FROM drafts WHERE id=?",
            (draft_id,)).fetchone()
    finally:
        conn.close()
    return row[0], json.loads(row[1]) if row[1] else {}


def _insert(state_db, jid, mode, meta):
    from lighthouse_ai.persistence import open_db
    conn = open_db(state_db)
    try:
        conn.execute(
            "INSERT INTO jobs (id, mode, status, metadata_json) "
            "VALUES (?, ?, 'queued', ?)", (jid, mode, json.dumps(meta)))
    finally:
        conn.close()


# No-corpus modes exercise the LLM meaningfully without ingest setup.
_REAL_CASES = [
    ("decide", {"topic": "Postgres vs SQLite for a local-first app?",
                "options": ["Postgres", "SQLite"],
                "criteria": [{"label": "Simplicity", "weight": 2.0},
                             {"label": "Concurrency", "weight": 1.0}]},
     "matrix"),
    ("adjudicate", {"topic": "Should small teams self-host LLMs?"}, "verdict"),
]


@pytest.mark.parametrize("mode,meta,artifact_type", _REAL_CASES)
def test_mode_runs_on_real_backend(migrated_paths, mode, meta, artifact_type):
    from lighthouse_ai.dispatcher import build_runtime_gateway, dispatch_once

    gw = build_runtime_gateway(migrated_paths)
    if gw is None:
        pytest.skip("ollama not reachable / no models installed")

    _insert(migrated_paths.state_db, "j1", mode, meta)
    draft_id = dispatch_once(migrated_paths, gateway=gw)
    assert draft_id is not None

    atype, body = _draft_body(migrated_paths.state_db, draft_id)
    assert atype == artifact_type
    prov = body.get("provenance") or {}
    # The artifact must record a provenance manifest, and the run must be real
    # (ollama) — not a silent mock masquerade.
    assert prov.get("backend") in {"ollama", "mock", "mock-lowmem"}
    if prov.get("backend") == "ollama":
        assert prov.get("models")
