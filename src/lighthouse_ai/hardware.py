"""Hardware probe — typed HardwareProfile per design §5.1.

The probe is *passive*: it never installs anything or escalates privilege.
Backend detection is by import + binary check. GPU detection uses pynvml
when available; absent that, we fall back to ``nvidia-smi`` parsing, and on
Apple Silicon we infer Metal availability from the ``mlx`` import success.

Tier classification (§5.4):
  T1: 16 GB unified
  T2: 24-32 GB unified OR ≥24 GB VRAM
  T3: 48-64 GB unified
  T4: 96-128 GB unified OR 2× high-VRAM GPU OR A6000-class
  T5: ≥256 GB unified OR multi-high-VRAM-GPU

The chosen tier is the *suggested* default — the user can override in
``config.toml`` under ``[hardware] detected_tier``.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import psutil

PlatformId = Literal["macos", "linux", "windows"]
ArchId = Literal["arm64", "x86_64", "other"]
BackendId = Literal["ollama", "mlx", "llamacpp", "vllm", "sglang", "cuda", "metal", "cpu"]
Tier = Literal["T1", "T2", "T3", "T4", "T5"]


@dataclass(frozen=True)
class GPUInfo:
    name: str
    vram_gb: float
    vendor: Literal["nvidia", "amd", "apple", "other"] = "other"


@dataclass(frozen=True)
class HardwareProfile:
    platform: PlatformId
    arch: ArchId
    apple_silicon: bool
    total_ram_gb: float
    free_ram_gb: float
    cpu_cores_physical: int
    cpu_cores_logical: int
    gpu: list[GPUInfo] = field(default_factory=list)
    unified_memory: bool = False
    available_backends: list[BackendId] = field(default_factory=list)
    docker_available: bool = False
    bubblewrap_available: bool = False
    sandbox_exec_available: bool = False
    disk_total_gb: float = 0.0
    disk_free_gb: float = 0.0
    suggested_tier: Tier = "T1"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["gpu"] = [asdict(g) for g in self.gpu]
        return d


def _detect_platform() -> PlatformId:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"  # best-effort fallback


def _detect_arch() -> ArchId:
    m = platform.machine().lower()
    if m in {"arm64", "aarch64"}:
        return "arm64"
    if m in {"x86_64", "amd64"}:
        return "x86_64"
    return "other"


def _bytes_to_gb(n: int | float) -> float:
    return round(float(n) / 1e9, 2)


def _binary_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _detect_nvidia_gpus() -> list[GPUInfo]:
    """Try pynvml, then nvidia-smi, then give up."""
    try:
        import pynvml  # type: ignore
    except ImportError:
        pynvml = None  # type: ignore[assignment]
    if pynvml is not None:
        try:
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            gpus: list[GPUInfo] = []
            for i in range(count):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(h)
                if isinstance(name, bytes):
                    name = name.decode()
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                gpus.append(GPUInfo(name=name, vram_gb=_bytes_to_gb(mem.total), vendor="nvidia"))
            pynvml.nvmlShutdown()
            return gpus
        except Exception:
            pass
    if _binary_exists("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout
            gpus = []
            for line in out.strip().splitlines():
                name, mem_mb = [s.strip() for s in line.split(",", 1)]
                gpus.append(GPUInfo(name=name, vram_gb=round(int(mem_mb) / 1024, 2),
                                    vendor="nvidia"))
            return gpus
        except Exception:
            return []
    return []


def _detect_amd_gpus() -> list[GPUInfo]:
    if not _binary_exists("rocm-smi"):
        return []
    try:
        out = subprocess.run(
            ["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--json"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        data = json.loads(out)
        gpus = []
        for _key, info in data.items():
            name = info.get("Card series", info.get("Card model", "amd"))
            vram_bytes = int(info.get("VRAM Total Memory (B)", 0))
            if vram_bytes:
                gpus.append(GPUInfo(name=name, vram_gb=_bytes_to_gb(vram_bytes), vendor="amd"))
        return gpus
    except Exception:
        return []


def _detect_apple_gpu(total_ram_gb: float) -> list[GPUInfo]:
    """Apple Silicon: GPU shares unified memory. Report the unified pool size."""
    chip = "Apple Silicon"
    try:
        out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                             capture_output=True, text=True, timeout=2, check=True).stdout
        if out.strip():
            chip = out.strip()
    except Exception:
        pass
    return [GPUInfo(name=chip, vram_gb=total_ram_gb, vendor="apple")]


def _detect_backends(plat: PlatformId, has_apple: bool, has_nvidia: bool) -> list[BackendId]:
    backends: list[BackendId] = ["cpu"]
    if _binary_exists("ollama"):
        backends.append("ollama")
    try:
        import mlx.core  # type: ignore  # noqa: F401
        if has_apple:
            backends.extend(["mlx", "metal"])
    except ImportError:
        pass
    try:
        import llama_cpp  # type: ignore  # noqa: F401
        backends.append("llamacpp")
    except ImportError:
        pass
    if has_nvidia:
        backends.append("cuda")
        try:
            import vllm  # type: ignore  # noqa: F401
            backends.append("vllm")
        except ImportError:
            pass
        try:
            import sglang  # type: ignore  # noqa: F401
            backends.append("sglang")
        except ImportError:
            pass
    return backends


# --- memory budget (§5.2) ----------------------------------------------

#: Reserves carved out before the LLM gets memory, per design §5.2.
OS_RESERVE_MACOS_GB = 6.0
OS_RESERVE_OTHER_GB = 4.0
EMBEDDINGS_RESERVE_GB = 1.5
QDRANT_RESERVE_GB = 0.8
CONCURRENCY_BUFFER_GB = 2.0


def llm_budget_gb(profile: HardwareProfile) -> float:
    """RAM (or VRAM) available to the reasoning LLM, per §5.2.

    For unified-memory machines (Apple Silicon) we budget against total RAM.
    For discrete-GPU machines we budget against aggregate VRAM, since the
    model lives on the card. CPU-only boxes fall back to RAM.
    """
    os_reserve = OS_RESERVE_MACOS_GB if profile.platform == "macos" else OS_RESERVE_OTHER_GB
    overhead = os_reserve + EMBEDDINGS_RESERVE_GB + QDRANT_RESERVE_GB + CONCURRENCY_BUFFER_GB
    if not profile.unified_memory and profile.gpu:
        vram = sum(g.vram_gb for g in profile.gpu)
        # GPUs don't pay the OS reserve from VRAM, only embeddings/qdrant if
        # co-located; keep a small buffer.
        return round(vram - EMBEDDINGS_RESERVE_GB - CONCURRENCY_BUFFER_GB, 2)
    return round(profile.total_ram_gb - overhead, 2)


def classify_tier(total_ram_gb: float, gpus: list[GPUInfo], unified: bool) -> Tier:
    """Suggest a tier from §5.3/§5.4. RAM-dominant for unified; VRAM-dominant else.

    Boundaries are inclusive on the lower bound — a 24 GB machine is T2.
    """
    if unified:
        ram = total_ram_gb
        if ram >= 240:
            return "T5"
        if ram >= 96:
            return "T4"
        if ram >= 48:
            return "T3"
        if ram >= 22:  # 24 GB chips report ~22.5 after OS reserve
            return "T2"
        return "T1"
    # Discrete GPU systems: tier driven by aggregate VRAM and GPU count.
    high_vram = [g for g in gpus if g.vram_gb >= 20]
    total_vram = sum(g.vram_gb for g in gpus)
    if len(high_vram) >= 4 or total_vram >= 160:
        return "T5"
    if len(high_vram) >= 2 or total_vram >= 40:
        return "T4"
    if total_vram >= 22:
        return "T2"
    if total_ram_gb >= 48:
        return "T3"  # CPU-leaning fat box with no real GPU
    return "T1"


def probe() -> HardwareProfile:
    plat = _detect_platform()
    arch = _detect_arch()
    apple_silicon = (plat == "macos" and arch == "arm64")
    vm = psutil.virtual_memory()
    total_ram_gb = _bytes_to_gb(vm.total)
    free_ram_gb = _bytes_to_gb(vm.available)

    nvidia_gpus = _detect_nvidia_gpus()
    amd_gpus = _detect_amd_gpus()
    gpus: list[GPUInfo] = list(nvidia_gpus) + list(amd_gpus)
    if apple_silicon and not gpus:
        gpus = _detect_apple_gpu(total_ram_gb)

    unified = apple_silicon
    backends = _detect_backends(plat, apple_silicon, bool(nvidia_gpus))

    disk = psutil.disk_usage(os.path.expanduser("~"))
    tier = classify_tier(total_ram_gb, gpus, unified)

    return HardwareProfile(
        platform=plat,
        arch=arch,
        apple_silicon=apple_silicon,
        total_ram_gb=total_ram_gb,
        free_ram_gb=free_ram_gb,
        cpu_cores_physical=psutil.cpu_count(logical=False) or 1,
        cpu_cores_logical=psutil.cpu_count(logical=True) or 1,
        gpu=gpus,
        unified_memory=unified,
        available_backends=backends,
        docker_available=_binary_exists("docker"),
        bubblewrap_available=(plat == "linux" and _binary_exists("bwrap")),
        sandbox_exec_available=(plat == "macos" and _binary_exists("sandbox-exec")),
        disk_total_gb=_bytes_to_gb(disk.total),
        disk_free_gb=_bytes_to_gb(disk.free),
        suggested_tier=tier,
    )


def write_profile(profile: HardwareProfile, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(profile.to_dict(), indent=2, sort_keys=True))


def load_profile(src: Path) -> HardwareProfile:
    data = json.loads(src.read_text())
    gpus = [GPUInfo(**g) for g in data.pop("gpu", [])]
    return HardwareProfile(gpu=gpus, **data)
