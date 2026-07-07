"""Unit tests for the Model Gateway."""

from __future__ import annotations

import json

import pytest

from lighthouse_ai.gateway import (
    DriftDetected,
    Gateway,
    bindings_for_tier,
    check_drift,
    fingerprint,
    fingerprint_unknown,
    load_catalog,
    load_chosen_models,
    write_chosen_models,
)
from lighthouse_ai.governor import BUDGET_DEFAULTS, Governor
from lighthouse_ai.hardware import HardwareProfile
from lighthouse_ai.persistence import open_db


@pytest.fixture
def stub_profile() -> HardwareProfile:
    return HardwareProfile(
        platform="macos", arch="arm64", apple_silicon=True,
        total_ram_gb=64.0, free_ram_gb=32.0,
        cpu_cores_physical=10, cpu_cores_logical=10,
        gpu=[], unified_memory=True,
        available_backends=["cpu", "ollama"],
        suggested_tier="T3",
    )


def test_catalog_loads_with_all_five_tiers():
    cat = load_catalog()
    assert set(cat["tiers"].keys()) == {"T1", "T2", "T3", "T4", "T5"}
    assert "planner" in cat["roles"]["T1"]


def test_bindings_for_tier_includes_fixed_roles():
    b = bindings_for_tier("T3")
    assert "planner" in b
    assert "synthesizer" in b
    assert "embedding" in b
    assert "reranker" in b
    assert b["embedding"].backend == "native"


def test_write_chosen_models_creates_file(tmp_path, stub_profile):
    dest = tmp_path / "chosen.yaml"
    doc = write_chosen_models(dest, stub_profile)
    assert dest.exists()
    assert doc["hardware_tier"] == "T3"
    loaded = load_chosen_models(dest)
    assert "planner" in loaded["roles"]
    assert "fingerprints" in loaded


def test_fingerprint_unknown_is_stable_and_distinct():
    a = fingerprint_unknown("qwen3:8b", "ollama")
    b = fingerprint_unknown("qwen3:8b", "ollama")
    c = fingerprint_unknown("qwen3:8b", "mlx")
    assert a.registry_digest_sha256 == b.registry_digest_sha256
    assert a.registry_digest_sha256 != c.registry_digest_sha256


def test_fingerprint_dispatches_to_ollama_when_present():
    # On CI without ollama we still get a valid (unknown-source) fingerprint.
    fp = fingerprint("qwen3:8b-q4_k_m", "ollama")
    assert fp.model_string == "qwen3:8b-q4_k_m"
    assert len(fp.registry_digest_sha256) == 64


def test_check_drift_passes_when_recorded_matches(tmp_path, stub_profile):
    dest = tmp_path / "chosen.yaml"
    write_chosen_models(dest, stub_profile)
    # Same machine, just wrote it — no drift.
    drift = check_drift(dest)
    assert drift == []


def test_check_drift_raises_when_recorded_differs(tmp_path, stub_profile):
    dest = tmp_path / "chosen.yaml"
    write_chosen_models(dest, stub_profile)
    # Mutate the file to simulate model drift.
    import yaml as _yaml
    doc = _yaml.safe_load(dest.read_text())
    first_model = next(iter(doc["fingerprints"]))
    doc["fingerprints"][first_model]["registry_digest_sha256"] = "0" * 64
    dest.write_text(_yaml.safe_dump(doc))
    with pytest.raises(DriftDetected):
        check_drift(dest)
    # With --allow-drift returns the list non-empty.
    drift = check_drift(dest, allow_drift=True)
    assert drift and drift[0]["model"] == first_model


# --- Gateway proper ---

def test_gateway_routes_role_and_records_audit(migrated_paths, stub_profile):
    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    gw = Gateway(g, migrated_paths.audit_db, profile=stub_profile)
    gw._get_ollama = lambda: None  # hermetic: force the mock path (no real ollama)
    resp = gw.complete("planner", "ping", job_id="j1")
    assert resp.role == "planner"
    assert resp.model
    assert "[mock" in resp.text
    # Audit event written.
    conn = open_db(migrated_paths.audit_db)
    try:
        rows = conn.execute(
            "SELECT actor, event_type, payload_json FROM audit_events "
            "WHERE event_type = 'model_call'"
        ).fetchall()
    finally:
        conn.close()
    assert rows
    payload = json.loads(rows[0][2])
    assert payload["role"] == "planner"
    assert payload["job_id"] == "j1"
    assert "fingerprint" in payload


def test_gateway_unknown_role_raises(migrated_paths, stub_profile):
    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    gw = Gateway(g, migrated_paths.audit_db, profile=stub_profile)
    with pytest.raises(KeyError):
        gw.complete("not_a_role", "hi")


def test_complete_structured_uses_aux_when_bound(migrated_paths, stub_profile):
    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    gw = Gateway(g, migrated_paths.audit_db, profile=stub_profile)
    gw._get_ollama = lambda: None  # hermetic: force the mock path (no real ollama)
    resp = gw.complete_structured("score this", job_id="j1")
    # aux_context is bound in the tier catalog → structured calls route to it,
    # keeping extraction/scoring off the heavy reasoner.
    assert resp.role == "aux_context"
    assert "[mock" in resp.text


def test_complete_structured_falls_back_to_researcher(migrated_paths, stub_profile):
    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    gw = Gateway(g, migrated_paths.audit_db, profile=stub_profile)
    # Simulate a gateway with no aux binding → must fall back, not raise.
    gw._bindings.pop("aux_context", None)
    resp = gw.complete_structured("score this")
    assert resp.role == "researcher"


def test_gateway_with_chosen_models_uses_recorded_bindings(
        tmp_path, migrated_paths, stub_profile):
    from lighthouse_ai.gateway import recommend_models
    dest = tmp_path / "chosen.yaml"
    write_chosen_models(dest, stub_profile)
    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    gw = Gateway(g, migrated_paths.audit_db, chosen_models_path=dest,
                 profile=stub_profile)
    gw._get_ollama = lambda: None  # hermetic: don't serve via a real local ollama
    # The gateway resolves planner via the recorded (budget-aware) yaml.
    resp = gw.complete("planner", "ping")
    assert resp.model == recommend_models(stub_profile)["planner"].model


def test_admission_refusal_degrades_to_smaller_real_model(migrated_paths, stub_profile):
    """When the role's model can't fit live RAM, complete() serves the largest
    INSTALLED model that DOES fit — a real answer, not a silent mock (the
    mock-masquerade root-cause fix)."""
    from lighthouse_ai.backends.ollama import ChatResponse

    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    gw = Gateway(g, migrated_paths.audit_db, profile=stub_profile)

    class _FakeOllama:
        def chat(self, model, prompt, **kw):
            return ChatResponse(text=f"real answer from {model}", prompt_tokens=1,
                                completion_tokens=1, model=model)

        def loaded_models(self):
            return []

    gw._get_ollama = lambda: _FakeOllama()
    primary = gw.binding("researcher").model
    # primary can't fit (huge need); the smaller fallback reserves nothing (fits).
    gw._need_gb = lambda ollama, m: 999.0 if m == primary else 0.0
    gw._fallback_candidates = lambda ollama, p: ["small-real-model"]

    resp = gw.complete("researcher", "hi", job_id="j1")
    assert resp.model == "small-real-model"
    assert "real answer" in resp.text
    counts = gw.drain_backends()
    assert counts.get("mock-lowmem", 0) == 0  # did NOT mock
    assert counts.get("mock", 0) == 0


def test_admission_mocks_only_when_nothing_fits(migrated_paths, stub_profile):
    """If NO installed model fits, it still falls to the low-memory mock."""
    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    gw = Gateway(g, migrated_paths.audit_db, profile=stub_profile)

    class _FakeOllama:
        def chat(self, model, prompt, **kw):  # pragma: no cover - never admitted
            raise AssertionError("should not be called when nothing fits")

        def loaded_models(self):
            return []

    gw._get_ollama = lambda: _FakeOllama()
    gw._need_gb = lambda ollama, m: 999.0            # nothing fits
    gw._fallback_candidates = lambda ollama, p: ["also-too-big"]

    resp = gw.complete("researcher", "hi", job_id="j1")
    assert "[mock" in resp.text
    assert gw.drain_backends().get("mock-lowmem", 0) == 1
