"""Global pause — supervisor single-source-of-truth + control API.

The CLI `pause`/`resume` and the dashboard Pause button all set
``supervisor_state.status``; every 24/7 loop reads ``is_paused()`` each tick and
skips its work while paused, so the user can reclaim the machine.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from lighthouse_ai.controlplane import create_app
from lighthouse_ai.supervisor import is_paused, runtime_status, set_runtime_status


def test_runtime_status_default_running(migrated_paths):
    assert runtime_status(migrated_paths) == "running"
    assert is_paused(migrated_paths) is False


def test_set_runtime_status_round_trip(migrated_paths):
    set_runtime_status(migrated_paths, "paused_soft")
    assert runtime_status(migrated_paths) == "paused_soft"
    assert is_paused(migrated_paths) is True

    set_runtime_status(migrated_paths, "paused_hard")
    assert is_paused(migrated_paths) is True

    set_runtime_status(migrated_paths, "running")
    assert is_paused(migrated_paths) is False


def test_is_paused_missing_db_is_running(tmp_path):
    # A bare Paths whose state.db doesn't exist must read as running, never crash.
    from lighthouse_ai.paths import Paths

    p = Paths.for_data_dir(tmp_path) if hasattr(Paths, "for_data_dir") else None
    if p is None:
        # Fallback: just assert the helper tolerates a non-existent db path.
        from types import SimpleNamespace
        fake = SimpleNamespace(state_db=tmp_path / "nope.db")
        assert is_paused(fake) is False  # type: ignore[arg-type]
    else:
        assert is_paused(p) is False


# --- control API ------------------------------------------------------------


def _client(migrated_paths):
    return TestClient(create_app(migrated_paths))


def test_control_status_endpoint(migrated_paths):
    c = _client(migrated_paths)
    r = c.get("/api/control")
    assert r.status_code == 200
    assert r.json() == {"status": "running", "paused": False}


def test_pause_then_resume_via_api(migrated_paths):
    c = _client(migrated_paths)
    r = c.post("/api/pause", json={"hard": False})
    assert r.status_code == 200 and r.json()["paused"] is True
    assert r.json()["status"] == "paused_soft"
    # The single source of truth reflects it for the loops.
    assert is_paused(migrated_paths) is True
    assert c.get("/api/control").json()["paused"] is True

    r2 = c.post("/api/resume")
    assert r2.status_code == 200 and r2.json()["paused"] is False
    assert is_paused(migrated_paths) is False


def test_hard_pause_via_api(migrated_paths):
    c = _client(migrated_paths)
    r = c.post("/api/pause", json={"hard": True})
    assert r.json()["status"] == "paused_hard"
    assert is_paused(migrated_paths) is True


def test_pause_no_body_defaults_soft(migrated_paths):
    c = _client(migrated_paths)
    r = c.post("/api/pause")
    assert r.status_code == 200 and r.json()["status"] == "paused_soft"
