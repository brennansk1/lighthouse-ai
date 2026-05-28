"""Unit tests for the hardware probe and tier classification."""

from __future__ import annotations

from pathlib import Path

import pytest

from lighthouse_ai.hardware import (
    GPUInfo,
    HardwareProfile,
    classify_tier,
    load_profile,
    probe,
    write_profile,
)

# --- tier classification (pure function) ---

def test_t1_baseline_16gb_unified():
    assert classify_tier(16.0, [GPUInfo("Apple M4", 16.0, "apple")], unified=True) == "T1"


def test_t2_unified_24gb():
    assert classify_tier(24.0, [GPUInfo("Apple M3 Pro", 24.0, "apple")], unified=True) == "T2"


def test_t3_unified_64gb():
    assert classify_tier(64.0, [GPUInfo("M4 Max", 64.0, "apple")], unified=True) == "T3"


def test_t4_unified_128gb():
    assert classify_tier(128.0, [GPUInfo("M3 Ultra", 128.0, "apple")], unified=True) == "T4"


def test_t5_unified_256gb():
    assert classify_tier(256.0, [GPUInfo("M3 Ultra", 256.0, "apple")], unified=True) == "T5"


def test_t2_discrete_single_3090():
    assert classify_tier(64.0, [GPUInfo("RTX 3090", 24.0, "nvidia")], unified=False) == "T2"


def test_t4_discrete_two_4090s():
    gpus = [GPUInfo("RTX 4090", 24.0, "nvidia"), GPUInfo("RTX 4090", 24.0, "nvidia")]
    assert classify_tier(128.0, gpus, unified=False) == "T4"


def test_t5_discrete_four_h100s():
    gpus = [GPUInfo("H100", 80.0, "nvidia")] * 4
    assert classify_tier(512.0, gpus, unified=False) == "T5"


def test_cpu_only_box_falls_to_t1_when_small():
    assert classify_tier(16.0, [], unified=False) == "T1"


def test_cpu_only_fat_box_lifts_to_t3():
    assert classify_tier(64.0, [], unified=False) == "T3"


# --- probe + profile serialization ---

def test_probe_returns_well_formed_profile():
    p = probe()
    assert isinstance(p, HardwareProfile)
    assert p.platform in {"macos", "linux", "windows"}
    assert p.arch in {"arm64", "x86_64", "other"}
    assert p.total_ram_gb > 0
    assert p.cpu_cores_logical >= p.cpu_cores_physical
    assert "cpu" in p.available_backends
    assert p.suggested_tier in {"T1", "T2", "T3", "T4", "T5"}


def test_profile_roundtrips_through_disk(tmp_path: Path):
    p = probe()
    dest = tmp_path / "hw.json"
    write_profile(p, dest)
    loaded = load_profile(dest)
    assert loaded.platform == p.platform
    assert loaded.total_ram_gb == p.total_ram_gb
    assert loaded.suggested_tier == p.suggested_tier
    assert [g.name for g in loaded.gpu] == [g.name for g in p.gpu]


def test_apple_silicon_implies_unified_memory():
    p = probe()
    if p.apple_silicon:
        assert p.unified_memory is True


def test_write_profile_creates_parents(tmp_path: Path):
    dest = tmp_path / "nested" / "x" / "hw.json"
    write_profile(probe(), dest)
    assert dest.exists()


# --- backend detection edge case ---

def test_backends_always_include_cpu():
    p = probe()
    assert "cpu" in p.available_backends


@pytest.mark.parametrize("ram", [0.5, 1.0, 8.0])
def test_low_ram_unified_is_t1(ram):
    assert classify_tier(ram, [GPUInfo("toy", ram, "apple")], unified=True) == "T1"
