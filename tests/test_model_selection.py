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


def test_estimate_resident_param_hint():
    from lighthouse_ai.gateway import estimate_resident_gb
    assert estimate_resident_gb("some-14b-model") > estimate_resident_gb("some-8b-model")


def test_gateway_falls_back_to_mock_when_lowmem(migrated_paths):
    """Real Ollama binding degrades to mock (not crash) when RAM is tight."""
    from dataclasses import dataclass
    from lighthouse_ai.gateway import Gateway
    from lighthouse_ai.governor import BUDGET_DEFAULTS, Governor
    from lighthouse_ai.backends.ollama import ChatResponse

    @dataclass
    class _Fake:
        def available(self): return True
        def loaded_models(self): return []
        def chat(self, *a, **k): return ChatResponse("REAL", 1, 1, "m")

    g = Governor(migrated_paths.state_db, BUDGET_DEFAULTS)
    gw = Gateway(g, migrated_paths.audit_db, profile=_profile(25.77, tier="T1"),
                 ollama=_Fake(), overrides={"planner": "llama3.1:8b"})
    import lighthouse_ai.gateway as gmod
    orig = gmod.enough_ram_for
    gmod.enough_ram_for = lambda model, **kw: False
    try:
        resp = gw.complete("planner", "hi")
    finally:
        gmod.enough_ram_for = orig
    assert "[mock" in resp.text


# --- chosen_models.yaml records the advisory ---

def test_write_chosen_models_records_paging(tmp_path):
    from lighthouse_ai.gateway import write_chosen_models
    doc = write_chosen_models(tmp_path / "chosen.yaml", _profile(25.77, tier="T2"))
    assert doc["roles"]["planner"]["model"] == "qwen3.6-35b-a3b"
    assert doc["llm_budget_gb"] == pytest.approx(15.47, abs=0.01)
    assert "qwen3.6-35b-a3b" in doc["paging_from_ssd"]
