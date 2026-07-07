# Hardware Adaptation & Model Selection — Future Development Roadmap

Companion to [`HARDWARE_AND_MODELS.md`](./HARDWARE_AND_MODELS.md) (which describes
the *current* engine). This doc is the **forward plan**: the issues raised in an
external technical review, an honest evaluation of which are real, and a
prioritized path to the best end product without over-building ahead of where the
product is.

> **Stance up front.** Lighthouse is pre-alpha with zero real users, and the
> product review panel ([`dev/PRODUCT_REVIEW_PANEL.md`](./dev/PRODUCT_REVIEW_PANEL.md))
> judged the #1 risk to be effort flowing into engineering depth instead of
> validation and buyers. So this roadmap deliberately separates **cheap
> correctness/honesty fixes to do now** from a **technically-excellent but
> mostly post-PMF redesign**. Most of the redesign is *Later*, by design.

Evidence tags: **[verified]** = confirmed against current code this cycle ·
**[sound]** = technically correct, not yet code-checked · **[verify-first]** =
depends on a post-January-2026 model/technique claim that must be checked on the
live landscape before building.

---

## 0. Guiding principles (keep these invariant)

1. **Correctness and honesty before performance.** A wrong budget number that
   ships is worse than a slow-but-correct one. Fix the accounting before chasing
   tokens/sec.
2. **Measure where you can, estimate honestly where you can't.** The long-term
   direction is measured residency/throughput, but any measurement pass must be
   opt-in and bounded — it must never be the thing that OOMs the box it protects
   (the dev box has crashed under load; no heavy always-on work).
3. **Tier on `(capacity, bandwidth)`, not capacity alone.** Decode is
   bandwidth-bound; prefill is compute-bound. Don't give a base M4 and an M4 Max
   the same defaults.
4. **KV is a first-class, non-pageable budget line**, coupled to the depth tier's
   context length — not a fudge factor off model weights.
5. **Don't advertise what you don't serve.** Declared-but-unimplemented backends
   and benchmark numbers from a single summary are honesty debt.

---

## 1. Do now — correctness & honesty bugs (cheap, aligns with the wedge sprint)

These are real defects, mostly verified against the code this cycle. They are
small, they remove wrong numbers and false advertising, and they fit the
in-flight "make the wedge true" honesty theme.

### 1.1 Tier-map hole: single fat GPU skips T3 [verified]
`classify_tier` (discrete path, [`hardware.py`](../src/lighthouse_ai/hardware.py))
sends a single 32 GB card (e.g. 5090) to **T2** (32 ≥ 22, but < 40 and not ≥2
cards), yet [`catalog/models.yaml`](../src/lighthouse_ai/catalog/models.yaml)
lists "32 GB VRAM (5090)" as a **T3** example. There is no discrete-VRAM path
into T3 at all (single cards jump 24→T2→40→T4).
**Fix:** add a discrete branch `if total_vram >= 30: return "T3"` (or reconcile
the catalog comment), and add a regression test in `tests/test_model_selection.py`
asserting a single-32 GB-card profile lands where the catalog claims.

### 1.2 Budget under-counts the always-on models [verified]
`llm_budget_gb` reserves `EMBEDDINGS_RESERVE_GB = 1.5`, but `MODEL_FOOTPRINTS_GB["bge-m3"]`
is **2.2**, and the **0.8 GB reranker** (`qwen3-reranker-0.6b`) has no reserve line
(the 0.8 there is qdrant). The reasoning budget is therefore ~1.5 GB too generous —
exactly the "systematically wrong on the reference box" class of bug.
**Fix:** set the embeddings reserve to the real footprint and add an explicit
reranker reserve (or derive both from `MODEL_FOOTPRINTS_GB` so they can't drift).
Add a test asserting `llm_budget_gb` subtracts the real aux footprints.

### 1.3 README quick-start models don't match the catalog [verified]
README quick-start still pulls `qwen3:14b` / `llama3.1:8b`; the catalog binds
`qwen3.6-35b-a3b`. A fresh `lighthouse init` should print the *catalog-resolved*
tag the box will actually use, and the README should not hardcode a stale tag.
**Fix:** make `init` print the resolved per-role tags + the single `ollama pull`
the user needs (this overlaps the wedge sprint's "auto-model first-run" item);
update the README quick-start to reference that flow, not a fixed tag.

### 1.4 Stop advertising backends we don't serve [verified]
`_OLLAMA_SERVED_BACKENDS` routes mlx/metal/llamacpp through Ollama; native
`mlx`/`vllm`/`sglang` are detected and declared in the catalog `inference:` field
but **not implemented**. `HARDWARE_AND_MODELS.md` §7 is already honest about this;
the catalog/`doctor` should be too.
**Fix:** have `doctor` label a declared-but-unserved backend as "planned (served
via Ollama today)", and gate any `inference:`-driven behavior behind a capability
check so it can't silently no-op.

---

## 2. Corrections to the review — do NOT implement these as written

The external critique is strong, but three items are wrong or overstated for our
actual target hardware. Future work must not blindly follow them.

### 2.1 `--n-cpu-moe` is a no-op on the reference Apple Silicon box [sound]
CPU-RAM expert offload is a **discrete-GPU** lever (move expert tensors to host
RAM, keep attention/KV on the card across the PCIe boundary). On unified-memory
Apple Silicon there is **no separate CPU/GPU pool** — experts already live in the
memory the GPU reads. So "route over-budget MoE to `--n-cpu-moe` resident offload
first" does not apply to the M4. There, the real lever is **quantize the working
set to fit resident** (§3.3); SSD mmap fault is the genuine last resort.
**Implication:** the MoE-serving work is *backend-config* (pass `--n-cpu-moe` /
batch flags to Ollama **on discrete-GPU tiers only**) plus *quant-to-fit on
unified tiers* — not a new paging engine. Also note: the current engine does not
implement paging at all — `is_pageable_moe` merely *permits* an over-budget MoE to
load and delegates memory to Ollama. [verified]

### 2.2 Speculative decoding draft model must share the target's tokenizer [sound]
The review's "bind the aux model as the draft model for a free 1.3–2×" is invalid
across model families: draft/target must share a **vocabulary/tokenizer**. The T1
aux is `phi-4-mini` (Microsoft) drafting `qwen3.5-9b` (Qwen) — different
tokenizers, will not work. Only same-family pairs are valid (e.g. a small Qwen3
draft for a Qwen3.6 target), or use a model with **built-in Multi-Token
Prediction** instead of a separate draft. Any future `speculative:` catalog field
must encode the family/tokenizer constraint, not just "use aux".

### 2.3 Treat the post-cutoff landscape claims as to-verify, not settled [verify-first]
Several recommendations rest on claims past this assistant's January-2026
knowledge: EAGLE-3 being the "de-facto standard" at 3.0–6.5×, Qwen3-Embedding-8B
at MTEB 70.58, `--n-cpu-moe` being current SOTA, the 0.6B→4B reranker recall
figures. These are plausible (Qwen3-Embedding and EAGLE-2 existed around the
cutoff) but unverified here. **Do a fresh web-research pass and cite primary
sources before hardcoding any of these numbers or making them load-bearing.**

---

## 3. Next — high-value correctness (the redesign worth doing first)

These are real improvements that are still mostly about *correctness* (avoiding
OOM, fitting long context), not speculative performance. Sequenced by leverage.

### 3.1 KV cache as a first-class, quantized, depth-coupled budget line [sound]
**Problem:** `_kv_context_headroom_gb` scales KV off model *weights*, but KV scales
with **context × layers × batch** and is **not pageable** (hot every token). The
real OOM corner — "paging MoE + Deep depth + 128k context" — is unguarded.
**Change:** (a) compute a KV budget from the *configured max context for the depth
tier*, not a constant; (b) enable **KV-cache quantization** (q8_0, or q4 K / q8 V)
to buy long context on tight boxes; (c) **couple admission to the depth tier** so
Deep@128k runs a different fit check than Quick@8k, and on a tight box auto-selects
a smaller/more-quantized bind rather than thrashing.
**Touchpoints:** `gateway.estimate_resident_gb`, `_kv_context_headroom_gb`, the
dispatch pre-flight gate, depth config in `templates/config.toml`.
**Acceptance:** a test proving Deep@128k on a 24 GB profile is refused (or
down-bound) while Quick@8k is admitted; KV budget is a function of context, not
weights. **Effort: M · Risk: low** (pure accounting + a config knob).

### 3.2 Bandwidth-aware tiering (`tier = (capacity, bandwidth)`) [sound]
**Problem:** `classify_tier` ignores bandwidth though the doc claims to tier on
speed. Base M4 (~120 GB/s) vs M4 Pro (~270) vs M4 Max (~410) decode a paged MoE
very differently at the same capacity.
**Change:** carry a small per-chip bandwidth table (or add a STREAM/memcpy probe
to a later calibration pass) and let it break ties / adjust the paging warning.
Split the two phases in any future estimate: **prefill compute-bound** (tune
llama.cpp `-b`/`-ub` per box) vs **decode bandwidth-bound**.
**Touchpoints:** `hardware.probe`/`classify_tier`, a new `bandwidth_gbps` field on
`HardwareProfile`, `budget_report`.
**Acceptance:** two 24 GB Apple profiles with different chips don't get identical
paging advice. **Effort: M · Risk: low.**

### 3.3 Degrade-to-fit quant ladder [sound]
**Problem:** one fixed quant per tier, then page if it doesn't fit. A resident Q5
beats an SSD-paged Q8 on latency and quality-per-second.
**Change:** try the target at Q8 and step Q8→Q6→Q5→Q4 until it fits resident with
KV headroom (§3.1), and only then consider offload/paging. Per-role **quality
floors** prevent over-degrading the synthesizer. The catalog already carries
multi-quant footprints (27B Q4/Q6/Q8) to build on.
**Touchpoints:** `bindings_for_tier`, `MODEL_FOOTPRINTS_GB`, admission gate.
**Acceptance:** on a profile where Q8 doesn't fit, the binder picks the largest
quant that fits resident, never a paged higher quant, unless a quality floor
forbids it. **Effort: M · Risk: medium** (safest once §4.1 measurement exists).

---

## 4. Later — the larger redesign (real, but post-PMF)

Right ideas, wrong sprint. Do these after the product has users and one real
quality number. Each carries meaningful effort and/or external-claim risk.

### 4.1 Measure-then-bind calibration pass [sound, resource-sensitive]
**Idea:** a one-time pass at `init` (and on hardware/model change) that loads each
candidate model and measures real resident RSS, decode tok/s, TTFT at a
representative prefill, and KV growth slope at two context lengths — then binds
roles against *measured* numbers cached in `chosen_models.yaml`. This self-corrects
quant/driver/model drift and would have caught the §1.2 accounting bug empirically.
**Why Later, not Now:** it directly tension's the resource constraint — loading a
20 GB MoE to benchmark it can OOM the very 24 GB box it's meant to protect. It must
be **opt-in, bounded, crash-safe, never background**, and is closer to a few
hundred careful lines than the "~150" the review suggested. Build it *after* the
cheap accounting fixes (§1) make the static path honest.
**Acceptance:** `doctor` shows measured numbers ("synthesizer: 11.3 GB resident,
34 tok/s, TTFT 2.1s @ 8k") and admission uses them; the pass refuses to run a
measurement that would exceed safe headroom. **Effort: L · Risk: medium-high.**

### 4.2 Native backends: MLX (Apple T3+), vLLM/SGLang (NVIDIA T4+) [sound]
MLX is meaningfully faster than llama.cpp-via-Metal for many Apple models; vLLM/
SGLang unlock paged-attention, continuous batching, and the speculative path.
**Effort: L (per driver) · Risk: medium.** Until then, §1.4 keeps us honest.

### 4.3 Tier-aware speculative decoding [verify-first]
Add `speculative: {draft_model, method}` to the catalog **with the tokenizer/family
constraint from §2.2**. On NVIDIA (vLLM/SGLang) pursue EAGLE-style heads; on
Ollama/llama.cpp use classic same-family draft-model or prompt-lookup; prefer MoE
models with built-in MTP where available. Verify EAGLE-3 status/speedups first
(§2.3). **Effort: M–L · Risk: medium (external claims).**

### 4.4 Tier the retrieval stack [verify-first]
Today a fixed `bge-m3` runs everywhere. Tier the embedder (e.g. small/mid/large by
tier) and the reranker (the `0.6b` is fine at T1, undersized above). **Keep BGE-M3
for hybrid** — it does dense + sparse + late-interaction in one model, which fits
the BM25+dense design — and *add* a higher-quality dense option (e.g. Qwen3-Embedding,
with MRL dimension truncation to control vector-store cost), surfaced as a choice.
For regulated-domain users the mid-size (4B-class) embedder is often the sweet spot,
not the largest. **Verify the leaderboard/recall numbers first** (§2.3).
Note: confirm which reranker is actually on the retrieval path — the catalog's
`qwen3-reranker-0.6b` (model-budget) vs the RAG cross-encoder (FlagEmbedding
`bge-reranker-v2-m3`) — before tiering, so the right component is upgraded.
**Effort: M · Risk: medium (external claims).**

---

## 5. The target "best-version T2" (24 GB M4), corrected for unified memory

After §1 + §3 (and eventually §4), a 24 GB M4 should look like:

- Calibration (§4.1) measures the box → binds the synthesizer to **Qwen3.6-35B-A3B
  via MLX with experts resident in unified RAM** (not SSD-paged), stepping the
  quant down (§3.3) until it fits with KV headroom — **not** `--n-cpu-moe` (§2.1).
- **KV cache quantized (q8) and budgeted for the selected depth tier's context**
  (§3.1); admission refuses Deep@128k unless measured KV + working set fits, else
  auto-drops to a smaller bind and tells the user.
- Retrieval: keep **BGE-M3 for sparse/hybrid**, optionally a mid-size dense
  embedder + a larger reranker if the box has headroom (§4.4).
- Speculative decode only if a **same-family** draft or built-in MTP is available
  (§2.2 / §4.3).

Same machine, honest fit story, materially faster — without the discrete-GPU
assumptions that don't hold on Apple Silicon.

---

## 6. Sequencing (solo builder)

1. **§1 correctness/honesty bugs** — days; do alongside the wedge sprint.
2. **§3.1 KV depth-coupled + quantized** — the real OOM corner; highest-value next.
3. **§3.2 bandwidth-aware tiering** + **§3.3 quant ladder** — finish the
   correctness story.
4. **Verify §2.3 landscape claims** (web pass) — gates everything in §4.3/§4.4.
5. **§4.1 calibration pass** — de-risks the rest empirically; build it carefully.
6. **§4.2 native drivers**, then **§4.3 spec decode**, **§4.4 retrieval tiering** —
   post-PMF performance work.

**Do not** start §4 before the product has users and one validated quality number;
that is where the review panel says the real risk lives.

---

## 7. Source map

| Concern | File |
|---|---|
| Probe, tier classification, budget reserves, KV headroom | [`hardware.py`](../src/lighthouse_ai/hardware.py) |
| Role bindings, footprints, residency estimate, paging, admission | [`gateway.py`](../src/lighthouse_ai/gateway.py) |
| Curated tier/role table, quant footnotes, fixed aux models | [`catalog/models.yaml`](../src/lighthouse_ai/catalog/models.yaml) |
| Current behavior (descriptive) | [`HARDWARE_AND_MODELS.md`](./HARDWARE_AND_MODELS.md) |
| Why correctness/adoption outranks this redesign | [`dev/PRODUCT_REVIEW_PANEL.md`](./dev/PRODUCT_REVIEW_PANEL.md) |
| Selection tests | `tests/test_model_selection.py` |
