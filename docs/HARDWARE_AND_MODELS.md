# Hardware Adaptation & Model Selection

How Lighthouse fits itself to the machine it lands on — from a 16 GB laptop to a
multi-GPU datacenter node — and which models it runs in each role at each tier.

This document is descriptive of the shipped code. The authoritative sources are
[`hardware.py`](../src/lighthouse_ai/hardware.py) (probe + tier classification +
memory budget), [`gateway.py`](../src/lighthouse_ai/gateway.py) (role bindings,
footprint/RAM estimation, admission), and the curated catalog
[`catalog/models.yaml`](../src/lighthouse_ai/catalog/models.yaml). Design refs
in the code point at §5.2–5.4 of [`lighthouse_design.md`](./lighthouse_design.md).

---

## 1. Two facts that drive everything

The whole adaptation strategy follows from two hardware realities (stated at the
top of `models.yaml`):

1. **Inference is memory-bandwidth-bound, not compute-bound.** A tier is judged
   by how much memory it has and how fast it is, *not* by chip generation or core
   count. RAM (or VRAM) is the gating resource.
2. **Fine-grained MoE collapses the old "big model needs a big machine" rule.** A
   35B-total / 3B-active MoE runs at ~3B speed with ~mid-dense quality, and pages
   its experts from SSD via mmap — so it loads in *less resident RAM than its full
   weights*. This is why the middle tiers default to an MoE rather than a dense model.

The durable decision is the **capability class** (9B dense · 27B dense · 35B-A3B
MoE · V4-Flash · V4-Pro), never a specific tag. Tags churn; at install time the
current tag is resolved and its SHA-256 digest pinned for reproducibility
([`fingerprint_ollama`](../src/lighthouse_ai/gateway.py)).

---

## 2. Probing the machine

`hardware.probe()` builds a `HardwareProfile` with no network and no heavy work:

| Probed | How | Notes |
|---|---|---|
| Platform / arch | `platform` module | `macos` / `linux` / `windows`; `arm64` ⇒ Apple Silicon |
| Total / free RAM | `psutil.virtual_memory()` | physical total drives tiering |
| Unified memory | Apple Silicon flag | GPU shares the RAM pool |
| NVIDIA GPUs | `pynvml`, else `nvidia-smi` | name + VRAM per card |
| AMD GPUs | `rocm-smi` | name + VRAM |
| Apple GPU | unified pool size | reported as one "GPU" with `vram_gb = total_ram` |
| Backends | import + binary checks | see §7 |

**Backends detected** (`BackendId`): `cpu` (always), `ollama`, `mlx` + `metal`
(Apple Silicon), `llamacpp`, `cuda`, `vllm`, `sglang` (NVIDIA).

---

## 3. Tier classification

`classify_tier(total_ram_gb, gpus, unified)` maps the probe onto one of five
tiers. **Boundaries are inclusive on the lower bound** (a 24 GB machine is T2).

**Unified-memory machines (Apple Silicon)** — RAM-dominant:

| Condition | Tier |
|---|---|
| RAM ≥ 240 GB | T5 |
| RAM ≥ 96 GB | T4 |
| RAM ≥ 48 GB | T3 |
| RAM ≥ 22 GB (24 GB chips report ~22.5 after OS reserve) | T2 |
| otherwise | T1 |

**Discrete-GPU machines** — VRAM-dominant (aggregate VRAM + GPU count):

| Condition | Tier |
|---|---|
| ≥4 high-VRAM cards (≥20 GB) **or** ≥160 GB total VRAM | T5 |
| ≥2 high-VRAM cards **or** ≥40 GB total VRAM | T4 |
| ≥22 GB total VRAM (e.g. one 3090/4090) | T2 |
| no real GPU but ≥48 GB system RAM | T3 (CPU-leaning fat box) |
| otherwise | T1 |

The result is the **suggested** default. The user can override it in
`config.toml` under `[hardware] detected_tier`.

---

## 4. The five tiers

From `catalog/models.yaml` (`tiers` + `roles`). "Default reasoning" is the model
the planner/researcher roles bind to; the synthesizer may differ (it favors the
highest-quality model that fits).

| Tier | Name | RAM/VRAM floor | Default reasoning (planner/researcher) | Synthesizer | Inference |
|---|---|---|---|---|---|
| **T1** | Mini | 16 GB / 8–12 GB VRAM | `qwen3.5-9b` (dense) | `qwen3.5-9b` (extended-thinking) | ollama |
| **T2** | Workstation | 24–32 GB / 24 GB VRAM (3090/4090) | `qwen3.6-35b-a3b` (MoE) | `qwen3.6-35b-a3b` | ollama |
| **T3** | Studio | 48–64 GB / 32 GB VRAM (5090) | `qwen3.6-35b-a3b` (MoE) | `qwen3.6-27b` (dense Q6/Q8) | mlx |
| **T4** | Workstation+ | 96–128 GB / 2× 24 GB VRAM | `qwen3.6-35b-a3b` (Q8) | `deepseek-v4-flash` (284B/13B-active) | mlx |
| **T5** | Ultra | 256 GB+ / multi-GPU H100/H200/GB300 | `deepseek-v4-pro` (1.6T/49B-active) | `deepseek-v4-pro` (reasoning mode) | vllm |

### Per-role bindings

Each tier binds four reasoning roles. `planner`/`researcher` favor the fast MoE;
`synthesizer` favors the best model that fits; `aux_context` is the small/fast
classifier-and-lint role that frees the big model.

| Role | T1 | T2 | T3 | T4 | T5 |
|---|---|---|---|---|---|
| planner | qwen3.5-9b | qwen3.6-35b-a3b | qwen3.6-35b-a3b | qwen3.6-35b-a3b | deepseek-v4-pro |
| researcher | qwen3.5-9b | qwen3.6-35b-a3b | qwen3.6-35b-a3b | qwen3.6-35b-a3b | deepseek-v4-pro |
| synthesizer | qwen3.5-9b | qwen3.6-35b-a3b | qwen3.6-27b | deepseek-v4-flash | deepseek-v4-pro |
| aux_context | phi-4-mini (3.8B) | qwen3.5-9b | qwen3.5-9b | qwen3.5-9b | qwen3.5-9b |

### Always-on auxiliary models (every tier)

Budgeted inside the §5.2 reserves, not the reasoning budget:

- **Embedding** — `bge-m3` (~2.2 GB, 1024-dim, multilingual)
- **Reranker** — `qwen3-reranker-0.6b` (~0.8 GB, runs alongside)

### Sampling defaults (per role)

| Role | temp | top_p | max_tokens |
|---|---|---|---|
| planner | 0.2 | 0.9 | 4096 |
| researcher | 0.3 | 0.9 | 4096 |
| synthesizer | 0.3 | 0.9 | 8192 |
| aux_context | 0.1 | 0.9 | 1024 |

`chosen_models.yaml` (written at init) can override any of these.

---

## 5. The memory budget (§5.2)

`llm_budget_gb(profile)` computes how much memory the reasoning LLM actually gets
after carving out fixed reserves:

```
budget_gb = total_ram
          − os_reserve        (6 GB macOS / 4 GB other)
          − 1.5 GB  embeddings
          − 0.8 GB  qdrant
          − 2.0 GB  concurrency buffer
```

- **Unified memory (Apple Silicon):** budgeted against **total RAM** (the GPU
  shares it).
- **Discrete GPU:** budgeted against **aggregate VRAM** (the model lives on the
  card; OS reserve isn't paid from VRAM — only a small embeddings/buffer carve-out).
- **CPU-only:** falls back to system RAM.

Reserve constants live in [`hardware.py`](../src/lighthouse_ai/hardware.py)
(`OS_RESERVE_MACOS_GB`, `EMBEDDINGS_RESERVE_GB`, `QDRANT_RESERVE_GB`,
`CONCURRENCY_BUFFER_GB`).

---

## 6. Does the chosen model fit? (footprints, KV headroom, paging)

Tier selection picks the *class*; two more layers decide what actually runs.

### Resident-RAM estimate

`estimate_resident_gb(model) = weights + KV/activation headroom`. Weights come
from a curated footprint table (`MODEL_FOOTPRINTS_GB`), backing out a little
baked-in pad; `_kv_context_headroom_gb` adds a size-scaled term because the KV
cache grows with context length. **Erring high is OOM-safe; erring low is not.**

Curated footprints (GB, approximate, Q4 unless noted):

| Model | GB | | Model | GB |
|---|---|---|---|---|
| qwen3-reranker-0.6b | 0.8 | | qwen3.6-35b-a3b | 20 (pages if tight) |
| bge-m3 | 2.2 | | glm-5.1 | 70 |
| phi-4-mini | 3.5 | | qwen3.5-122b-a10b | 70 |
| qwen3.5-9b | 7.0 | | deepseek-v4-flash | 160 (284B/13B-act) |
| gemma4-26b-a4b | 16 | | qwen3.5-397b-a17b | 220 |
| qwen3.6-27b | 17 (Q6≈24, Q8≈30) | | deepseek-v4-pro | 900 (1.6T/49B-act) |

### Pageable MoE — the key escape hatch

`is_pageable_moe(model)` recognizes both the curated MoE class names
(`PAGEABLE_MOE`) and **real Ollama tags** whose name encodes MoE structure — the
active-param suffix `-a<N>b` (e.g. `qwen3:30b-a3b`) or classic sparse `<E>x<N>b`
(e.g. `mixtral:8x7b`), via `_MOE_TAG_RE`. A pageable MoE is **admitted even when
its full weights exceed the budget** — it pages experts from SSD and runs slower,
not broken. (Getting this recognition right matters: a paging MoE bound to a real
tag would otherwise be estimated at full dense footprint and wrongly denied on
exactly the tight-RAM machines paging exists for.)

### Two enforcement layers

1. **Advisory — `budget_report(profile)`:** for each role's model, reports
   `footprint_gb` and `pages_from_ssd`. Surfaced in `chosen_models.yaml` and
   `lighthouse doctor` so you know when a tier default will run slower on *your*
   RAM. It **never silently overrides** the curated tier pick.
2. **Hard — runtime admission gate (dispatch pre-flight):**
   `smallest_reasoning_resident_gb(installed)` + `enough_ram_for(model)` keep a
   dense model that would swap from being loaded, while letting a pageable MoE
   through (counted at a ~2 GB resident floor). This is what stops a 24 GB box
   from swapping itself to death, and stops a big-model-only box from running
   before it has genuine headroom.

---

## 7. Backends

Today the implemented driver is **Ollama**, which transparently offloads to the
detected accelerator — Metal on Apple Silicon, CUDA on NVIDIA, ROCm on AMD — so
the local-GPU classes `{ollama, mlx, metal, llamacpp}` all route through it
(`_OLLAMA_SERVED_BACKENDS`). The native high-performance drivers (`mlx`, `vllm`,
`sglang`) are **detected and declared in the catalog** for the higher tiers but
are not yet implemented as separate drivers. The catalog's `inference:` field per
tier records the *intended* backend; the runtime serves via Ollama until the
native drivers land.

---

## 8. Reproducibility

Because tags drift, every bound model is fingerprinted: `fingerprint_ollama`
runs `ollama show --modelfile` and pins the registry SHA-256 digest (falling back
to hashing the modelfile). The digest + runtime version go into the provenance
sidecar so a run can be replayed against the exact weights, and drift detection
refuses byte-exact replay when the model is "unknown."

---

## 9. Worked example — Apple M4, 24 GB (the reference dev box)

1. **Probe:** `platform=macos`, `arch=arm64`, `unified_memory=True`,
   `total_ram_gb≈24`, one Apple "GPU" reporting the 24 GB unified pool.
2. **Tier:** unified + RAM ≥ 22 ⇒ **T2 (Workstation)**.
3. **Budget:** `24 − 6 (macOS) − 1.5 − 0.8 − 2.0 = ~13.7 GB` for the reasoning LLM.
4. **Bindings (T2):** planner/researcher/synthesizer = `qwen3.6-35b-a3b`,
   aux_context = `qwen3.5-9b`.
5. **Fit:** the 35B-A3B footprint is ~20 GB > 13.7 GB budget — but it's a
   **pageable MoE**, so it's admitted and pages experts from SSD.
   `budget_report` flags `pages_from_ssd: true` for it; the aux 9B (~7 GB) fits
   resident. This is exactly why **24 GB is the practical T2 floor**: the curated
   default is chosen to *run* on this box (via paging), not to require a bigger one.

---

## 10. Inspecting & overriding

- **See your tier + paging picture:** `lighthouse doctor` (reports platform, RAM,
  GPU, backends, suggested tier, and per-role paging from `budget_report`).
- **Force a tier:** set `[hardware] detected_tier = "T3"` in `config.toml` (e.g.
  to opt a 24 GB box up/down knowingly).
- **Pin exact models:** edit `chosen_models.yaml` (overrides the catalog bindings
  and sampling) — and re-run `doctor` to confirm the new picks fit.

---

## Source map

| Concern | File |
|---|---|
| Probe, tier classification, budget math | [`hardware.py`](../src/lighthouse_ai/hardware.py) |
| Role bindings, footprints, KV/resident estimate, paging, admission, fingerprint | [`gateway.py`](../src/lighthouse_ai/gateway.py) |
| Five-tier curated table (tiers / roles / fixed roles / sampling) | [`catalog/models.yaml`](../src/lighthouse_ai/catalog/models.yaml) |
| Design rationale (§5.2–5.4) | [`lighthouse_design.md`](./lighthouse_design.md) |
