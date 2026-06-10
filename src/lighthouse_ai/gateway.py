"""Model Gateway — single OpenAI-shaped API; routes by role; records every call.

Per design §6 + §27.

Sprint 4 scope:
  * Load tier-keyed role bindings from ``catalog/models.yaml``.
  * Write ``chosen_models.yaml`` at first run, sealed with SHA-256 digests
    of whatever models are installed locally (Ollama / MLX / unknown).
  * Provide ``Gateway.complete(role, prompt, job_id)`` that:
      1. Resolves the role to a model + backend + sampling preset.
      2. Asks the Governor for budget (USD=0 for local, real for cloud).
      3. Invokes the backend driver; falls back to the mock provider when
         no real backend is available.
      4. Records the call in ``audit.db`` as a ``model_call`` event with
         the full fingerprint.
  * Drift detection helper: compare recorded digest with installed digest.

Real ``litellm`` integration is wired in the cloud-escalation path; for
local Ollama/MLX we call subprocess/SDK directly when available, else
the mock provider serves the call.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml

from .governor import Governor
from .governor.mock_provider import MockProvider
from .hardware import HardwareProfile, probe

Role = Literal["planner", "researcher", "synthesizer", "aux_context",
               "embedding", "reranker", "escalation"]


@dataclass(frozen=True)
class SamplingParams:
    """Granular generation-steerability knobs for one call/role (§6 + §27).

    All fields are optional: ``None`` means "leave the model/catalog default
    untouched", so an unset :class:`SamplingParams` is a no-op overlay that
    preserves current behavior. Setting a field pins it for reproducibility,
    and the effective value is recorded in provenance.

      * ``seed`` — RNG seed. Pinning it makes sampling reproducible run-to-run.
      * ``temperature`` — 0.0 is greedy/deterministic; higher is more diverse.
      * ``top_p`` — nucleus-sampling cutoff.

    Frozen so a locked experiment's params can't be mutated mid-run (itself a
    reproducibility hazard, like the provenance log).
    """

    seed: int | None = None
    temperature: float | None = None
    top_p: float | None = None

    @classmethod
    def locked(cls, *, seed: int = 0, top_p: float | None = None) -> SamplingParams:
        """Deterministic preset: fixed ``seed`` + ``temperature == 0`` (greedy).

        This is the "locked" reproducible mode — given the same model digest and
        prompt, Ollama produces byte-stable output. ``top_p`` is left untouched
        unless supplied (greedy decoding ignores it anyway).
        """
        return cls(seed=seed, temperature=0.0, top_p=top_p)

    def is_empty(self) -> bool:
        """True when no knob is set — applying this overlay changes nothing."""
        return self.seed is None and self.temperature is None and self.top_p is None

    def overlay(self, base: dict[str, Any]) -> dict[str, Any]:
        """Return ``base`` with this overlay's set (non-``None``) fields applied.

        ``base`` (e.g. a binding's catalog sampling dict) is not mutated; only
        explicitly-set fields override it, so unset knobs keep the default. The
        result is the gateway's sampling dict shape, ready for the backend.
        """
        out = dict(base)
        if self.seed is not None:
            out["seed"] = self.seed
        if self.temperature is not None:
            out["temperature"] = self.temperature
        if self.top_p is not None:
            out["top_p"] = self.top_p
        return out

    def to_dict(self) -> dict[str, Any]:
        """Only the set fields, for recording the effective params in provenance."""
        out: dict[str, Any] = {}
        if self.seed is not None:
            out["seed"] = self.seed
        if self.temperature is not None:
            out["temperature"] = self.temperature
        if self.top_p is not None:
            out["top_p"] = self.top_p
        return out


@dataclass(frozen=True)
class ModelBinding:
    role: str
    model: str
    backend: str
    sampling: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelFingerprint:
    model_string: str
    registry_digest_sha256: str
    backend: str
    runtime_version: str | None = None
    pulled_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_string": self.model_string,
            "registry_digest_sha256": self.registry_digest_sha256,
            "backend": self.backend,
            "runtime_version": self.runtime_version,
            "pulled_at": self.pulled_at,
        }


class DriftDetected(RuntimeError):
    pass


class LoopTripped(RuntimeError):
    """Raised when the Governor loop detector trips a per-job/per-node cap (§24.6)."""


# --- catalog loading ---

def load_catalog() -> dict[str, Any]:
    """Load the packaged ``catalog/models.yaml``."""
    raw = (resources.files("lighthouse_ai.catalog") / "models.yaml").read_text()
    return yaml.safe_load(raw)


def bindings_for_tier(tier: str, catalog: dict[str, Any] | None = None) -> dict[str, ModelBinding]:
    cat = catalog or load_catalog()
    if tier not in cat["roles"]:
        raise KeyError(f"tier {tier!r} not in catalog")
    roles_map = cat["roles"][tier]
    samp = cat.get("sampling", {})
    out: dict[str, ModelBinding] = {}
    inference = cat["tiers"][tier]["inference"]
    for role, model in roles_map.items():
        out[role] = ModelBinding(role=role, model=model, backend=inference,
                                 sampling=dict(samp.get(role, {})))
    # Fixed roles (embedding, reranker) keep their "native" backend marker.
    for role, model in cat.get("fixed_roles", {}).items():
        out[role] = ModelBinding(role=role, model=model, backend="native")
    return out


# --- model footprints + MoE-paging awareness (§5.2 + §5.3) -------------
#
# The per-tier role table in catalog/models.yaml is the authoritative,
# hand-curated source of truth (2026 MoE-centric). These footprints exist
# only to ANNOTATE that choice: report headroom, and warn when a model will
# page from SSD rather than reject it.
#
# Capability-class → approx live footprint at Q4 (GB) ≈ weights + KV +
# activations + runtime overhead. Tags are nominal (resolved at install).

MODEL_FOOTPRINTS_GB: dict[str, float] = {
    # always-on auxiliary models (fit inside their §5.2 reserves)
    "qwen3-reranker-0.6b": 0.8,
    "bge-m3": 2.2,
    # reasoning ladder
    "phi-4-mini": 3.5,
    "qwen3.5-4b": 3.5,
    "qwen3.5-9b": 7.0,
    "gemma4-26b-a4b": 16.0,
    "qwen3.6-27b": 17.0,            # Q4; Q6≈24, Q8≈30
    "qwen3.6-35b-a3b": 20.0,        # full weights resident; pages if tight
    "glm-5.1": 70.0,
    "qwen3.5-122b-a10b": 70.0,
    "deepseek-v4-flash": 160.0,     # 284B / 13B active
    "qwen3.5-397b-a17b": 220.0,
    "kimi-k2.6": 600.0,
    "deepseek-v4-pro": 900.0,       # 1.6T / 49B active (datacenter)
}

# Fine-grained MoE models page experts from SSD (mmap), so they run in less
# resident RAM than their full weights — at a tok/s cost. They're allowed
# even when the strict budget says they don't "fit" (slower, not broken).
#: Backend classes served by the implemented Ollama driver today. Ollama
#: transparently offloads to the detected accelerator (Metal on Apple Silicon,
#: CUDA on NVIDIA, ROCm on AMD), so these local-GPU classes route through it
#: rather than mocking. Native ``mlx``/``vllm`` high-performance drivers are
#: detected + catalog-declared (higher tiers) but not yet implemented.
_OLLAMA_SERVED_BACKENDS = frozenset({"ollama", "mlx", "metal", "llamacpp"})

PAGEABLE_MOE: set[str] = {
    "gemma4-26b-a4b", "qwen3.6-35b-a3b", "glm-5.1", "qwen3.5-122b-a10b",
    "deepseek-v4-flash", "qwen3.5-397b-a17b", "kimi-k2.6", "deepseek-v4-pro",
}

# At run time roles are rebound from these capability-class names to *real
# installed Ollama tags* (e.g. ``qwen3:30b-a3b``). Those tags carry the MoE
# marker in their name — the active-param suffix ``-a<N>b`` (30B total / 3B
# active) or the classic sparse ``<E>x<N>b`` notation (``mixtral:8x7b``). We
# must recognise them too, otherwise a paging MoE bound to a real tag gets
# estimated at its full dense footprint and wrongly denied admission (silently
# degrading to the mock) on exactly the tight-RAM machines paging exists for.
_MOE_TAG_RE = re.compile(r"(?:[-_:]a\d+\.?\d*b\b)|(?:\b\d+x\d+b\b)", re.IGNORECASE)


def is_pageable_moe(model: str) -> bool:
    """True if ``model`` is a fine-grained MoE that pages experts from SSD.

    Recognises both the curated capability-class names in :data:`PAGEABLE_MOE`
    and real Ollama tags whose name encodes the MoE structure (``…-a3b`` active
    params, or ``8x7b`` sparse experts). Pageable models are admitted even when
    their full weights would not fit resident RAM — they run slower, not broken.
    """
    if model in PAGEABLE_MOE:
        return True
    return bool(_MOE_TAG_RE.search(model))


# --- runtime memory guard: don't load a model into RAM we don't have ---
#
# The §5.2 budget is about *total* capacity. At run time what matters is
# *currently available* RAM — other apps may be holding it. Loading a model
# bigger than what's free forces swap and can wedge the machine. This guard
# checks live availability before a real completion; the Gateway falls back
# to the mock (never crashes) when there isn't room.

#: Headroom to leave free after loading, so the OS + our own process breathe.
RUNTIME_RAM_MARGIN_GB = 1.5

# --- KV-cache / activation headroom (OOM-safety) ------------------------
#
# A model's *resident* RAM is not just its weights. At inference the runtime
# also holds a KV cache + activation buffers that GROW with the served context
# length, and that growth is roughly proportional to the model's hidden size —
# i.e. bigger models pay a bigger per-token KV cost. The old estimate counted
# only weights (it even subtracted a pad off the footprint), so admission could
# clear a model whose weights "fit" while its KV cache at a long prompt pushed
# the box into swap. We add an explicit, size-scaled headroom term so the guard
# reserves what the model will actually occupy under load, not just at rest.
#
# The term is intentionally conservative (over-reserve is safe; under-reserve
# risks OOM): a small fixed floor plus a fraction of the weight size, which
# tracks the larger KV/activation buffers of larger models and longer contexts.
#: Minimum KV/activation headroom even for tiny models (runtime buffers, ctx).
KV_HEADROOM_FLOOR_GB = 1.0
#: Extra KV/activation headroom as a fraction of weight size (grows with model
#: hidden size and served context — bigger models pay more per token).
KV_HEADROOM_FRACTION = 0.18


def _kv_context_headroom_gb(weights_gb: float) -> float:
    """Conservative KV-cache + activation headroom for a model of ``weights_gb``.

    Returns a size-scaled term — a fixed floor plus a fraction of the weight
    size — so the runtime guard reserves room for the KV cache and activation
    buffers that grow with context length, not just the static weights. Erring
    high here is OOM-safe; erring low is not.
    """
    if weights_gb <= 0:
        return 0.0
    return round(KV_HEADROOM_FLOOR_GB + KV_HEADROOM_FRACTION * weights_gb, 2)


def estimate_weights_gb(model: str) -> float:
    """Resident RAM the *weights alone* occupy once loaded (no KV headroom).

    Falls back to a param-count hint in the tag (…8b…, …14b…) for unknown tags.
    The curated footprint table already bakes a little KV/overhead into its
    numbers, so we back that out here to get a weights-only figure, then add the
    explicit, context-scaled KV headroom in :func:`estimate_resident_gb`.
    """
    fp = model_footprint_gb(model)
    if fp > 0:
        return max(fp - 2.0, fp * 0.7)  # weights ≈ footprint minus baked-in pad
    import re
    m = re.search(r"(\d+)\s*b", model.lower())
    if m:
        return int(m.group(1)) * 0.6  # ~0.6 GB/B at Q4
    return 0.0


def estimate_resident_gb(model: str) -> float:
    """Live resident RAM a model needs under load: weights + KV/activation headroom.

    This is the figure the admission guard reserves. It is deliberately a touch
    higher than the static weights, because the KV cache and activation buffers
    grow with the served context length and would otherwise push a "just fits"
    model into swap. Returns 0.0 for an unknown tiny/aux model (caller treats as
    negligible).
    """
    weights = estimate_weights_gb(model)
    if weights <= 0:
        return 0.0
    return round(weights + _kv_context_headroom_gb(weights), 2)


def smallest_reasoning_resident_gb(installed: list[str], *,
                                   default_gb: float = 4.0) -> float:
    """Resident RAM (GB) of the *smallest installed* reasoning model.

    This is the real RAM floor for a given box: a machine whose smallest model
    is a 1B can run on far less RAM than one whose smallest is an 8B. Used by
    the dispatch loop's pre-flight gate so small machines aren't deferred forever
    (and big-model-only boxes still wait for genuine headroom). Embedding/reranker
    tags are ignored; a pageable MoE counts as a small resident floor (it pages
    experts from SSD). Falls back to ``default_gb`` when nothing recognizable is
    installed (never block on an empty/odd model list)."""
    sizes: list[float] = []
    for tag in installed:
        low = tag.lower()
        if any(x in low for x in ("embed", "bge-", "rerank", "minilm", "arctic")):
            continue
        if is_pageable_moe(tag):
            sizes.append(2.0)
            continue
        resident = estimate_resident_gb(tag)
        if resident > 0:
            sizes.append(resident)
    return min(sizes) if sizes else default_gb


def enough_ram_for(model: str, *, available_gb: float | None = None,
                   margin_gb: float = RUNTIME_RAM_MARGIN_GB) -> bool:
    """True if ``model`` can load without exhausting available RAM.

    MoE models page from SSD so they're always allowed. If a model is already
    resident in Ollama it costs no new RAM (caller can short-circuit).
    """
    if is_pageable_moe(model):
        return True
    need = estimate_resident_gb(model)
    if need <= 0:
        return True  # unknown tiny/aux model — assume ok
    if available_gb is None:
        try:
            import psutil
            available_gb = psutil.virtual_memory().available / 1e9
        except Exception:
            return True  # can't measure → don't block
    return need + margin_gb <= available_gb

FLOOR_MODEL = "qwen3.5-9b"   # T1 reasoning floor
AUX_MODEL = "qwen3.5-9b"     # default small/fast aux (phi-4-mini at T1)


def model_footprint_gb(model: str) -> float:
    return MODEL_FOOTPRINTS_GB.get(model, 0.0)


def model_fits(model: str, budget_gb: float) -> bool:
    """True if the model fits resident, OR is a pageable MoE (runs, slower)."""
    if model_footprint_gb(model) <= budget_gb:
        return True
    return is_pageable_moe(model)


def model_pages(model: str, budget_gb: float) -> bool:
    """True if the model exceeds budget but runs anyway by SSD-paging (MoE)."""
    return model_footprint_gb(model) > budget_gb and is_pageable_moe(model)


# --- pull preflight: never fill the disk, never surprise-OOM -------------
#
# A model PULL is a disk operation (Ollama downloads weights to
# ~/.ollama/models). On a near-full disk it can wedge macOS. This preflight
# refuses a pull that would leave too little headroom, so the download can
# never take the machine down. (Pull does NOT load weights into RAM — that
# happens lazily at inference time, gated separately by the Governor.)

#: Always keep at least this much disk free after a pull.
MIN_DISK_HEADROOM_GB = 5.0
#: Pulls larger than this prompt for confirmation in the CLI.
LARGE_PULL_GB = 15.0


@dataclass(frozen=True)
class PullPreflight:
    model: str
    estimated_download_gb: float   # 0.0 ⇒ size unknown
    free_disk_gb: float
    headroom_after_gb: float
    ok: bool
    reason: str
    is_large: bool


def estimate_download_gb(model: str) -> float:
    """Approx on-disk download size (GB). Weights only — a bit under the live
    footprint, which also counts KV cache + activations + runtime overhead.
    Returns 0.0 for an unknown model (caller treats as 'size unknown')."""
    fp = model_footprint_gb(model)
    if fp <= 0:
        return 0.0
    return round(max(fp - 2.5, fp * 0.8), 1)


def preflight_pull(model: str, *, free_disk_gb: float,
                   min_headroom_gb: float = MIN_DISK_HEADROOM_GB) -> PullPreflight:
    """Decide whether ``model`` can be safely pulled given free disk.

    Refuses when the download would leave less than ``min_headroom_gb`` free,
    so a pull can never fill the volume and destabilize the OS.
    """
    est = estimate_download_gb(model)
    if est <= 0.0:
        # Unknown size — allow only if there's comfortable headroom, and say so.
        ok = free_disk_gb >= (min_headroom_gb + 5.0)
        return PullPreflight(
            model=model, estimated_download_gb=0.0, free_disk_gb=round(free_disk_gb, 1),
            headroom_after_gb=round(free_disk_gb, 1), ok=ok,
            reason=("size unknown — proceeding (ample free disk)" if ok
                    else f"size unknown and only {free_disk_gb:.1f} GB free; refusing"),
            is_large=False,
        )
    headroom = round(free_disk_gb - est, 1)
    ok = headroom >= min_headroom_gb
    reason = ("ok" if ok else
              f"would leave {headroom:.1f} GB free, under the {min_headroom_gb:.0f} GB "
              f"safety margin (need ~{est:.1f} GB, have {free_disk_gb:.1f} GB)")
    return PullPreflight(
        model=model, estimated_download_gb=est, free_disk_gb=round(free_disk_gb, 1),
        headroom_after_gb=headroom, ok=ok, reason=reason,
        is_large=est >= LARGE_PULL_GB,
    )


def recommend_models(profile: HardwareProfile,
                     catalog: dict[str, Any] | None = None) -> dict[str, ModelBinding]:
    """Per-role model bindings for this machine.

    The per-tier table in the catalog is authoritative — it was hand-tuned
    (design §5.3) with MoE flash-paging, memory-bandwidth, and license
    constraints already factored in. This returns those bindings for the
    detected tier; the budget math is advisory (see :func:`budget_report`),
    used to warn about SSD-paging, never to silently override the curated
    pick.
    """
    cat = catalog or load_catalog()
    return bindings_for_tier(profile.suggested_tier, cat)


def budget_report(profile: HardwareProfile,
                  catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Advisory: for each role's model, does it fit resident or page from SSD?

    Surfaced in chosen_models.yaml and `lighthouse doctor` so the user knows
    when a tier's default will run slower on their specific RAM.
    """
    from .hardware import llm_budget_gb
    budget = llm_budget_gb(profile)
    bindings = recommend_models(profile, catalog)
    roles: dict[str, dict[str, Any]] = {}
    paging: list[str] = []
    for role, b in bindings.items():
        if b.backend == "native":
            continue
        fp = model_footprint_gb(b.model)
        pages = model_pages(b.model, budget)
        roles[role] = {"model": b.model, "footprint_gb": fp, "pages_from_ssd": pages}
        if pages and b.model not in paging:
            paging.append(b.model)
    return {"budget_gb": budget, "roles": roles, "paging": paging}


# --- fingerprinting ---

def fingerprint_ollama(model: str) -> ModelFingerprint | None:
    """Run ``ollama show --modelfile MODEL`` and parse the digest line."""
    if not shutil.which("ollama"):
        return None
    try:
        out = subprocess.run(
            ["ollama", "show", "--modelfile", model],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    digest = None
    for line in out.stdout.splitlines():
        if line.lower().startswith("# from") and "sha256" in line.lower():
            digest = line.strip().split("sha256")[-1].lstrip(":").strip()
            break
    if digest is None:
        # Fallback: hash the modelfile content itself (stable per-version).
        digest = hashlib.sha256(out.stdout.encode("utf-8")).hexdigest()
    version = None
    try:
        v = subprocess.run(["ollama", "--version"], capture_output=True,
                           text=True, timeout=2, check=False)
        version = v.stdout.strip() or v.stderr.strip() or None
    except Exception:
        pass
    return ModelFingerprint(model_string=model, registry_digest_sha256=digest,
                            backend="ollama", runtime_version=version)


def fingerprint_unknown(model: str, backend: str) -> ModelFingerprint:
    """Last-resort fingerprint: hash the model string itself with a backend salt.

    Lets us still record *something* in audit events on machines where the
    backend SDK isn't installed (e.g. CI without Ollama). Drift detection
    correctly flags this as "unknown" so replay logic refuses byte-exact.
    """
    digest = hashlib.sha256(f"{backend}:{model}".encode()).hexdigest()
    return ModelFingerprint(model_string=model, registry_digest_sha256=digest,
                            backend=backend, runtime_version=None)


def fingerprint(model: str, backend: str) -> ModelFingerprint:
    if backend == "ollama":
        fp = fingerprint_ollama(model)
        if fp is not None:
            return fp
    return fingerprint_unknown(model, backend)


# --- resolve capability classes → real installed Ollama tags ----------
#
# The catalog uses capability-class placeholders (qwen3.6-35b-a3b, …). On a
# real machine we must map each role to a tag that's actually pulled. This
# is the design's "resolve the current tag at install" step (§6/§27).

#: Preference order (best→smallest) of real Ollama tags we know how to use
#: for the reasoning roles. First installed match wins.
_REASONING_PREFERENCE = [
    "qwen3:32b", "qwen3:30b-a3b", "mistral-small:24b", "gemma2:27b",
    "qwen3:14b-q4_K_M", "qwen3:14b", "qwen2.5:14b", "qwen2.5-coder:14b",
    "qwen3:8b", "llama3.1:8b",
    # Small-RAM rung: lets a 4-8 GB box step down to a tiny model instead of
    # degrading straight to the mock. Footprints come from the param-count hint
    # in the tag, so admission stays honest for these too.
    "qwen3:4b", "qwen2.5:3b", "llama3.2:3b", "gemma2:2b",
    "qwen3:1.7b", "llama3.2:1b", "qwen2.5:0.5b",
]
#: Smaller/faster tags for the aux role.
_AUX_PREFERENCE = ["qwen3:8b", "llama3.1:8b", "qwen2.5:14b", "qwen3:14b-q4_K_M"]
#: Embedding tags Ollama can serve.
_EMBED_PREFERENCE = ["bge-m3", "bge-m3:latest", "nomic-embed-text", "mxbai-embed-large"]


def _first_installed(prefs: list[str], installed: list[str]) -> str | None:
    installed_set = set(installed)
    # accept exact or ":latest"-suffixed matches
    for p in prefs:
        if p in installed_set:
            return p
        if f"{p}:latest" in installed_set:
            return f"{p}:latest"
        # match base name (e.g. pref "bge-m3" vs installed "bge-m3:latest")
        for inst in installed:
            if inst.split(":")[0] == p.split(":")[0]:
                return inst
    return None


def resolve_against_installed(profile: HardwareProfile, installed: list[str],
                              catalog: dict[str, Any] | None = None,
                              *, budget_gb: float | None = None
                              ) -> dict[str, str]:
    """Map each role to a real installed Ollama tag, fitting the RAM budget.

    Returns role→tag for roles we could satisfy from ``installed``. Roles with
    no installed match are omitted (caller falls back to the catalog class or
    a stub). Reasoning picks respect the budget — the largest preference whose
    footprint (best-effort) fits resident, else the smallest installed.

    ``budget_gb`` overrides the static §5.2 capacity budget. The live dispatch
    loop passes ``free_ram - margin`` here so it selects a model that fits
    *currently available* RAM (not total capacity), avoiding a too-big pick that
    would only ever degrade to the low-memory mock.
    """
    from .hardware import llm_budget_gb
    budget = llm_budget_gb(profile) if budget_gb is None else budget_gb
    out: dict[str, str] = {}

    # Reasoning: walk preference, prefer ones that fit the budget.
    reasoning = None
    # resolve each preference to its installed tag, keep order
    resolved_pref = []
    for t in _REASONING_PREFERENCE:
        inst = _first_installed([t], installed)
        if inst and inst not in resolved_pref:
            resolved_pref.append(inst)
    # prefer the first that fits the budget; else the last (smallest) installed
    for tag in resolved_pref:
        # crude footprint by param hint in the tag name
        if _tag_fits(tag, budget):
            reasoning = tag
            break
    if reasoning is None and resolved_pref:
        reasoning = resolved_pref[-1]
    if reasoning:
        for role in ("planner", "researcher", "synthesizer"):
            out[role] = reasoning

    aux = _first_installed(_AUX_PREFERENCE, installed)
    if aux:
        out["aux_context"] = aux

    embed = _first_installed(_EMBED_PREFERENCE, installed)
    if embed:
        out["embedding"] = embed
    return out


def recommend_pull_tag(profile: HardwareProfile,
                       *, budget_gb: float | None = None) -> str:
    """Best *pullable* Ollama reasoning tag for this machine's RAM budget.

    Unlike :func:`recommend_models` (which returns the catalog's capability-class
    placeholders such as ``qwen3.6-35b-a3b``), this returns the one real tag a
    cold-install user must ``ollama pull`` to get a working reasoning model.

    For the *first-run* recommendation we want a tag that fits resident in the
    measured RAM budget so the box gets a genuinely small download — not a
    multi-GB MoE that only "fits" by paging experts off the SSD. So we walk the
    largest→smallest tag ladder and return the first *dense* tag whose live
    footprint fits the budget. Only if nothing dense fits do we fall back to the
    first pageable-MoE that the resolver would accept, and finally to the
    smallest known tag. The result is RAM-appropriate: a small box gets a small
    tag instead of a hardcoded 14b.
    """
    from .hardware import llm_budget_gb
    budget = llm_budget_gb(profile) if budget_gb is None else budget_gb
    # First pass: a dense tag that genuinely fits resident (no SSD paging).
    for tag in _REASONING_PREFERENCE:
        if not is_pageable_moe(tag) and _tag_fits(tag, budget):
            return tag
    # Second pass: accept a pageable-MoE (slower, but usable) if one fits.
    for tag in _REASONING_PREFERENCE:
        if _tag_fits(tag, budget):
            return tag
    # Very tight box — fall back to the smallest known tag.
    return _REASONING_PREFERENCE[-1]


def _tag_fits(tag: str, budget_gb: float) -> bool:
    """Best-effort: does this installed tag fit the live RAM budget?

    A fine-grained MoE tag (``…-a3b``, ``8x7b``) pages experts from SSD, so it
    runs even when its full weights exceed the budget — it must be considered a
    fit, otherwise the budget-aware resolver skips a perfectly usable larger MoE
    and steps down to a small dense model, leaving capability on the table on
    exactly the tight-RAM boxes paging exists for.

    For dense tags we estimate live footprint from a param-count hint in the
    name and include the same context-scaled KV/activation headroom the runtime
    admission guard reserves, so "fits the resolver" and "fits admission" agree.
    Unknown (no param hint) ⇒ assume it fits.
    """
    if is_pageable_moe(tag):
        return True
    import re
    m = re.search(r"(\d+)\s*b", tag.lower())
    if not m:
        return True
    params_b = int(m.group(1))
    weights = params_b * 0.6  # ~0.6 GB per B at Q4
    live = weights + _kv_context_headroom_gb(weights)
    return live <= budget_gb


# --- chosen_models.yaml ---

def write_chosen_models(dest: Path, profile: HardwareProfile,
                        catalog: dict[str, Any] | None = None,
                        budget_aware: bool = True) -> dict[str, Any]:
    """Render and write the per-install ``chosen_models.yaml``.

    Uses :func:`recommend_models` (budget-aware, fits the *measured* RAM) by
    default. Pass ``budget_aware=False`` to fall back to the static per-tier
    catalog defaults (which target the tier ceiling, not the floor).

    Returns the dict that was written, for callers who want to log/verify.
    """
    from .hardware import llm_budget_gb
    cat = catalog or load_catalog()
    if budget_aware:
        bindings = recommend_models(profile, cat)
    else:
        bindings = bindings_for_tier(profile.suggested_tier, cat)
    fingerprints: dict[str, dict[str, Any]] = {}
    roles_out: dict[str, dict[str, Any]] = {}
    seen: dict[str, ModelFingerprint] = {}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for role, b in bindings.items():
        if b.model not in seen:
            seen[b.model] = fingerprint(b.model, b.backend)
        fp = seen[b.model]
        fingerprints[b.model] = {**fp.to_dict(), "pulled_at": now}
        roles_out[role] = {"model": b.model, "backend": b.backend,
                           "sampling": b.sampling}
    report = budget_report(profile, cat)
    doc = {
        "version": 1,
        "hardware_tier": profile.suggested_tier,
        "llm_budget_gb": llm_budget_gb(profile),
        "paging_from_ssd": report["paging"],  # models that page (slower)
        "detected_at": now,
        "fingerprints": fingerprints,
        "roles": roles_out,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump(doc, sort_keys=False))
    return doc


def load_chosen_models(src: Path) -> dict[str, Any]:
    return yaml.safe_load(src.read_text())


def check_drift(src: Path, *, allow_drift: bool = False) -> list[dict[str, Any]]:
    """Compare recorded vs installed digests. Returns the list of drift entries.

    Raises :class:`DriftDetected` when drift exists and ``allow_drift=False``.
    """
    doc = load_chosen_models(src)
    drift: list[dict[str, Any]] = []
    for model, fp_rec in doc.get("fingerprints", {}).items():
        installed = fingerprint(model, fp_rec.get("backend", "unknown"))
        if installed.registry_digest_sha256 != fp_rec.get("registry_digest_sha256"):
            drift.append({
                "model": model,
                "recorded": fp_rec.get("registry_digest_sha256"),
                "installed": installed.registry_digest_sha256,
            })
    if drift and not allow_drift:
        raise DriftDetected(f"{len(drift)} model(s) drifted: "
                            f"{[d['model'] for d in drift]}")
    return drift


# --- gateway proper ---

@dataclass(frozen=True)
class CompletionResponse:
    text: str
    model: str
    role: str
    prompt_tokens: int
    completion_tokens: int
    usd: float
    fingerprint: ModelFingerprint


class Gateway:
    """Role-routed model gateway.

    Sprint 4 only had a mock provider. Sprint 21 adds backend dispatch:
    when a binding declares ``backend == "ollama"`` and the Ollama daemon
    is reachable, the call goes there. If Ollama can't be reached, the
    call transparently falls back to the mock (with a logged warning) so
    tests and offline use keep working.

    Backend instances are created lazily and cached on the Gateway.
    Callers can inject pre-built backends via the constructor for tests.
    """

    def __init__(self, governor: Governor, audit_db: Path,
                 chosen_models_path: Path | None = None,
                 profile: HardwareProfile | None = None,
                 ollama=None,
                 prefer_real_backends: bool = True,
                 overrides: dict[str, str] | None = None,
                 *,
                 sampling: dict[str, SamplingParams] | None = None,
                 default_sampling: SamplingParams | None = None,
                 locked: bool = False,
                 token_sink: Callable[[str, str | None, str], None] | None = None):
        self.governor = governor
        self.audit_db = audit_db
        self.profile = profile or probe()
        self.chosen_models_path = chosen_models_path
        self._chosen: dict[str, Any] | None
        if chosen_models_path is not None and chosen_models_path.exists():
            self._chosen = load_chosen_models(chosen_models_path)
        else:
            self._chosen = None
        self._bindings: dict[str, ModelBinding]
        if self._chosen is None:
            self._bindings = bindings_for_tier(self.profile.suggested_tier)
        else:
            self._bindings = {
                role: ModelBinding(role=role, model=cfg["model"], backend=cfg["backend"],
                                   sampling=cfg.get("sampling", {}))
                for role, cfg in self._chosen["roles"].items()
            }
        # Overrides (role→real tag) take precedence — used to bind capability
        # classes to actual installed Ollama tags at run time. Keep the
        # existing sampling/backend for the role, just swap the model.
        if overrides:
            for role, tag in overrides.items():
                prev = self._bindings.get(role)
                sampling = prev.sampling if prev else {}
                # Overrides come from resolve_against_installed() — i.e. real
                # *Ollama* tags — so they are served by the Ollama driver, which
                # transparently uses the detected accelerator (Metal on Apple
                # Silicon, CUDA on NVIDIA, ROCm on AMD). Force backend "ollama"
                # rather than inheriting the catalog tier's aspirational mlx/vllm
                # marker; otherwise T3/T4/T5 boxes (catalog inference=mlx/vllm)
                # would hit complete()'s else-branch and silently fall to the mock.
                backend = "native" if role in ("embedding", "reranker") else "ollama"
                self._bindings[role] = ModelBinding(role=role, model=tag,
                                                    backend=backend, sampling=sampling)
        self._mock = MockProvider(governor, usd_per_1k_tokens=0.0)
        self._ollama = ollama
        self._prefer_real = prefer_real_backends
        from .governor import LoopDetector
        self._loop_detector = LoopDetector()
        # Cross-process, RAM-aware admission for real Ollama calls: serialise
        # model calls across all Lighthouse processes so two of them can't both
        # load a model and exhaust RAM. The lock lives beside the audit DB.
        from .governor.ollama_queue import AdmissionConfig
        self._ollama_lock = self.audit_db.parent / "ollama.lock"
        self._admission = AdmissionConfig.from_env()
        # Per-instance tally of which backend actually served each completion
        # ("ollama" real vs "mock"/"mock-lowmem" fallback). The dispatcher drains
        # this per job to detect a "mock masquerade" — a real-gateway run that
        # silently degraded to the mock because RAM was tight.
        from collections import Counter
        self._backend_counts: Counter = Counter()
        # Granular generation steerability (§6 + §27). Three overlays, applied
        # over each binding's catalog sampling dict in increasing precedence:
        #   1. ``default_sampling`` — applies to every role unless overridden.
        #   2. ``locked`` — a deterministic preset (fixed seed + temperature 0)
        #      so a run is reproducible; pinned here it cannot be mutated mid-run.
        #   3. ``sampling`` — per-role overrides (a researcher can lock just the
        #      synthesizer, say). Per-call overrides (passed to ``complete``)
        #      sit above all of these.
        # Unset (the default) leaves behavior identical to before.
        self._locked = locked
        self._default_sampling = default_sampling or SamplingParams()
        self._sampling: dict[str, SamplingParams] = dict(sampling or {})
        # Live token feed: ``(role, job_id, token)`` per streamed chunk from a
        # real backend. The dispatcher wires this to the SSE bus so the
        # dashboard renders synthesis as it is generated. Optional and
        # best-effort — None (the default) keeps every call non-streaming, and
        # the audit record is unchanged either way (it hashes the final text).
        self.token_sink = token_sink

    # --- backend access (lazy) ---
    def _get_ollama(self):
        if self._ollama is not None:
            # Probe even injected backends — tests use the availability flag
            # to simulate daemon-down scenarios.
            try:
                if not self._ollama.available():
                    return None
            except Exception:
                return None
            return self._ollama
        if not self._prefer_real:
            return None
        try:
            from .backends.ollama import OllamaBackend
            backend = OllamaBackend()
            if not backend.available():
                return None
            self._ollama = backend
        except Exception:
            return None
        return self._ollama

    def binding(self, role: str) -> ModelBinding:
        if role not in self._bindings:
            raise KeyError(f"no model bound for role {role!r}")
        return self._bindings[role]

    def effective_sampling(self, role: str,
                           override: SamplingParams | None = None) -> dict[str, Any]:
        """Resolve the sampling dict that *would* be sent to the backend for ``role``.

        Precedence (lowest → highest), each only touching its set fields:
        binding's catalog sampling → ``default_sampling`` → locked preset →
        per-role override → per-call ``override``. The result is the gateway's
        sampling-dict shape (``temperature``/``top_p``/``seed``/``max_tokens``),
        the same value passed to ``ollama.chat`` and recorded in provenance.

        Pure/side-effect-free, so callers (and tests) can record or assert the
        effective params without issuing a completion.
        """
        base = dict(self.binding(role).sampling)
        out = self._default_sampling.overlay(base)
        if self._locked:
            out = SamplingParams.locked().overlay(out)
        per_role = self._sampling.get(role)
        if per_role is not None:
            out = per_role.overlay(out)
        if override is not None:
            out = override.overlay(out)
        return out

    def sampling_provenance(self) -> dict[str, Any]:
        """The effective sampling params per role, for the run sidecar (§27).

        Records the steerability configuration that governed the run so it is
        reproducible-on-paper: ``{"locked": bool, "roles": {role: {...}}}``. A
        researcher reading the sidecar can re-pin the exact seed/temperature/
        top_p that produced the artefact.
        """
        return {
            "locked": self._locked,
            "roles": {role: self.effective_sampling(role)
                      for role in self._bindings},
        }

    def complete_structured(self, prompt: str, *, job_id: str | None = None,
                            allow_drift: bool = True) -> CompletionResponse:
        """Complete a low-creativity *structured* task (scoring, extraction,
        date/field parsing) on the fast ``aux_context`` model when one is bound,
        falling back to ``researcher``. This keeps extraction/scoring off the
        heavy reasoning model (whose thinking traces make such calls slow) while
        reserving the reasoner for synthesis. Offline output is unchanged (the
        mock provider ignores role)."""
        role = "aux_context" if "aux_context" in self._bindings else "researcher"
        return self.complete(role, prompt, job_id=job_id, allow_drift=allow_drift)

    def complete(self, role: str, prompt: str, *, job_id: str | None = None,
                 allow_drift: bool = True,
                 sampling: SamplingParams | None = None) -> CompletionResponse:
        b = self.binding(role)
        # Resolve the effective sampling overlay once (catalog base + configured
        # default/locked/per-role overlays + this call's optional override). When
        # nothing is configured this equals the binding's catalog sampling, so
        # behavior is unchanged.
        effective_sampling = self.effective_sampling(role, sampling)
        # Loop guard (§24.6): count calls per job/role; a runaway loop trips
        # the per-job (default 1500) or per-node (25) cap and raises before an
        # obviously stuck job spins forever.
        if job_id is not None:
            decision = self._loop_detector.record_call(job_id, node=role)
            if not decision.allowed:
                raise LoopTripped(decision.reason)
        fp = fingerprint(b.model, b.backend)
        # Drift check: only if chosen_models.yaml has a record for this model.
        if self._chosen is not None:
            rec = self._chosen.get("fingerprints", {}).get(b.model)
            if rec and rec.get("registry_digest_sha256") != fp.registry_digest_sha256:
                if not allow_drift:
                    raise DriftDetected(
                        f"{b.model}: recorded {rec['registry_digest_sha256']} "
                        f"!= installed {fp.registry_digest_sha256}"
                    )
        # Dispatch on the binding's backend declaration. The Ollama driver is the
        # implemented local path and is GPU-accelerated on every platform (Metal
        # on Apple Silicon, CUDA on NVIDIA, ROCm on AMD), so route the local-GPU
        # backend classes through it. Native mlx/vllm drivers are detected +
        # catalog-declared but not yet implemented — until they are, serving those
        # models via Ollama (still accelerated) beats silently mocking.
        backend_used = b.backend
        text: str
        prompt_tokens: int
        completion_tokens: int
        if b.backend in _OLLAMA_SERVED_BACKENDS:
            ollama = self._get_ollama()
            chat_ok = False
            if ollama is not None:
                # Cross-process, RAM-aware admission: reserve the new resident
                # RAM this call needs (0 if the model is already hot or pages
                # from SSD) against live-available memory. Yields False if
                # headroom never appears → fall back to the low-memory mock
                # rather than force a swap.
                from .governor.ollama_queue import ollama_slot
                with ollama_slot(self._ollama_lock, b.model,
                                 need_gb_fn=lambda m: self._need_gb(ollama, m),
                                 cfg=self._admission) as admitted:
                    if not admitted:
                        backend_used = "mock-lowmem"
                    else:
                        try:
                            chat_kwargs: dict[str, Any] = {
                                "sampling": effective_sampling,
                            }
                            if self.token_sink is not None:
                                sink = self.token_sink

                                def _on_token(tok: str, _role: str = role,
                                              _job: str | None = job_id) -> None:
                                    try:
                                        sink(_role, _job, tok)
                                    except Exception:
                                        pass

                                chat_kwargs["on_token"] = _on_token
                            chat_resp = ollama.chat(b.model, prompt, **chat_kwargs)
                            text = chat_resp.text
                            prompt_tokens = chat_resp.prompt_tokens
                            completion_tokens = chat_resp.completion_tokens
                            chat_ok = True
                        except Exception:
                            backend_used = "mock"
            else:
                backend_used = "mock"
            if not chat_ok:
                mock_resp = self._mock.complete(prompt, job_id=job_id)
                text, prompt_tokens, completion_tokens = (
                    mock_resp.text, mock_resp.prompt_tokens, mock_resp.completion_tokens,
                )
        else:
            mock_resp = self._mock.complete(prompt, job_id=job_id)
            text, prompt_tokens, completion_tokens = (
                mock_resp.text, mock_resp.prompt_tokens, mock_resp.completion_tokens,
            )

        resp = CompletionResponse(
            text=text, model=b.model, role=role,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            usd=0.0,  # local calls are free; cloud pricing TBD when escalation lands
            fingerprint=fp,
        )
        self._backend_counts[backend_used] += 1
        self._record(resp, job_id=job_id, prompt=prompt, backend_used=backend_used,
                     sampling=effective_sampling)
        return resp

    def drain_backends(self) -> dict[str, int]:
        """Return and reset the per-backend completion tally since the last drain.

        The dispatcher calls this after each job to record which backend served
        it. Keys are ``"ollama"`` (real) and ``"mock"``/``"mock-lowmem"``
        (fallback). An all-mock tally under a real gateway is a masquerade."""
        counts = dict(self._backend_counts)
        self._backend_counts.clear()
        return counts

    def _need_gb(self, ollama, model: str) -> float:
        """New resident RAM ``model`` will add: 0 if already loaded or SSD-paging.

        The admission queue reserves this against live-available RAM. A resident
        model (Ollama keeps it hot) or a fine-grained MoE that pages experts
        from disk adds no new resident footprint, so it reserves nothing and is
        admitted with no locking; a fresh load reserves its estimated weights.
        """
        try:
            loaded = getattr(ollama, "loaded_models", None)
            if callable(loaded) and model in (loaded() or []):
                return 0.0
        except Exception:
            pass
        if is_pageable_moe(model):
            return 0.0
        return estimate_resident_gb(model)

    def _record(self, resp: CompletionResponse, *, job_id: str | None, prompt: str,
                backend_used: str | None = None,
                sampling: dict[str, Any] | None = None) -> None:
        payload = {
            "role": resp.role,
            "model": resp.model,
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
            "usd": resp.usd,
            "fingerprint": resp.fingerprint.to_dict(),
            "prompt_preview": prompt[:120],
            "job_id": job_id,
            "backend_used": backend_used,
            "sampling": sampling or {},
        }
        from .verification.audit_chain import append_event
        append_event(self.audit_db, actor=f"gateway:{resp.role}",
                     event_type="model_call", payload=payload,
                     data_dir=self.audit_db.parent)
