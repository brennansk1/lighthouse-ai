"""Model selection (§5.2 budget + §5.3 2026 MoE-centric table).

The per-tier role table in catalog/models.yaml is authoritative; the budget
math is advisory and flags when a tier's default will page from SSD on a
given machine. Capability-class tags are nominal (resolved at install).
"""

from __future__ import annotations

import pytest

from lighthouse_ai.gateway import (
    AUX_MODEL,
    FLOOR_MODEL,
    MODEL_FOOTPRINTS_GB,
    PAGEABLE_MOE,
    budget_report,
    model_fits,
    model_footprint_gb,
    model_pages,
    recommend_models,
)
from lighthouse_ai.hardware import GPUInfo, HardwareProfile, llm_budget_gb


def _profile(ram_gb: float, *, tier="T2", platform="macos", unified=True,
             gpus=None) -> HardwareProfile:
    return HardwareProfile(
        platform=platform, arch="arm64", apple_silicon=(platform == "macos"),
        total_ram_gb=ram_gb, free_ram_gb=ram_gb / 2,
        cpu_cores_physical=10, cpu_cores_logical=10,
        gpu=gpus if gpus is not None else ([GPUInfo("Apple", ram_gb, "apple")] if unified else []),
        unified_memory=unified, available_backends=["cpu", "ollama"],
        suggested_tier=tier,
    )


# --- budget math (§5.2) ---

def test_budget_macos_24gb():
    assert llm_budget_gb(_profile(25.77)) == pytest.approx(15.47, abs=0.01)


def test_budget_linux_smaller_os_reserve():
    p = _profile(25.77, platform="linux", unified=False, gpus=[])
    assert llm_budget_gb(p) == pytest.approx(17.47, abs=0.01)


def test_budget_discrete_gpu_uses_vram():
    p = _profile(64.0, platform="linux", unified=False,
                 gpus=[GPUInfo("RTX 4090", 24.0, "nvidia")])
    assert llm_budget_gb(p) == pytest.approx(20.5, abs=0.01)


# --- footprint + MoE paging ---

def test_footprint_table_has_expected_classes():
    for m in ("qwen3.5-9b", "qwen3.6-35b-a3b", "qwen3.6-27b",
              "deepseek-v4-flash", "deepseek-v4-pro", "phi-4-mini"):
        assert m in MODEL_FOOTPRINTS_GB


def test_dense_model_must_fit():
    assert not model_fits("qwen3.6-27b", 15.47)  # ~17 GB dense, not MoE


def test_moe_model_pages_when_over_budget():
    assert model_fits("qwen3.6-35b-a3b", 15.47)
    assert model_pages("qwen3.6-35b-a3b", 15.47)


def test_small_model_fits_outright():
    assert model_fits("qwen3.5-9b", 15.47)
    assert not model_pages("qwen3.5-9b", 15.47)


def test_pageable_set_is_all_moe():
    assert "qwen3.6-35b-a3b" in PAGEABLE_MOE
    assert "deepseek-v4-pro" in PAGEABLE_MOE
    assert "qwen3.5-9b" not in PAGEABLE_MOE


def test_floor_and_aux_constants():
    assert FLOOR_MODEL == "qwen3.5-9b"
    assert AUX_MODEL == "qwen3.5-9b"
    assert model_footprint_gb("qwen3.5-9b") == 7.0


# --- recommend_models follows the curated per-tier table ---

@pytest.mark.parametrize("tier,planner,researcher,synthesizer,aux", [
    ("T1", "qwen3.5-9b", "qwen3.5-9b", "qwen3.5-9b", "phi-4-mini"),
    ("T2", "qwen3.6-35b-a3b", "qwen3.6-35b-a3b", "qwen3.6-35b-a3b", "qwen3.5-9b"),
    ("T3", "qwen3.6-35b-a3b", "qwen3.6-35b-a3b", "qwen3.6-27b", "qwen3.5-9b"),
    ("T4", "qwen3.6-35b-a3b", "qwen3.6-35b-a3b", "deepseek-v4-flash", "qwen3.5-9b"),
    ("T5", "deepseek-v4-pro", "deepseek-v4-pro", "deepseek-v4-pro", "qwen3.5-9b"),
])
def test_recommend_matches_table(tier, planner, researcher, synthesizer, aux):
    rec = recommend_models(_profile(32.0, tier=tier))
    assert rec["planner"].model == planner
    assert rec["researcher"].model == researcher
    assert rec["synthesizer"].model == synthesizer
    assert rec["aux_context"].model == aux


def test_t2_default_is_the_moe():
    """This machine (24 GB T2) gets the 35B-A3B MoE — it pages but runs."""
    rec = recommend_models(_profile(25.77, tier="T2"))
    assert rec["planner"].model == "qwen3.6-35b-a3b"


def test_fixed_roles_unchanged():
    rec = recommend_models(_profile(32.0, tier="T2"))
    assert rec["embedding"].model == "bge-m3"
    assert rec["reranker"].model == "qwen3-reranker-0.6b"


# --- budget_report advisory ---

def test_budget_report_flags_paging_on_24gb_t2():
    rep = budget_report(_profile(25.77, tier="T2"))
    assert rep["budget_gb"] == pytest.approx(15.47, abs=0.01)
    assert "qwen3.6-35b-a3b" in rep["paging"]
    assert rep["roles"]["planner"]["pages_from_ssd"] is True


def test_budget_report_no_paging_on_32gb_t2():
    rep = budget_report(_profile(34.4, tier="T2"))
    assert "qwen3.6-35b-a3b" not in rep["paging"]
    assert rep["roles"]["planner"]["pages_from_ssd"] is False


def test_budget_report_t1_no_paging():
    rep = budget_report(_profile(17.2, tier="T1"))
    assert rep["paging"] == []


# --- pull preflight (disk safety) ---

def test_estimate_download_known_vs_unknown():
    from lighthouse_ai.gateway import estimate_download_gb
    assert estimate_download_gb("qwen3.6-35b-a3b") > 0
    assert estimate_download_gb("totally-unknown-model") == 0.0


def test_preflight_ok_with_ample_disk():
    from lighthouse_ai.gateway import preflight_pull
    pf = preflight_pull("qwen3.5-9b", free_disk_gb=100.0)
    assert pf.ok and pf.headroom_after_gb > 5.0


def test_preflight_refuses_when_low_disk():
    from lighthouse_ai.gateway import preflight_pull
    pf = preflight_pull("qwen3.6-35b-a3b", free_disk_gb=10.0)
    assert not pf.ok
    assert "safety margin" in pf.reason


def test_preflight_flags_large_pull():
    from lighthouse_ai.gateway import preflight_pull
    pf = preflight_pull("deepseek-v4-flash", free_disk_gb=1000.0)
    assert pf.is_large and pf.ok


def test_preflight_unknown_size_needs_headroom():
    from lighthouse_ai.gateway import preflight_pull
    assert preflight_pull("mystery", free_disk_gb=50.0).ok
    assert not preflight_pull("mystery", free_disk_gb=3.0).ok


def test_preflight_refuses_35b_on_this_machine():
    """Regression: 24 GB box with ~10 GB free must REFUSE the 35B-A3B pull
    rather than fill the disk and crash the OS."""
    from lighthouse_ai.gateway import preflight_pull
    assert not preflight_pull("qwen3.6-35b-a3b", free_disk_gb=9.8).ok


# --- runtime RAM guard ---

def test_enough_ram_blocks_when_insufficient():
    from lighthouse_ai.gateway import enough_ram_for
    assert not enough_ram_for("llama3.1:8b", available_gb=3.9)


def test_enough_ram_allows_when_plenty():
    from lighthouse_ai.gateway import enough_ram_for
    assert enough_ram_for("llama3.1:8b", available_gb=20.0)


def test_enough_ram_moe_always_allowed():
    from lighthouse_ai.gateway import enough_ram_for
    assert enough_ram_for("qwen3.6-35b-a3b", available_gb=2.0)


def test_runtime_moe_tag_recognized_as_pageable():
    """Regression: a fine-grained MoE bound to a *real installed tag* (e.g.
    ``qwen3:30b-a3b`` — 30B total, 3B active) pages experts from SSD and must
    be treated as pageable, not estimated at its full 30B resident footprint.

    The catalog ``PAGEABLE_MOE`` set only holds capability-class names; at run
    time roles are rebound to actual Ollama tags. Without tag-pattern detection
    the admission queue wrongly denies these and silently degrades to the mock,
    defeating the SSD-paging feature on exactly the 24 GB box this targets."""
    from lighthouse_ai.gateway import enough_ram_for, is_pageable_moe
    assert is_pageable_moe("qwen3:30b-a3b")
    assert is_pageable_moe("qwen3-coder:30b-a3b")
    assert is_pageable_moe("qwen3.5-122b-a10b")
    assert is_pageable_moe("mixtral:8x7b")  # classic sparse-MoE notation
    # A dense model is NOT pageable.
    assert not is_pageable_moe("qwen3:32b")
    assert not is_pageable_moe("llama3.1:8b")
    # The whole point: the paging MoE is allowed even when RAM is far too small
    # for its full weights, just like the catalog-class MoE above.
    assert enough_ram_for("qwen3:30b-a3b", available_gb=2.0)
    # ...while a dense 30B is still blocked when it won't fit.
    assert not enough_ram_for("qwen3:32b", available_gb=2.0)


def test_estimate_resident_param_hint():
    from lighthouse_ai.gateway import estimate_resident_gb
    assert estimate_resident_gb("some-14b-model") > estimate_resident_gb("some-8b-model")


# --- KV/context headroom: admission reserves more than static weights ---

def test_resident_includes_kv_headroom_over_weights():
    """OOM-safety: the resident estimate must exceed weights-only, because the
    KV cache + activations grow with context and would otherwise swap a model
    whose weights barely fit."""
    from lighthouse_ai.gateway import estimate_resident_gb, estimate_weights_gb
    for m in ("qwen3.5-9b", "qwen3.6-27b", "llama3.1:8b", "some-14b-model"):
        assert estimate_resident_gb(m) > estimate_weights_gb(m) > 0


def test_kv_headroom_scales_with_model_size():
    """Bigger models pay more KV/activation headroom (per-token cost tracks
    hidden size), so the headroom term must grow with weight size."""
    from lighthouse_ai.gateway import _kv_context_headroom_gb
    assert _kv_context_headroom_gb(20.0) > _kv_context_headroom_gb(5.0)
    assert _kv_context_headroom_gb(0.0) == 0.0


def test_27b_resident_exceeds_footprint_for_kv():
    """A dense 27B's live resident need (with KV headroom) must be at least its
    curated footprint — admission must not under-reserve relative to the table
    that already counts some KV. Regression: the old weights-only estimate came
    in *under* the footprint, under-reserving the KV cache."""
    from lighthouse_ai.gateway import estimate_resident_gb, model_footprint_gb
    assert estimate_resident_gb("qwen3.6-27b") >= model_footprint_gb("qwen3.6-27b")


def test_enough_ram_tighter_with_kv_headroom():
    """A model whose *weights* fit but whose weights+KV+margin do not is now
    correctly blocked, where a weights-only check would have admitted it."""
    from lighthouse_ai.gateway import (
        enough_ram_for,
        estimate_resident_gb,
        estimate_weights_gb,
    )
    weights = estimate_weights_gb("qwen3.6-27b")
    resident = estimate_resident_gb("qwen3.6-27b")
    # Available sits between weights+margin and resident+margin: the KV headroom
    # is exactly what flips this from "admit" to "block".
    avail = weights + 1.5 + 0.5
    assert avail < resident + 1.5
    assert not enough_ram_for("qwen3.6-27b", available_gb=avail)


# --- budget-aware resolver steps UP to a paging MoE, not down to dense ---

def test_resolver_prefers_paging_moe_over_small_dense_when_tight():
    """On a tight-RAM box the resolver must pick the larger MoE tag (which pages
    from SSD and runs) over stepping all the way down to a small dense model —
    using the hardware well instead of leaving capability on the table."""
    from lighthouse_ai.gateway import resolve_against_installed
    p = _profile(25.77, tier="T2")
    installed = ["qwen3:32b", "qwen3:30b-a3b", "qwen3:8b"]
    # Tight live budget (~10 GB free): the dense 32B does not fit, but the
    # 30B-a3b MoE pages and is chosen — not the 8B floor.
    out = resolve_against_installed(p, installed, budget_gb=10.0)
    assert out["planner"] == "qwen3:30b-a3b"


def test_resolver_picks_largest_dense_that_fits():
    """When RAM is ample the resolver picks the largest dense tag that fits the
    budget (best model that fits), not an over-conservative floor."""
    from lighthouse_ai.gateway import resolve_against_installed
    p = _profile(64.0, tier="T3")
    installed = ["qwen3:32b", "qwen2.5:14b", "qwen3:8b"]
    out = resolve_against_installed(p, installed, budget_gb=40.0)
    assert out["planner"] == "qwen3:32b"


def test_resolver_steps_down_when_dense_too_big():
    """No MoE installed and the big dense tag won't fit → step down to the
    largest dense tag that does, gracefully (not crash, not floor blindly)."""
    from lighthouse_ai.gateway import resolve_against_installed
    p = _profile(25.77, tier="T2")
    installed = ["qwen3:32b", "qwen2.5:14b", "qwen3:8b"]
    # ~13 GB budget: 32B (≈21 GB live) and 14B (≈10 GB) — 14B fits, 32B doesn't.
    out = resolve_against_installed(p, installed, budget_gb=13.0)
    assert out["planner"] == "qwen2.5:14b"


def test_gateway_falls_back_to_mock_when_lowmem(migrated_paths):
    """Real Ollama binding degrades to mock (not crash) when RAM is tight."""
    from dataclasses import dataclass

    from lighthouse_ai.backends.ollama import ChatResponse
    from lighthouse_ai.gateway import Gateway
    from lighthouse_ai.governor import BUDGET_DEFAULTS, Governor

    @dataclass
    class _Fake:
        def available(self): return True
        def loaded_models(self): return []
        def chat(self, *a, **k): return ChatResponse("REAL", 1, 1, "m")

    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    gw = Gateway(g, migrated_paths.audit_db, profile=_profile(25.77, tier="T1"),
                 ollama=_Fake(), overrides={"planner": "llama3.1:8b"})
    from lighthouse_ai.governor.ollama_queue import AdmissionConfig
    gw._admission = AdmissionConfig(wait_timeout_s=0.0)  # refuse now, don't poll
    import lighthouse_ai.gateway as gmod
    orig = gmod.estimate_resident_gb
    # Model isn't resident and would need more RAM than the host has → the
    # admission queue refuses it and the gateway falls back to the low-mem mock.
    gmod.estimate_resident_gb = lambda model: 1_000_000.0
    try:
        resp = gw.complete("planner", "hi")
    finally:
        gmod.estimate_resident_gb = orig
    assert "[mock" in resp.text


# --- chosen_models.yaml records the advisory ---

def test_write_chosen_models_records_paging(tmp_path):
    from lighthouse_ai.gateway import write_chosen_models
    doc = write_chosen_models(tmp_path / "chosen.yaml", _profile(25.77, tier="T2"))
    assert doc["roles"]["planner"]["model"] == "qwen3.6-35b-a3b"
    assert doc["llm_budget_gb"] == pytest.approx(15.47, abs=0.01)
    assert "qwen3.6-35b-a3b" in doc["paging_from_ssd"]


# --- adaptability for small machines (all-machines support) ---

def test_adaptive_ram_floor_reflects_smallest_installed_model():
    """The dispatch RAM gate must adapt to the box: a machine whose smallest
    reasoning model is a 1B clears on far less free RAM than an 8B-only box."""
    from lighthouse_ai.gateway import smallest_reasoning_resident_gb
    tiny = smallest_reasoning_resident_gb(["llama3.2:1b", "bge-m3"])
    big = smallest_reasoning_resident_gb(["qwen3:8b", "bge-m3"])
    assert tiny < 2.5, f"1B floor too high: {tiny}"
    assert big > 5.0, f"8B floor too low: {big}"
    assert tiny < big
    # Embedding/reranker tags are ignored; empty → safe default.
    assert smallest_reasoning_resident_gb(["bge-m3", "qwen3-reranker-0.6b"]) == 4.0
    assert smallest_reasoning_resident_gb([]) == 4.0


def test_low_budget_box_steps_down_to_tiny_model_not_mock():
    """On a tight live-RAM budget the resolver picks the smallest installed
    reasoning model (so a 4–8 GB box runs a real tiny model) rather than leaving
    nothing and degrading to the mock."""
    from lighthouse_ai.gateway import resolve_against_installed
    prof = _profile(8.0, tier="T1")
    installed = ["qwen3:8b", "llama3.2:1b", "bge-m3"]
    tight = resolve_against_installed(prof, installed, budget_gb=2.0)
    assert tight["planner"] == "llama3.2:1b"
    roomy = resolve_against_installed(prof, installed, budget_gb=10.0)
    assert roomy["planner"] == "qwen3:8b"
