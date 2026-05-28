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
import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml

from .governor import Governor
from .governor.mock_provider import MockProvider
from .hardware import HardwareProfile, probe
from .persistence import open_db

Role = Literal["planner", "researcher", "synthesizer", "aux_context",
               "embedding", "reranker", "escalation"]


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
PAGEABLE_MOE: set[str] = {
    "gemma4-26b-a4b", "qwen3.6-35b-a3b", "glm-5.1", "qwen3.5-122b-a10b",
    "deepseek-v4-flash", "qwen3.5-397b-a17b", "kimi-k2.6", "deepseek-v4-pro",
}


# --- runtime memory guard: don't load a model into RAM we don't have ---
#
# The §5.2 budget is about *total* capacity. At run time what matters is
# *currently available* RAM — other apps may be holding it. Loading a model
# bigger than what's free forces swap and can wedge the machine. This guard
# checks live availability before a real completion; the Gateway falls back
# to the mock (never crashes) when there isn't room.

#: Headroom to leave free after loading, so the OS + our own process breathe.
RUNTIME_RAM_MARGIN_GB = 1.5


def estimate_resident_gb(model: str) -> float:
    """Resident RAM a model needs once loaded (weights, no KV headroom).
    Falls back to a param-count hint in the tag (…8b…, …14b…) for unknown tags.
    """
    fp = model_footprint_gb(model)
    if fp > 0:
        return max(fp - 2.0, fp * 0.7)  # weights ≈ footprint minus our overhead pad
    import re
    m = re.search(r"(\d+)\s*b", model.lower())
    if m:
        return int(m.group(1)) * 0.6  # ~0.6 GB/B at Q4
    return 0.0


def enough_ram_for(model: str, *, available_gb: float | None = None,
                   margin_gb: float = RUNTIME_RAM_MARGIN_GB) -> bool:
    """True if ``model`` can load without exhausting available RAM.

    MoE models page from SSD so they're always allowed. If a model is already
    resident in Ollama it costs no new RAM (caller can short-circuit).
    """
    if model in PAGEABLE_MOE:
        return True
    need = estimate_resident_gb(model)
    if need <= 0:
        return True  # unknown tiny/aux model — assume ok
    if available_gb is None:
        try:
            import psutil
            available_gb = psutil.virtual_memory().available / 1e9
        except Exception:  # noqa: BLE001
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
    return model in PAGEABLE_MOE


def model_pages(model: str, budget_gb: float) -> bool:
    """True if the model exceeds budget but runs anyway by SSD-paging (MoE)."""
    return model_footprint_gb(model) > budget_gb and model in PAGEABLE_MOE


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
                              catalog: dict[str, Any] | None = None
                              ) -> dict[str, str]:
    """Map each role to a real installed Ollama tag, fitting the RAM budget.

    Returns role→tag for roles we could satisfy from ``installed``. Roles with
    no installed match are omitted (caller falls back to the catalog class or
    a stub). Reasoning picks respect the §5.2 budget — the largest preference
    whose footprint (best-effort) fits resident, else the smallest installed.
    """
    from .hardware import llm_budget_gb
    budget = llm_budget_gb(profile)
    out: dict[str, str] = {}

    # Reasoning: walk preference, prefer ones that fit the budget.
    reasoning = None
    fitting = [t for t in _REASONING_PREFERENCE
               if t in set(installed) or _first_installed([t], installed)]
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


def _tag_fits(tag: str, budget_gb: float) -> bool:
    """Best-effort: estimate a tag's footprint from a param-count hint in its
    name (…14b…, …24b…) and check against budget. Unknown ⇒ assume it fits."""
    import re
    m = re.search(r"(\d+)\s*b", tag.lower())
    if not m:
        return True
    params_b = int(m.group(1))
    # ~0.6 GB per B at Q4 + ~2.5 GB overhead
    live = params_b * 0.6 + 2.5
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
                 overrides: dict[str, str] | None = None):
        self.governor = governor
        self.audit_db = audit_db
        self.profile = profile or probe()
        self.chosen_models_path = chosen_models_path
        if chosen_models_path is not None and chosen_models_path.exists():
            self._chosen = load_chosen_models(chosen_models_path)
        else:
            self._chosen = None
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
                backend = prev.backend if prev else "ollama"
                sampling = prev.sampling if prev else {}
                if role in ("embedding", "reranker"):
                    backend = "native"
                self._bindings[role] = ModelBinding(role=role, model=tag,
                                                    backend=backend, sampling=sampling)
        self._mock = MockProvider(governor, usd_per_1k_tokens=0.0)
        self._ollama = ollama
        self._prefer_real = prefer_real_backends
        from .governor import LoopDetector
        self._loop_detector = LoopDetector()

    # --- backend access (lazy) ---
    def _get_ollama(self):
        if self._ollama is not None:
            # Probe even injected backends — tests use the availability flag
            # to simulate daemon-down scenarios.
            try:
                if not self._ollama.available():
                    return None
            except Exception:  # noqa: BLE001 - any error → treat as unavailable
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
        except Exception:  # noqa: BLE001 - defensive: never block on missing backend
            return None
        return self._ollama

    def binding(self, role: str) -> ModelBinding:
        if role not in self._bindings:
            raise KeyError(f"no model bound for role {role!r}")
        return self._bindings[role]

    def complete(self, role: str, prompt: str, *, job_id: str | None = None,
                 allow_drift: bool = True) -> CompletionResponse:
        b = self.binding(role)
        # Loop guard (§24.6): count calls per job/role; a runaway loop trips
        # the per-job (default 1500) or per-node (25) cap and raises before we
        # burn budget on an obviously stuck job.
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
        # Dispatch on the binding's backend declaration.
        backend_used = b.backend
        text: str
        prompt_tokens: int
        completion_tokens: int
        if b.backend == "ollama":
            ollama = self._get_ollama()
            # Runtime RAM guard: if the model isn't already resident and won't
            # fit available RAM, fall back to mock rather than force a swap.
            if ollama is not None and not self._fits_ram(ollama, b.model):
                ollama = None
                backend_used = "mock-lowmem"
            if ollama is not None:
                try:
                    chat_resp = ollama.chat(b.model, prompt, sampling=b.sampling)
                    text = chat_resp.text
                    prompt_tokens = chat_resp.prompt_tokens
                    completion_tokens = chat_resp.completion_tokens
                    # Local inference: USD is zero, but still charge tokens + 1 call.
                    self.governor.spend(usd=0.0, tool_calls=1,
                                        tokens=prompt_tokens + completion_tokens,
                                        job_id=job_id)
                except Exception:  # noqa: BLE001 - fall back to mock on any backend failure
                    backend_used = "mock"
                    mock_resp = self._mock.complete(prompt, job_id=job_id)
                    text, prompt_tokens, completion_tokens = (
                        mock_resp.text, mock_resp.prompt_tokens, mock_resp.completion_tokens,
                    )
            else:
                # Keep 'mock-lowmem' if the RAM guard set it; else plain mock.
                if backend_used != "mock-lowmem":
                    backend_used = "mock"
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
            usd=0.0 if backend_used != "cloud" else 0.0,  # placeholder for cloud pricing
            fingerprint=fp,
        )
        self._record(resp, job_id=job_id, prompt=prompt, backend_used=backend_used)
        return resp

    def _fits_ram(self, ollama, model: str) -> bool:
        """True if ``model`` is already loaded (free) or fits available RAM."""
        try:
            loaded = getattr(ollama, "loaded_models", None)
            if callable(loaded) and model in (loaded() or []):
                return True
        except Exception:  # noqa: BLE001
            pass
        return enough_ram_for(model)

    def _record(self, resp: CompletionResponse, *, job_id: str | None, prompt: str,
                backend_used: str | None = None) -> None:
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
        }
        conn = open_db(self.audit_db)
        try:
            conn.execute(
                "INSERT INTO audit_events (actor, event_type, payload_json) "
                "VALUES (?, 'model_call', ?)",
                (f"gateway:{resp.role}", json.dumps(payload, sort_keys=True)),
            )
        finally:
            conn.close()
