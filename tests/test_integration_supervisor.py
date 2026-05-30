"""Integration tests: supervisor in a thread, real uvicorn, real httpx."""

from __future__ import annotations

import time

import httpx
import pytest

from lighthouse_ai import intents
from lighthouse_ai.persistence import open_db
from lighthouse_ai.supervisor import _recover_orphaned_intents, serve_in_thread


@pytest.mark.integration
def test_supervisor_starts_and_serves_health(tmp_paths):
    server, thread, port = serve_in_thread(tmp_paths, port=0)
    try:
        # /health should respond within a couple of seconds.
        deadline = time.time() + 5
        last_exc = None
        while time.time() < deadline:
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
                if r.status_code == 200:
                    break
            except httpx.HTTPError as exc:
                last_exc = exc
            time.sleep(0.05)
        else:
            raise AssertionError(f"health never responded: {last_exc}")
        body = r.json()
        assert body["supervisor"]["status"] == "running"
        assert body["supervisor"]["pid"] is not None
        # PID file written
        assert tmp_paths.pid_file.exists()
        assert int(tmp_paths.pid_file.read_text()) == body["supervisor"]["pid"]
        # All five DBs migrated
        for kind, info in body["databases"].items():
            assert info["present"], kind
            assert info["integrity_check"] == "ok"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.integration
def test_governor_endpoint_reachable(tmp_paths):
    server, thread, port = serve_in_thread(tmp_paths, port=0)
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/governor", timeout=1.0)
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        body = r.json()
        assert "outbox_depth" in body
        assert body["kill_switched"] is False
    finally:
        server.should_exit = True
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Outbox recovery at startup: orphaned in_flight intents must be requeued.
# ---------------------------------------------------------------------------


def _backdate_claimed_at(db, intent_id: int, seconds: int) -> None:
    conn = open_db(db)
    try:
        conn.execute(
            "UPDATE intents SET claimed_at = datetime('now', ?) WHERE id = ?",
            (f"-{seconds} seconds", intent_id),
        )
    finally:
        conn.close()


def _status(db, intent_id: int) -> str:
    conn = open_db(db)
    try:
        row = conn.execute(
            "SELECT status FROM intents WHERE id = ?", (intent_id,)
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


def test_recover_orphaned_intents_requeues_stuck(migrated_paths):
    db = migrated_paths.intents_db
    iid = intents.write_intent(
        db, target="audit", op="noop", payload={}, idempotency_key="orphan-1",
    )
    # Simulate a crash mid-apply: claim it (→ in_flight) then backdate the claim
    # past the requeue threshold so it counts as orphaned.
    intents.claim_one(db)
    _backdate_claimed_at(db, iid, 600)
    assert _status(db, iid) == "in_flight"

    n = _recover_orphaned_intents(migrated_paths)

    assert n == 1
    assert _status(db, iid) == "pending"


def test_recover_orphaned_intents_offline_safe_missing_db(tmp_paths):
    # No migrations run → intents table absent. Must not raise; returns 0.
    assert _recover_orphaned_intents(tmp_paths) == 0


@pytest.mark.integration
def test_supervisor_handles_multiple_health_calls(tmp_paths):
    server, thread, port = serve_in_thread(tmp_paths, port=0)
    try:
        # Wait until up
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as c:
            for _ in range(20):
                r = c.get("/health", timeout=1.0)
                assert r.status_code == 200
    finally:
        server.should_exit = True
        thread.join(timeout=5)
