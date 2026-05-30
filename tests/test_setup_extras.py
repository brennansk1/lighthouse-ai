"""On-demand optional-extras installer — status + resolution logic.

No real pip install is exercised (that's network + multi-GB); we test the
pure logic and that the endpoints are wired.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lighthouse_ai import setup_extras
from lighthouse_ai.controlplane import create_app


@pytest.fixture
def client(migrated_paths):
    return TestClient(create_app(migrated_paths))


def test_extras_status_lists_every_bundle():
    st = setup_extras.extras_status()
    names = {e["name"] for e in st}
    # A representative spread of the declared bundles.
    assert {"faithfulness", "reranker", "js-render", "politeness"} <= names
    for e in st:
        assert isinstance(e["installed"], bool)
        assert e["label"] and e["description"]


def test_extra_packages_resolved_from_metadata():
    pkgs = setup_extras._extra_packages("faithfulness")
    assert any("sentence-transformers" in p for p in pkgs)
    # Unknown extra falls back to the dist[extra] form rather than crashing.
    assert setup_extras._extra_packages("does-not-exist") == ["lighthouse-ai[does-not-exist]"]


def test_resolve_extras_normalizes_and_filters():
    # Unknown names are dropped.
    assert setup_extras.resolve_extras(["faithfulness", "bogus"]) == ["faithfulness"]
    # None / ["all"] -> only the not-yet-installed bundles (a subset of all).
    all_names = {e.name for e in setup_extras.EXTRAS}
    assert set(setup_extras.resolve_extras(["all"])) <= all_names


def test_start_install_noop_when_nothing_to_install(monkeypatch):
    # Pretend everything is already installed → start_install does nothing.
    monkeypatch.setattr(setup_extras, "_is_installed", lambda mod: True)
    out = setup_extras.start_install(["all"])
    assert out["state"] == "done" and out["extras"] == []


def test_extras_endpoints_wired(client):
    r = client.get("/api/setup/extras")
    assert r.status_code == 200
    assert any(e["name"] == "faithfulness" for e in r.json()["extras"])
    s = client.get("/api/setup/extras/status")
    assert s.status_code == 200 and "state" in s.json()
