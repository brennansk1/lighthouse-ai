"""Granular generation steerability — per-role seed / temperature / top_p.

Serves the determinism/reproducibility differentiator (§6 + §27): a researcher
can lock sampling params so an experiment is reproducible, and the effective
values are recorded in provenance.

All tests are offline/deterministic — no real Ollama. A fake backend captures
the options dict that *would* be sent, and provenance is asserted on the dict
built by ``build_run_sidecar``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from lighthouse_ai.backends.ollama import ChatResponse, _sampling_to_options
from lighthouse_ai.gateway import Gateway, SamplingParams
from lighthouse_ai.governor import BUDGET_DEFAULTS, Governor
from lighthouse_ai.hardware import HardwareProfile
from lighthouse_ai.persistence import open_db
from lighthouse_ai.provenance import build_run_sidecar


@dataclass
class _CapturingOllama:
    """Fake backend that records the ``sampling`` dict handed to ``chat``."""

    fixed_text: str = "captured"
    available_flag: bool = True
    calls: list[dict] = field(default_factory=list)

    def available(self) -> bool:
        return self.available_flag

    def loaded_models(self):
        # Report every model as resident so the RAM admission guard never blocks.
        class _All:
            def __contains__(self, _x: object) -> bool:
                return True

        return _All()

    def chat(self, model: str, prompt: str, *, sampling=None, system=None) -> ChatResponse:
        self.calls.append({"model": model, "prompt": prompt, "sampling": sampling})
        return ChatResponse(text=self.fixed_text, prompt_tokens=3, completion_tokens=2, model=model)


@pytest.fixture
def stub_profile() -> HardwareProfile:
    """T1 — binds every reasoning role to Ollama per catalog/models.yaml."""
    return HardwareProfile(
        platform="macos",
        arch="arm64",
        apple_silicon=True,
        total_ram_gb=16.0,
        free_ram_gb=8.0,
        cpu_cores_physical=8,
        cpu_cores_logical=8,
        gpu=[],
        unified_memory=True,
        available_backends=["cpu", "ollama"],
        suggested_tier="T1",
    )


def _gateway(migrated_paths, stub_profile, fake, **kw) -> Gateway:
    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    return Gateway(
        g,
        migrated_paths.audit_db,
        profile=stub_profile,
        ollama=fake,
        prefer_real_backends=True,
        **kw,
    )


# --- SamplingParams unit behavior -----------------------------------------


def test_sampling_params_empty_is_noop() -> None:
    base = {"temperature": 0.2, "top_p": 0.9}
    assert SamplingParams().is_empty()
    assert SamplingParams().overlay(base) == base


def test_sampling_params_overlay_only_set_fields() -> None:
    base = {"temperature": 0.2, "top_p": 0.9, "max_tokens": 4096}
    out = SamplingParams(seed=42, temperature=0.0).overlay(base)
    assert out["seed"] == 42
    assert out["temperature"] == 0.0
    assert out["top_p"] == 0.9  # untouched
    assert out["max_tokens"] == 4096  # untouched


def test_locked_preset_forces_seed_and_zero_temperature() -> None:
    locked = SamplingParams.locked(seed=7)
    assert locked.seed == 7
    assert locked.temperature == 0.0


# --- per-call / global / per-role overrides flow to the backend -----------


def test_unset_sampling_uses_catalog_default(migrated_paths, stub_profile) -> None:
    """No steerability config → backend gets the catalog's per-role sampling."""
    fake = _CapturingOllama()
    gw = _gateway(migrated_paths, stub_profile, fake)
    gw.complete("planner", "hi")
    samp = fake.calls[0]["sampling"]
    # Catalog planner default (models.yaml): temperature 0.2, top_p 0.9.
    assert samp["temperature"] == 0.2
    assert samp["top_p"] == 0.9
    assert "seed" not in samp


def test_per_call_override_flows_to_backend(migrated_paths, stub_profile) -> None:
    fake = _CapturingOllama()
    gw = _gateway(migrated_paths, stub_profile, fake)
    gw.complete("planner", "hi", sampling=SamplingParams(seed=123, top_p=0.5))
    samp = fake.calls[0]["sampling"]
    assert samp["seed"] == 123
    assert samp["top_p"] == 0.5
    assert samp["temperature"] == 0.2  # catalog default preserved (unset knob)


def test_global_default_sampling_flows_to_backend(migrated_paths, stub_profile) -> None:
    fake = _CapturingOllama()
    gw = _gateway(
        migrated_paths,
        stub_profile,
        fake,
        default_sampling=SamplingParams(seed=99, temperature=0.0),
    )
    gw.complete("planner", "hi")
    samp = fake.calls[0]["sampling"]
    assert samp["seed"] == 99
    assert samp["temperature"] == 0.0


def test_per_role_override_only_affects_that_role(migrated_paths, stub_profile) -> None:
    fake = _CapturingOllama()
    gw = _gateway(
        migrated_paths,
        stub_profile,
        fake,
        sampling={"planner": SamplingParams(seed=555, temperature=0.0)},
    )
    gw.complete("planner", "a")
    gw.complete("researcher", "b")
    planner_samp = fake.calls[0]["sampling"]
    researcher_samp = fake.calls[1]["sampling"]
    assert planner_samp["seed"] == 555
    assert planner_samp["temperature"] == 0.0
    # researcher untouched: catalog default, no seed.
    assert "seed" not in researcher_samp
    assert researcher_samp["temperature"] == 0.3


def test_per_call_override_beats_per_role_and_default(migrated_paths, stub_profile) -> None:
    fake = _CapturingOllama()
    gw = _gateway(
        migrated_paths,
        stub_profile,
        fake,
        default_sampling=SamplingParams(seed=1),
        sampling={"planner": SamplingParams(seed=2)},
    )
    gw.complete("planner", "hi", sampling=SamplingParams(seed=3))
    assert fake.calls[0]["sampling"]["seed"] == 3


# --- locked / deterministic mode ------------------------------------------


def test_locked_mode_forces_seed_and_zero_temp(migrated_paths, stub_profile) -> None:
    fake = _CapturingOllama()
    gw = _gateway(migrated_paths, stub_profile, fake, locked=True)
    gw.complete("planner", "hi")
    gw.complete("synthesizer", "hi")
    for call in fake.calls:
        assert call["sampling"]["temperature"] == 0.0
        assert call["sampling"]["seed"] == 0


def test_locked_mode_options_are_deterministic_for_ollama(migrated_paths, stub_profile) -> None:
    """The captured sampling dict translates to Ollama options with temp 0 + seed."""
    fake = _CapturingOllama()
    gw = _gateway(migrated_paths, stub_profile, fake, locked=True)
    gw.complete("planner", "hi")
    opts = _sampling_to_options(fake.calls[0]["sampling"])
    assert opts["temperature"] == 0.0
    assert opts["seed"] == 0


# --- effective_sampling resolver ------------------------------------------


def test_effective_sampling_is_side_effect_free(migrated_paths, stub_profile) -> None:
    fake = _CapturingOllama()
    gw = _gateway(migrated_paths, stub_profile, fake, sampling={"planner": SamplingParams(seed=8)})
    eff = gw.effective_sampling("planner")
    assert eff["seed"] == 8
    assert fake.calls == []  # resolving did not issue a completion


# --- provenance records the effective sampling params ---------------------


def test_provenance_sidecar_records_sampling(migrated_paths, stub_profile) -> None:
    fake = _CapturingOllama()
    gw = _gateway(migrated_paths, stub_profile, fake, locked=True)
    sampling_prov = gw.sampling_provenance()
    sidecar = build_run_sidecar(
        draft_id="d-1",
        job_id="job-1",
        question="Q?",
        mode="deep-dive",
        backends={"planner": "qwen3:8b"},
        source_count=0,
        sampling=sampling_prov,
    )
    assert sidecar["lighthouse:sampling"]["locked"] is True
    planner = sidecar["lighthouse:sampling"]["roles"]["planner"]
    assert planner["temperature"] == 0.0
    assert planner["seed"] == 0
    # Also recorded on the activity for PROV consumers.
    assert sidecar["activity"]["lighthouse:sampling"]["locked"] is True


def test_provenance_sidecar_omits_sampling_when_unset() -> None:
    """Backward-compatible: no ``sampling`` arg → no new key (shape unchanged)."""
    sidecar = build_run_sidecar(
        draft_id="d-2",
        job_id="job-2",
        question="Q?",
        mode="deep-dive",
        backends={},
        source_count=0,
    )
    assert "lighthouse:sampling" not in sidecar
    assert "lighthouse:sampling" not in sidecar["activity"]


def test_sampling_provenance_covers_every_bound_role(migrated_paths, stub_profile) -> None:
    fake = _CapturingOllama()
    gw = _gateway(migrated_paths, stub_profile, fake)
    prov = gw.sampling_provenance()
    assert "planner" in prov["roles"]
    assert prov["locked"] is False


# --- audit log carries the effective sampling -----------------------------


def test_audit_event_records_effective_sampling(migrated_paths, stub_profile) -> None:
    fake = _CapturingOllama()
    gw = _gateway(
        migrated_paths, stub_profile, fake, sampling={"planner": SamplingParams(seed=321)}
    )
    gw.complete("planner", "hi", job_id="trace-s")
    conn = open_db(migrated_paths.audit_db)
    try:
        row = conn.execute(
            "SELECT payload_json FROM audit_events "
            "WHERE event_type='model_call' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    payload = json.loads(row[0])
    assert payload["sampling"]["seed"] == 321
