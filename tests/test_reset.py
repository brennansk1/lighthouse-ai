"""Factory reset — module logic + the /api/reset endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lighthouse_ai.controlplane import create_app
from lighthouse_ai.persistence import open_db
from lighthouse_ai.reset import factory_reset


@pytest.fixture
def client(migrated_paths):
    return TestClient(create_app(migrated_paths))


def _seed(paths):
    c = open_db(paths.state_db)
    c.execute(
        "INSERT INTO jobs (id, mode, status, metadata_json) VALUES ('j1', 'ask', 'queued', '{}')"
    )
    c.commit()
    c.close()
    paths.config_file.write_text("[ui]\nnotify_enabled = true\n", encoding="utf-8")
    sb = paths.data_dir / "sandbox"
    sb.mkdir(parents=True, exist_ok=True)
    (sb / "upload.txt").write_text("data", encoding="utf-8")


def test_factory_reset_clears_rows_keeps_schema(migrated_paths):
    _seed(migrated_paths)
    summary = factory_reset(migrated_paths)
    # Rows gone, but the table (schema) still exists — the query must not error.
    c = open_db(migrated_paths.state_db)
    n = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    c.close()
    assert n == 0
    assert summary.tables_cleared > 0
    assert summary.kept_models is True


def test_factory_reset_removes_stores_and_config(migrated_paths):
    _seed(migrated_paths)
    factory_reset(migrated_paths)
    assert not migrated_paths.config_file.exists()
    assert not (migrated_paths.data_dir / "sandbox" / "upload.txt").exists()
    # Empty dir structure is re-created so the app keeps working.
    assert migrated_paths.corpus_dir.exists()


def test_reset_endpoint_requires_confirmation(client, migrated_paths):
    _seed(migrated_paths)
    # No confirmation -> 400, data untouched.
    r = client.post("/api/reset", json={})
    assert r.status_code == 400
    c = open_db(migrated_paths.state_db)
    assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    c.close()
    # Wrong token -> 400.
    assert client.post("/api/reset", json={"confirm": "yes"}).status_code == 400


def test_reset_endpoint_with_confirmation_wipes(client, migrated_paths):
    _seed(migrated_paths)
    r = client.post("/api/reset", json={"confirm": "RESET"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["reset"]["kept_models"] is True
    c = open_db(migrated_paths.state_db)
    assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    c.close()
