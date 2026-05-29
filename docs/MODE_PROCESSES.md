# Lighthouse — Research Mode Processes (start → end), self-contained

> **Read-this-first.** This document is written to be understood **without access to the Lighthouse
> source tree.** Every algorithm, constant, prompt, and data structure needed to reason about a mode is
> embedded inline. File paths (`module.py:func`) are given only as *locators* for a human; an LLM
> researching improvements should rely on the embedded detail, not on opening the files. The
> [Provenance](#appendix-provenance--external-dependencies) appendix lists every external package,
> model, paper, and repository each component derives from or depends on, with exact names/versions.

Lighthouse is a **local-first, hardware-adaptive research instrument** (Python ≥3.11, MIT). It runs on
a laptop: LLM inference via **Ollama** (local HTTP daemon), vectors via **Qdrant** (or an in-memory
fallback), no cloud required. **Seven research modes**, each producing one typed **artifact**, share
one infrastructure spine.

| Mode | Artifact | Entry point | Shape | Legacy key |
|------|----------|-------------|-------|-----------|
| **Watch** | digest | `modes/monitor.py:run_monitor` | Continuous: poll → dedupe → classify → alert/digest | Monitor |
| **Ask** | transcript | `modes/quc.py:ask` | Multi-turn cited Q&A with retrieval | QUC |
| **Investigate** | report | `modes/deepdive.py:run_deepdive` | Bounded iterative research (TTD-DR) → sourced report | Deep-Dive |
| **Survey** | evidence table | `modes/survey.py:run_survey` | Screen many docs → PRISMA flow + attribute grid | — (new) |
| **Reconstruct** | timeline | `modes/reconstruct.py:run_reconstruct` | Extract dated events → dedup → resolve → chronology | — (new) |
| **Decide** | matrix | `modes/decide.py:run_decide` | Score options × weighted criteria → winner + crux | — (new) |
| **Adjudicate** | verdict | `modes/debate.py:run_debate` | N adversarial perspectives → judged verdict | Debate |

Plus a **Digest** roll-up (`modes/digest.py`) that aggregates many Watch runs, and the **Deep-tier
exhaustive engine** (`modes/exhaustive.py`) that Investigate routes to at the deepest depth.

**Dispatch model.** A research job is a row in the `jobs` table created by `POST /api/jobs`. The
**dispatcher** (`dispatcher.py`) claims it (atomic `BEGIN IMMEDIATE`), resolves the registry to the
engine, builds inputs from job metadata, runs **one job per tick** (RAM-gated through the single
`ollama_slot` admission seam — never a second queue), attaches a provenance manifest, and stages the
artifact in `drafts` (status `staged`, job → `review`). The loop is SchedulerGate-gated and started
only by `serve(run=True)`, never by `create_app()`. Legacy mode keys still resolve via the registry
alias map, so persisted `jobs.mode` rows keep working.

Every mode is **offline-deterministic** when `gateway=None` (heuristic/stub path, no model load), so
the whole suite is testable without an LLM; the real path is identical in shape but model-filled.

**Status legend used throughout:** ✅ real/production-shaped · 🟡 heuristic baseline (works, but a model
or better algorithm is the intended replacement) · 🔌 contract exists but not yet wired into the live
path.

**Optimality callouts.** Each mode ends with a **❓ Is this optimal?** block listing the open research
questions for that mode — the specific design choices worth validating against the literature or
benchmarking before calling the approach settled.

---

## 0. Shared spine (used by every research job)

### 0.1 Backend selection — "prefer real, fall back to stub"
`pipeline.py:make_embedder / make_vector_store / make_gateway`

Three independent backends are each resolved at construction time. `offline=True` forces **all** stubs
and guarantees **no model is ever loaded** (used by tests and dry runs).

| Backend | Real | Stub fallback | Selection rule |
|---------|------|---------------|----------------|
| Embedder | `bge-m3` via Ollama, **1024-dim** (multilingual; supports dense+sparse+multi-vector) | `HashEmbedder(dim=256)` — deterministic hashing, **not semantic** | first installed Ollama tag whose base name is `bge-m3`, else any `*embed*`/`nomic-embed-text` (768-dim), else hash |
| Vector store | `QdrantStore` on `127.0.0.1:6333`, HNSW (`m=16`, `ef_construct=100`), int8 quantization | `InMemoryStore` — linear cosine scan | Qdrant if `available()`, else in-memory |
| LLM gateway | Ollama dispatch (`/api/chat`) with capability-class roles resolved to installed tags (`qwen3:14b`, `llama3.1:8b`, …) | `MockProvider` → returns literal `[mock …]` text | real if Ollama reachable + budget allows, else mock |

`ResearchResult.backends` records which path each run took, e.g.
`{"embedder": "bge-m3:latest", "vector_store": "qdrant", "gateway": "ollama"}` vs
`{"embedder": "hash-stub", "vector_store": "in-memory", "gateway": "mock"}`.

> The Gateway loads models **lazily** on first real completion and only after the **Governor** (token/
> USD budget + a runtime RAM guard) approves. A model that would exhaust available RAM is refused and
> the call falls back to mock rather than swapping the machine. (Local calls cost `usd=0.0` but still
> debit a token budget.)

### 0.2 Chunking
`rag/chunker.py:chunk_document` — ✅

Turns a `Document(id, text, metadata)` into `Chunk(id, document_id, text, position, metadata)`. Rules:

- Target **800 whitespace-tokens/chunk**, **100-token overlap** between adjacent chunks
  (`DEFAULT_CHUNK_TOKENS=800`, `DEFAULT_OVERLAP_TOKENS=100`).
- Prefer sentence boundaries: split on `(?<=[.!?])\s+(?=[A-Z0-9])`, paragraphs on `\n{2,}`.
- **Code fences** (```` ``` … ``` ````) are emitted as one protected chunk, never split.
- Overlong single sentences are hard-split on whitespace at the token cap.
- Chunk id = `f"{doc.id}:{i:04d}:{uuid5(NAMESPACE_URL, text).hex[:8]}"` (stable + content-addressed).
- Document metadata is copied onto every chunk (so `source`, `grade`, `published_date`, `quality_class`
  travel with the chunk for later filtering).

> 🟡 Boundaries are regex/whitespace, not semantic. Intended replacement: sentence-transformer
> similarity to find semantic boundaries (design §14.2). Token counting is `len(text.split())`, an
> approximation of real tokenization.

### 0.3 Ingestion + prompt-injection screening
`pipeline.py:ingest_text` (the gate is `governor/injection_gate.py:InjectionGate`)

Every chunk fetched from the open web is **hostile-until-proven-otherwise**. On ingest:

1. `chunk_document(doc)` → chunks.
2. **Each chunk** is scored by `InjectionGate.score(text)`; flagged chunks are **dropped from the
   retrievable corpus** and counted in `_blocked_chunks`. Injected instructions must never silently
   reach the LLM's context (design §24.8).
3. Survivors → `HybridSearch.add()`.

**The gate (embedded):** additive weighted-regex classifier, score clamped to 1.0, **blocks at
score ≥ 0.5**. Signatures and weights:

| Signature | Weight | Catches |
|-----------|--------|---------|
| `instruction_override` | 0.70 | "ignore/disregard/forget previous instructions" |
| `system_prompt_probe` | 0.60 | "reveal/repeat/print system prompt" |
| `role_assertion` | 0.55 | "you are now DAN/jailbroken/unrestricted" |
| `tool_call_injection` | 0.50 | `<tool_call>`, "invoke/execute … tool/shell/command" |
| `exfiltration_lure` | 0.50 | "send/email/upload … to <url-or-email>" |
| `new_instructions` | 0.45 | "new/updated instructions: follow …" |
| `role_confusion` | 0.40 | line-leading `system:` / `assistant:` / `user:` |
| `imperative_to_model` | 0.40 | "do not tell / without informing the user" |
| `delimiter_breakout` | 0.30 | ```` ``` ````, `"""`, `[/INST]`, `</system>`, `<\|…\|>` |

Any single ≥0.5 signature trips on its own; weaker ones must co-occur. Asymmetric on purpose: tolerate
false positives on retrieved content (user can override) rather than miss a real override.

**Companion: Spotlighting** (`spotlight(text, variant)`, from *Hines et al.*) wraps untrusted content
so the model can be told never to obey it — three variants: `delimiting` (named fences
`<<UNTRUSTED_CONTENT>>…`), `datamarking` (interleave a rare glyph `▁` between words), `encoding`
(base64 the payload). `normalize_unicode` does NFKC folding to defeat homoglyph evasion before scoring.

> 🟡 The gate is model-free heuristics by design (works offline, zero download, ~zero latency). The
> intended on-top layer is the **ProtectAI deBERTa** prompt-injection classifier
> (`protectai/deberta-v3-base-prompt-injection`) — not wired. **Improvement hook:** swap
> `InjectionGate.score` for the model; the call site is already isolated. Spotlighting exists but the
> pipeline does not yet verify the wrap before sending prompts.

### 0.4 Retrieval — hybrid search
`rag/hybrid.py:HybridSearch.search(query, top_k=5)` — ✅ (except the default reranker, see below)

Five-step pipeline (design §14.4):

1. **Dense ANN**: embed the query, `store.search(q_vec, k=100)` (cosine / HNSW).
2. **Sparse**: `BM25Index.search(query, k=100)`.
3. **Reciprocal Rank Fusion** of the two ranked id-lists.
4. Optional metadata filter + `min_quality_class` gate (uses chunk metadata).
5. **Rerank** the fused candidates → `top_k`.

**BM25 (embedded):** Okapi BM25, `k1=1.2`, `b=0.75`.
`idf = log(1 + (N − df + 0.5)/(df + 0.5))`,
`score += idf · tf·(k1+1) / (tf + k1·(1 − b + b·dl/avgdl))`. Tokenizer is `\w+` lowercased.

**RRF (embedded):** for each ranked list, `score[item] += 1/(k + rank)` with **`k=60`** (Cormack et al.
2009; the Elastic/Qdrant default), 1-based rank, summed across lists, sorted desc.

**Reranker (embedded contract):** `Reranker.rerank(query, chunks, top_k) -> [(chunk, score)]` sorted
desc.
- Default in the live pipeline is `ScoreReranker` — a **score-passthrough stub** (🔌 keeps fusion order).
- A real cross-encoder exists: `FlagReranker` backed by **`FlagEmbedding`** (model
  `BAAI/bge-reranker-v2-m3`, `use_fp16=True`; scores `[query, passage]` pairs). It lazy-imports so the
  heavy `torch` dependency is only paid on first real use; if `FlagEmbedding` is absent it raises
  `RerankerUnavailable` and `make_reranker()` degrades to `ScoreReranker`.

> 🔌 **Highest-value retrieval fix:** wire the real reranker — in `ResearchPipeline.__init__`, pass
> `reranker=make_reranker()` into `HybridSearch` instead of `ScoreReranker()`. The golden-set eval
> (`eval/`) currently reports **precision@5 ≈ 0.17, recall@5 ≈ 0.83, MRR ≈ 0.83**: recall is strong,
> precision is exactly what a cross-encoder reranker improves. A **Contextual Retrieval** prepass
> (Anthropic technique, `rag/contextual.py`) also exists to prepend document context to each chunk
> before embedding.

### 0.5 Quality-discipline gate
`verification/discipline.py:check` + `downgrade_wep` — ✅ (deterministic by design)

Runs over the synthesized text **before** it is staged. "Enforced by linters and gates, not by hoping
the LLM behaves."

1. **`extract_claims(text)`**: strip HTML, split into sentences (`(?<=[.!?])\s+(?=[A-Z0-9])`), keep only
   declaratives ≥3 words that don't end in `?`; capture inline `[N]` / `[2,3]` citation markers.
2. **`check()`**: `citation_coverage = sourced / total_claims`. `passed` iff coverage ≥ `min_coverage`
   (default **0.6**). If `high_stakes=True`, also enforce the **two-source rule** (≥2 distinct citation
   ids per claim).
3. **`downgrade_wep(prob, report)`**: `adjusted = prob · max(coverage, 0.1)`, then map to a band. A
   fluent but poorly-sourced answer is *never* labeled "almost certain" (honest-over-impressive).

**WEP bands (embedded)** — Words of Estimative Probability, ICD-203 / Sherman Kent tradition:

| Band | Range `[low, high)` | Label |
|------|--------------------|-------|
| `remote` | 0.00–0.10 | remote |
| `unlikely` | 0.10–0.40 | unlikely |
| `even` | 0.40–0.60 | even chance |
| `likely` | 0.60–0.90 | likely |
| `almost_certain` | 0.90–1.00 | almost certain |

**Triangulation + integrity (✅, added Sprint "night"):** when `evidence_chunks` is supplied, `check()`
also computes, against the real chunk metadata:
- **`triangulated`** — claims with ≥2 **independent** sources, where independence = **distinct source
  domain / document** (`metadata["source"]` or `document_id`), not merely distinct citation ids.
- **`fabricated_citations`** — claims citing an id that maps to **no evidence chunk**. Under
  `high_stakes`, any fabricated citation **fails** the gate (the competitive invariant: zero
  hallucinated citations — a cited chunk id must exist or the claim is rejected).
- **`contradictions`** — pairs of claims that disagree, found by a conservative deterministic heuristic
  (`detect_contradictions`): shared subject tokens + opposing polarity (antonym pair, or one negates a
  shared key term). Precision-biased — surfaced, never silently smoothed.

> 🟡 Claim extraction is regex sentence-splitting (misses compound/implicit claims). The contradiction
> heuristic is token-overlap + antonym/negation, not entailment-based NLI — it favours precision over
> recall. `min_coverage`/`high_stakes` are now driven per-mode by the depth tier (§0.7).

### 0.6 Persistence, calibration, audit
`pipeline.py:_persist_draft / _record_positions / _audit` — ✅

- Draft → `drafts` table (status `staged`) + a `jobs` row (status `review`) so it appears in the
  dashboard. Stored `confidence = 0.75 × max(coverage, 0.1)`.
- **Each extracted claim becomes a `Position`** (`verification/positions.py:record_position`) with
  probability **0.75 if sourced else 0.5** — this is the ground-truth-pending data the **calibration
  loop** later grades.
- **Calibration metric (embedded):** Brier score `(probability − outcome)²`, lower is better;
  `mean_brier` over `(probability, outcome)` pairs. A 0.5 forecast always scores 0.25.
- Every state transition appends to an **HMAC-chained audit log** (`verification/audit_chain.py`),
  tamper-evident.

> 🟡 Positions get a probability but **no resolve-by date or resolution criterion** yet
> (`_record_positions` leaves `resolved_at = NULL`), so the Brier loop has nothing to auto-score
> against — a human must resolve each position manually. **Improvement hook:** attach a resolve-by date
> + machine-checkable criterion at position-creation time.

### 0.7 Depth tiers — `modes/depth.py`
✅ The user (or `Auto`) picks a depth tier; the dispatcher maps it to concrete engine knobs. **Depth
scales coverage and confidence, never trust** — the discipline + entailment gates run at every tier.

| Tier | `max_rounds` | `top_k` | adversarial | coverage critic | recursive | high-stakes gate |
|------|-------------|---------|-------------|-----------------|-----------|------------------|
| `quick` | 2 | 4 | — | — | — | off |
| `standard` | 4 | 5 | — | ✅ | — | off |
| `thorough` | 6 | 8 | ✅ | ✅ | — | on |
| `deep` | 12 | 10 | ✅ | ✅ | ✅ (exhaustive engine) | on |

`resolve_depth(name)` normalizes aliases (`exhaustive`→thorough, `professional`/`overnight`→deep).
`Auto` (`/api/classify`) maps the framing **question type** → a tier (`factual_lookup`→quick,
`comparative`/`decision_support`→standard, `controversy`/`methodology`/`forecast`→thorough). The Deep
tier requires a user **budget** (wall-clock or node cap) before it will start.

> 🟡 Knob values are hand-tuned, not empirically calibrated. **Open question:** are 2/4/6 rounds and
> top-k 4/5/8/10 the right curve for answer quality vs latency on local models? The benchmark harness
> (§0.11) is the place to settle it.

### 0.8 Adversarial refutation — `verification/adversarial.py`
✅ (Thorough+). After synthesis, each **key claim** is handed to an independent skeptic that tries to
**refute** it against the same evidence. `refute_claim` → verdict ∈ {`stands`, `contested`, `refuted`};
a claim that is refuted, contested, or cannot be re-grounded is flagged, not asserted. Offline
(`gateway=None`) it is conservative: an uncited claim is `contested`, a cited one `stands`, nothing is
ever `refuted` without a model. `summarize()` rolls up a survival rate for the artifact.

> ❓ Single skeptic prompt today. **Open question:** is N independent skeptics with majority-vote
> (or perspective-diverse refutation: correctness / source-quality / reproducibility lenses) materially
> better per token than one? This is the classic adversarial-verification trade-off.

### 0.9 Coverage / completeness critic — `verification/coverage.py`
✅ (Standard+). Mirrors Gemini Deep Research's self-critique loop but scores coverage **against the
explicit plan**: `assess_coverage(sub_questions, sections)` marks each load-bearing sub-question
covered iff a section ties to it with a substantive body (≥8 words). Uncovered sub-questions are
**gaps** that trigger another round (`needs_another_round`); when the depth budget is exhausted they
are recorded as explicit **known-unknowns**. `find_missing_angles` (real-backend) additionally asks a
model what angle the draft hasn't considered.

> ❓ Coverage = "a substantive section exists per sub-question". **Open question:** should "covered"
> require a minimum *grounded* (cited+entailed) claim count, not just prose length? And should the
> termination condition weight plan-coverage vs evidence-saturation differently?

### 0.10 Provenance manifest — `dispatcher.py:_provenance_manifest`
✅ Every artifact's `body_json` carries a deterministic manifest: engine version, mode, depth, budget,
**backend actually used** (`ollama` vs `mock`/`mock-lowmem` — exposes a "mock masquerade"), per-role
models, source count, quality metrics, and a SHA-256 content hash. Deterministic given fixed inputs
(no wall-clock inside), so the same corpus + question reproduces the same manifest — the
reproducibility property frontier tools can't offer.

### 0.11 Quality benchmark — `eval/research_benchmark.py`
✅ (offline) Scores an artifact against the measurable bar (citation coverage ≥0.95, entailment ≥0.90,
fabricated == 0, adversarial + coverage ran, provenance present) and proves the grounding gate
**catches a planted hallucination** (a claim citing a non-existent source) — the failure mode frontier
deep-research ships. The real-LLM end-to-end variant is gated behind `LIGHTHOUSE_REAL_BACKEND=1`.

---

## Watch (legacy: Monitor) — `modes/monitor.py:run_monitor` → **digest**

**Purpose (§9.1):** continuously poll named sources; surface high-salience items as **alerts**, batch
the rest into a **digest**. Idempotent over `(source, item)`.

**Inputs:** `topic: str`, an iterable of `MonitorItem(source, url, title, body, published_at, metadata)`,
optional `state: MonitorState`, `salience_fn`, `gateway`, `embed_titles`.

**Process:**

1. **Fetch** (caller's job). The CLI path reads RSS via `sources/rss.py` **through the sandbox broker**
   (URL → bytes → admit/scan → parse), so feeds can't smuggle active content.
2. **Exact dedupe** — `dedup_key = sha256(url)` against `MonitorState.seen_keys`. Repeats suppressed
   and counted in `suppressed_duplicates`.
3. **Semantic dedupe** (optional) — if `embed_titles` is supplied, embed each surviving title and
   suppress near-duplicates from *different* URLs via **cosine ≥ 0.97** against prior titles.
4. **Classify + score salience** — `salience_fn(item) -> (score∈[0,1], category)`.
5. **Split** — sort by salience desc; **`is_alert` iff salience ≥ 0.7**. Alerts vs digest.
6. **Return** `MonitorReport(topic, generated_at, alerts, digest, suppressed_duplicates, total_seen)`.
   HTML via `output/html.py:render_monitor_html`.

**Default salience (embedded heuristic, `default_salience`):**
`score = min(0.5 + word_count/2000, 1.0)`; `+0.3 → "alert"` if any of
{`breaking, urgent, critical, major`}; `−0.3 → "noise"` if any of {`rumor, speculation, alleged`};
else `"informational"`.

> 🟡 Salience is length+keyword scoring. `SalienceFn` is a pluggable seam — the design intends an
> `aux_context` LLM call scored **relative to the user's stated interest** in the topic. 🟡 `MonitorState`
> is **in-memory** — production should persist the dedup ledger to `state.db` so dedupe survives
> restarts. Thresholds (alert 0.7, dup 0.97) are hard-coded.

> ❓ **Is this optimal?** (a) Salience is length+keyword; the design intends an LLM scoring each item
> **relative to the user's stated interest** — does interest-relative scoring change which items alert?
> (b) The 0.7 alert / 0.97 dedup thresholds are arbitrary constants — should they be learned from user
> accept/dismiss feedback? (c) Semantic dedup is cosine ≥0.97 on titles only — body-aware near-dup
> detection (or clustering) would catch reworded headlines.

---

## Investigate (legacy: Deep-Dive) — `modes/deepdive.py:run_deepdive` (TTD-DR backbone) → **report**

**Purpose (§9, §11):** bounded iterative research. Skeleton → per-section research fan-out → denoise
merge → iterate until the discovery curve flattens or the round budget is hit. Pattern = **TTD-DR**
("Test-Time Diffusion for Deep Research", Google).

**Depth + quality wiring (✅, night sprint).** The Investigate dispatcher adapter reads the depth tier
(§0.7): `max_rounds`/`top_k` come from the tier; **Standard+** runs the coverage critic (§0.9) and
records `coverage` + `coverage_gaps`; **Thorough+** runs the adversarial pass (§0.8) over load-bearing
section claims and records `adversarial` survival + `contested_claims`. **Deep** routes to the
exhaustive recursive engine instead (see [Deep-tier engine](#deep-tier-engine--modesexhaustivepyrun_exhaustive)).
`depth`, `max_rounds`, `rounds_used` are written into `body_json`.

**Process:**

1. **Frame** → `run_framing(question)` produces a `FramedQuestion` (see [Framing pipeline](#framing-pipeline-shared-by-investigate--the-deep-tree)).
2. **Skeleton** (`_skeleton`): one `Section(title, sub_question, body="", is_load_bearing)` per
   sub-question; sections matching a load-bearing sub-question are flagged.
3. **Round loop** (up to `max_rounds`, pipeline default **2**):
   - **Research each section** (`_research_section`): `hybrid.search(sub_question, top_k=5)` → evidence;
     build the prompt below; `gateway.complete("researcher", prompt)`. Citation ids = retrieved chunk
     ids. Researcher prompt (verbatim):
     ```
     Sub-question: {sub_question}

     Evidence:
     [1] {chunk_text[:300]}
     [2] ...

     Draft a 2-paragraph answer with [N] citations.
     ```
     (With no gateway, a deterministic stub body is produced so the orchestrator still runs.)
   - **Denoise** (`_denoise`): merge step — **currently only de-dupes each section's citation list.**
   - **Discovery-progress check** (`_discovery_progress`): fraction of *this* round's evidence chunk-ids
     that are **new** vs all prior rounds. If `< progress_threshold` (**0.1**) after round 1, the loop
     is "stuck" → terminate early. (Modeled on Undermind's discovery curve, §11.)
4. **Open questions**: any section left with an empty body is reported still-open.
5. **Return** `DraftReport(question, framing, sections, open_questions, rounds_used)`.
6. **In the pipeline**: sections concatenated → discipline gate (§0.5) → persistence/calibration/audit
   (§0.6).

> ✅ orchestration, early-termination, real per-section drafting. 🟡 **Denoise is a near-stub**
> (citation de-dupe only) — a real **synthesizer that resolves contradictions, fills gaps, and adds
> cross-section references** is the single biggest report-quality lever. 🔌 **ReSum compaction**
> (`compact()` → `CompactedContext(open_questions, established_facts, ruled_out, current_plan)`) exists
> as a contract but is **not invoked in the loop** — wire it when a researcher's working set exceeds the
> context budget (design §14.11). Sections are researched **independently** (no shared scratchpad), so
> later sections can't build on earlier findings within a round. `top_k=5`, `max_rounds`,
> `progress_threshold=0.1` are fixed. The design's LangGraph backbone is deferred — the loop is a plain
> `for`.

> ❓ **Is this optimal?** (a) **TTD-DR (skeleton→research→denoise→iterate)** vs alternatives — plan-and-
> execute (ReAct), or a true graph where sections depend on each other's findings. Is diffusion-style
> iteration the best fit for a *local* model's small context? (b) Sections are researched
> **independently within a round** (no shared scratchpad), so a finding in section 3 can't inform
> section 1 until the next round — is per-round independence costing answer quality? (c) The
> termination signal is evidence-saturation (discovery curve) AND plan-coverage (§0.9) — is that the
> right joint stopping rule, or should value-of-information drive it? Worth benchmarking on a question
> set with known-good reports.

### Framing pipeline (shared by Investigate + the Deep tree)
`framing/pipeline.py:run_framing` → `FramedQuestion`

1. **Classify type** (`classify_question`) — keyword rules → one of 8 `QuestionType`s:
   `factual_lookup, comparative, causal_explanation, predictive_forecast, decision_support,
   exploratory_survey, controversy_resolution, methodology_evaluation`. Example rules: `"should i/we"`
   → decision_support; `"vs/versus/compare"` → comparative; `"why/cause/because"` → causal;
   `"will/forecast/predict/by 20…"` → predictive. Default = factual_lookup.
2. **Critique** (`critique_question`) — flags `is_compound` (conjunction joining two question stems),
   `has_presupposition` ("why did / given that / since"), `is_underspecified` (<6 words or no `?`),
   `implicit_utility` ("best/optimal/good/ideal/right" needs a utility function). `well_formed = not
   (compound or underspecified)`.
3. **Frame multiplication** (`multiply_frames`) — 3–5 alternative framings keyed off type. E.g.
   decision_support → {NPV, long-run trajectory, downside-risk, preserve-options}; predictive →
   {base-rate, load-bearing drivers, uncertainty intervals}.
4. **Choose** (`frame_question`) — **default policy picks F1.**
5. **Decompose** (`decompose`) — 2–5 sub-questions whose union answers the parent (type-specific
   templates; e.g. comparative → strongest case per option / what evidence would change the choice /
   on what dimensions options differ).
6. **Mark load-bearing** (`load_bearing_subquestions`) — sub-questions mentioning
   `evidence|cause|change|driver` are flagged as able to flip the parent answer.

> 🟡 **This entire stage is keyword rules** — the most stubbed part of the research path and the highest-
> leverage improvement target, because everything downstream inherits the decomposition quality.
> Intended replacements (design §10): a small **classifier** (DistilBERT or planner few-shot) for
> typing; a **planner LLM** for framing/decomposition; a **Question Library** warm-start
> (`golden_sets/framings.db`, not implemented). For under-specified questions the design says run
> multiple frames in parallel or ask the user — not wired (always F1).

---

## Ask (legacy: QUC) — `modes/quc.py:ask` → **transcript**

**Purpose (§9.3):** multi-turn conversation; retrieve when the user asks something substantive; answer
with citations. The `QUCSession(id, history, topic)` is serializable so a paused conversation can be
checkpointed.

**Process** (`ask(session, user_text, hybrid, gateway, retrieve_threshold=4)`):

1. Append the user turn to `session.history`.
2. **Retrieve gate**: only if `hybrid` is bound **and** the question is **≥ 4 words** — short chit-chat
   skips retrieval. Then `hybrid.search(user_text, top_k=4)`; chunk ids become citations.
3. **Render history**: newest-first transcript truncated to **`max_chars=4000`** (crude budget cap).
4. **Draft** via `gateway.complete("researcher", prompt)`. Prompt (verbatim):
   ```
   Conversation so far:
   {history}

   Evidence:
   [1] {chunk_text[:300]}
   ...

   USER: {user_text}

   Draft a concise answer with [N] citations.
   ```
5. Append the assistant turn (with citations); return it.
6. **In the pipeline**: single-turn `quc_ask` → synthesis → discipline gate → persistence
   (same §0.5/§0.6 as Deep-Dive, but `sections=1`).

> ✅ retrieval + drafting. 🟡 History truncation is naive oldest-drop — swap for **ReSum compaction** so
> long sessions keep salient facts. 🟡 Retrieve-or-not is a word-count threshold — a lightweight intent
> classifier would avoid retrieving on "thanks" and force-retrieve on terse-but-substantive questions.
> 🔌 Streaming + interrupt not implemented (design defers it). QUC reuses the `researcher` role prompt —
> a conversational system prompt would fit chat better.

> ❓ **Is this optimal?** (a) Retrieve-or-not is a ≥4-word heuristic — a cheap intent classifier (or
> always-retrieve-then-let-the-model-ignore) may serve terse-but-substantive questions better. (b)
> History is truncated oldest-first at 4000 chars — ReSum-style compaction would keep salient facts in
> long sessions. (c) One retrieval per turn with no query rewriting — multi-hop questions ("and how
> does that compare to…") would benefit from query reformulation against the conversation.

---

## Digest (rolls up Watch) — `modes/digest.py:aggregate_digest`

**Purpose (§9.4):** roll up many Monitor runs (across all watched topics) into one daily/weekly
bulletin. **Pure aggregator**; IO (write file, notify Telegram) is the caller's job.

**Process** (`aggregate_digest(reports, period_label=None)`):

1. **Group** `MonitorReport`s by topic.
2. **Per topic**: concatenate all alerts + the **first 5** digest items; tally
   alert/digest/suppressed/seen counts → `DigestSection(topic, alert_count, digest_count, suppressed,
   items)`.
3. **Sort** sections by `alert_count` desc.
4. **Return** `Digest(period_label, generated_at, sections, total_alerts, total_items)`. HTML/markdown
   render + notify happen in the caller (a `TelegramChannel` exists in `notify/`).

> 🟡 Mechanical — it counts and concatenates, no synthesis. **Improvement hooks:** (a) add an LLM pass
> that writes a short "what changed this period" narrative per topic; (b) "top 5" is arbitrary; (c) no
> cross-topic de-duplication (same story under two topics); (d) no trend/delta vs the previous period.

---

## Adjudicate (legacy: Debate) — `modes/debate.py:run_debate` → **verdict**

**Purpose (§9.5):** for controversial claims, instantiate N perspectives to critique a draft; a judge
summarizes agreements and unresolved disputes.

**Now wired (✅, night sprint):** Adjudicate is a first-class dispatcher mode producing a `verdict`
artifact. Server-side, selecting it **promotes Quick → Standard** (a 2–3-perspective debate
legitimizes rather than stress-tests; the 4-perspective set is the floor). Validated real end-to-end
(`backend=ollama`, 168 s on a 14B).

**Process** (`run_debate(claim, draft, gateway, perspectives=PERSPECTIVES, agree_predicate)`):

1. **For each perspective**, format its prompt template with the claim → `gateway.complete("researcher",
   prompt)` for a 3–4 sentence critique. Canonical perspective set (embedded):
   - `steelman` — "Strengthen the claim '{claim}' with the best supporting argument."
   - `devils_advocate` — "Refute '{claim}' with the strongest counter-argument."
   - `base_rate` — "What is the historical base rate that bears on '{claim}'?"
   - `fragility` — "If '{claim}' is wrong, what fails first?"
   (No gateway → a deterministic `_heuristic_response` stub.)
2. **Agree predicate** per critique. Default `_default_agree` (embedded): positive if any of
   {`agree, support, consistent, proceed`} present **and** none of {`refute, wrong, fragile, fails,
   counter`}. Swappable.
3. **Judge summary**: `"{agree}/{N} perspectives agree. {disputes} disputes remain."` + the lists of
   agreeing/disputing critiques.
4. **Return** `DebateResult(claim, draft, responses, judge_summary, agreements, disputes)`.

> ✅ orchestration; each perspective is a real LLM call. 🟡 **judge + agree-classifier are stubs.**
> **Improvement hooks:** (a) replace keyword `_default_agree` with a stance classifier or a judge-LLM;
> (b) all four perspectives share the `researcher` role — give each its **own system prompt** so
> steelman/devil's-advocate truly diverge; (c) the judge merely counts — a real judge should identify
> *which* dispute is load-bearing and feed it back into Deep-Dive; (d) 🔌 Debate is **not wired into
> `ResearchPipeline`** — nothing triggers it (e.g. a `controversy_resolution` question type or a
> low-agreement draft) and its output isn't staged/audited like B and C. *(Update: Adjudicate is now
> wired into dispatch and staged/audited; the judge + agree-classifier remain stubs.)*

> ❓ **Is this optimal?** (a) The fixed 4-perspective set (steelman / devil's-advocate / base-rate /
> fragility) — is it the right basis, and should perspective count scale with the question's
> contestedness? (b) The agree-classifier is keyword-based and the judge merely counts — a real judge
> should identify *which* dispute is load-bearing and feed it back. (c) All four perspectives share the
> `researcher` role/prompt, so they diverge only by instruction, not by model/temperature — would
> distinct system prompts (or distinct models) produce genuinely more independent arguments? This is
> the multi-agent-debate literature (Du et al., "Improving Factuality via Debate").

---

## Survey — `modes/survey.py:run_survey` → **evidence table (PRISMA)**

**Purpose:** screen a corpus against inclusion/exclusion criteria, then extract a fixed set of
attributes from the included documents into a sortable evidence table — a systematic-review funnel.

**Inputs:** `topic`, `documents: [Document(doc_id, title, text)]`, `criteria: [ScreeningCriterion]`,
`attributes: [AttributeSpec]`, `gateway`, `gate`.

**Process:**
1. **Dedupe** documents by `doc_id` (first occurrence wins) → `identified` count.
2. **Screen** each document against every criterion (`ScreenDecision`). Offline: keyword match over
   `title + text`. A document is **included** iff it passes all inclusion criteria.
3. **Extract** one **`EvidenceCell` per (included doc × attribute)**: value + `citation_chunk_ids` +
   an **entailment score** (`verification.entailment.score_claim`, 1.0 offline) + `entailed` flag.
   Unsupported values are **flagged, not asserted** (`missing_attrs` records gaps).
4. **PRISMA counts** — `identified → screened → included → excluded` (internally consistent by
   construction) with `excluded_reasons`.
5. **Return** `SurveyReport(question, prisma, rows, …)`; `artifact_type=table`.

Deterministic offline (keyword screen + extract); the gateway path fills the same structure and falls
back to the heuristic on any exception.

> ❓ **Is this optimal?** (a) Screening is keyword-match offline; the real path should use the model
> with the criterion as a natural-language predicate — does that change inclusion materially vs a
> title/abstract pre-filter (real PRISMA screens titles → abstracts → full-text in stages, we screen
> full-text in one pass)? (b) Per-cell extraction is single-pass; dual-extraction with adjudication is
> the systematic-review gold standard — worth the 2× cost? (c) No inter-document contradiction flag on
> attribute values yet. (d) Entailment gate is off without MiniCheck installed.

---

## Reconstruct — `modes/reconstruct.py:run_reconstruct` → **timeline**

**Purpose:** assemble a sourced chronology — extract dated events across documents, dedupe the same
happening reported by multiple sources, resolve date disagreements, order them.

**Process:**
1. **Extract** `(date_raw, actors, action)` triples per document (offline: date regex over
   ISO / Month-Year / Month-Day-Year / numeric forms + sentence heuristic).
2. **Normalize** dates to a comparable key.
3. **Dedupe** events that are the same happening via an `event_id` hash (so one happening reported by
   five sources is one event with five sources).
4. **Resolve date conflicts** — when sources disagree, the **modal date weighted by *source* count**
   wins (one document mentioning a date 5× counts **once**, so it can't out-vote 5 separate documents).
5. **Certainty** = `winning_source_count / total_unique_sources` (1.0 when all agree, →1/N when one of
   N agrees). Events with no explicit date but inferred from ordering are marked `inferred`.
6. **Sort** chronologically → `ReconstructReport(events, …)`; `artifact_type=timeline`.

> ❓ **Is this optimal?** (a) Date extraction is regex offline — recall on prose dates ("the following
> spring", relative dates) is limited; a temporal-tagger (HeidelTime / SUTime) or the model is the
> intended upgrade. (b) Event dedup is a hash of normalized (actors, action) — paraphrased reports of
> the same event may not collide; embedding-similarity dedup is the obvious alternative. (c)
> Source-count weighting treats all sources as equally reliable — should source *grade* weight the
> vote? (d) No causal/ordering inference between events yet.

---

## Decide — `modes/decide.py:run_decide` → **decision matrix**

**Purpose:** score options against weighted criteria, compute a winner, and name the **crux** — the
criterion whose weight, if wrong, flips the decision — phrased to hand straight to Adjudicate.

**Inputs:** `question`, `options: [Option]` (≥2), `criteria: [Criterion(label, weight,
higher_is_better)]` (≥1). Validation raises on <2 options / empty criteria / missing weights.

**Process:**
1. **Score every cell** (option × criterion) → `ScoredCell(score∈[0,1], contribution)`. Offline: a
   stable hash of `(option, criterion)` (deterministic); real: `gateway.complete_structured` (the fast
   aux model — structured scoring, §model-role discipline).
2. **Weighted totals** = Σ `weight · score` per option; **argmax = winner**, runner-up + `margin`.
3. **Sensitivity sweep** — re-run totals with **each criterion removed**; record whether the winner
   changes (`decisive=True`) and the margin delta (`SensitivityResult`).
4. **Crux** — if any criterion is decisive, name all decisive criteria as a falsifiable claim ("the
   choice of X over Y is decided by C; if that weight is wrong, Z wins"); else acknowledge robustness
   and name the highest-weighted criterion as `primary_driver`.
5. **Return** `DecideReport(cells, totals, winner, runner_up, margin, sensitivity, crux, …)`;
   `artifact_type=matrix`. Validated real end-to-end (`backend=ollama`).

> ❓ **Is this optimal?** (a) Sensitivity is one-criterion-removed (one-at-a-time); it won't catch
> interactions where two weight changes jointly flip the result — a proper weight-space sweep or
> Monte-Carlo over weight distributions would. (b) Cells carry no per-cell **rationale** yet (scores
> without justification). (c) Scores are independent per cell — no cross-criterion consistency check.
> (d) Is a linear weighted-sum the right aggregation, or should it support non-compensatory rules
> (e.g. a hard veto criterion)? These map to classic MCDA literature (AHP, TOPSIS, ELECTRE).

---

## Deep-tier engine — `modes/exhaustive.py:run_exhaustive`

**Purpose:** the depth Claude/Gemini's ~10–20-min time-box can't reach. Decompose a question into a
**recursive question tree**, research each node, and recurse on any node that itself surfaces
load-bearing gaps — until every leaf is **grounded or an explicit known-unknown** — bounded only by a
user budget (`max_nodes` from the Deep budget: 30m=8 / 1h=15 / 2h=25 / overnight=50; `max_depth=3`).

**Process:** BFS over the tree; each node researched by an injectable `research_fn` (Investigate's Deep
adapter passes a one-round deep-dive: grounded iff it gathers citations). Decomposition reuses the
framing planner per node. **Termination is guaranteed** by the node/depth budget **plus question
dedup** (normalized-text `seen` set). Emits `on_node` progress; returns a serialized tree +
grounded/known-unknown counts + `truncated` flag. Safe on local hardware because it is **one bounded,
RAM-gated step at a time** — long ≠ heavy.

> ❓ **Is this optimal?** (a) The tree is **BFS, breadth-first, uniform budget** — no value-of-
> information prioritization (research the most decision-relevant branch first, prune low-value ones).
> (b) Per-node research is a 1-round deep-dive; deeper nodes might warrant more rounds. (c) No
> cross-node synthesis yet — leaves aren't woven into one narrative. (d) No checkpoint/resume (#52), so
> an interrupted multi-hour run restarts. (e) Dedup is exact normalized-text — near-duplicate
> sub-questions still expand.

---

## Cross-cutting improvement priorities (highest leverage first)

**Done in the night sprint** (was on this list): Adjudicate is wired into dispatch; the discipline gate
now does real source-independence triangulation + a fabricated-citation guard + contradiction
surfacing (§0.5); adversarial refutation (§0.8), coverage critic (§0.9), provenance (§0.10), depth
tiers (§0.7), and the benchmark (§0.11) all landed. Remaining, still highest-leverage:

1. **Framing → planner LLM** (§Investigate.0). Pure keyword rules today; everything downstream — including
   the recursive Deep tree and the coverage critic's sub-question list — inherits its decomposition
   quality. **The single highest-leverage upgrade.**
2. **Investigate denoiser** (§Investigate). The merge step is a citation de-dupe; a real
   contradiction-resolving synthesizer is the biggest report-quality gain.
3. **Wire the real reranker** (§0.4). `FlagReranker` (`BAAI/bge-reranker-v2-m3`) exists and is tested
   but the pipeline still uses the passthrough `ScoreReranker`; the golden-set eval says precision is
   the metric it moves.
4. **Grounding / auto-fetch into the dispatcher** (#28). Corpus modes only ground when documents are
   attached; without auto-fetch (arXiv/OpenAlex, behind the sandbox) a fresh user's Investigate/Ask
   runs on an empty corpus. Biggest *functional* gap for a new user.
5. **Document-ingestion UI** (#29) — Survey/Reconstruct need a way to get documents in from the
   dashboard; today they run on a placeholder.
6. **LLM salience for Watch** (§Watch) — interest-relative scoring instead of length+keywords; persist
   the dedup ledger to `state.db`.
7. **Model-based injection gate** (§0.3, ProtectAI deBERTa) and **claim-detector for the discipline
   gate** (§0.5) — both deterministic heuristics behind clean call sites.
8. **Calibration auto-resolution** (§0.6) — positions need resolve-by dates + criteria or the Brier loop
   has no ground truth.
9. **Deep-tier checkpoint/resume + cross-node synthesis** (#52, §exhaustive) — for the overnight tier.
10. **ReSum compaction** (§Investigate, §Ask) — both truncate context crudely; the `compact()` contract
    is ready to wire.

Each hook is a single, isolated call site — the orchestration contracts are stable, so these are
swap-in improvements, not rewrites. Per-mode optimality questions live in each mode's **❓** block.

---

## Appendix: Provenance — external dependencies

Everything a swap-in improvement would build on. **Pip package names and versions** are from
`pyproject.toml`; **models** are Ollama/HuggingFace tags; **algorithms** cite their source.

### Runtime Python packages (installed, `pyproject.toml` `dependencies`)
- **typer ≥0.12** — CLI framework (the `lighthouse` command surface).
- **rich ≥13.7** — terminal rendering.
- **fastapi ≥0.115** + **uvicorn[standard] ≥0.30** — web dashboard + JSON/SSE API.
- **pydantic ≥2.7**, **pydantic-settings ≥2.4** — config/models.
- **sqlalchemy ≥2.0**, **alembic ≥1.13** — DB access/migrations (SQLite, WAL mode).
- **psutil ≥5.9** — the runtime RAM guard (reads available memory before a model load).
- **structlog ≥24.1** — structured logging.
- **tenacity ≥8.2** — retry/backoff in the effector (intent outbox).
- **httpx ≥0.27** — HTTP client (Ollama, Qdrant, RSS, source APIs).
- **pyyaml ≥6.0** — model catalog (`catalog/models.yaml`, `chosen_models.yaml`).
- **tomli-w ≥1.0** — write `config.toml`.
- **platformdirs ≥4.2** — locate the data dir (`~/.lighthouse`).
- **jinja2 ≥3.1.6** — HTML report templates.
- **qdrant-client ≥1.18.0** — `QdrantStore` (HNSW vector index).
- **keyring ≥25.7.0** — secrets in the OS keychain (HMAC audit key, cloud keys).
- **textual ≥8.2.7** — the TUI.
- *(optional extra `gpu-nvidia`: **pynvml ≥11.5** for NVIDIA VRAM probing.)*

### Optional heavy dependency (reranker)
- **FlagEmbedding** (transitively **torch**) — `FlagReranker` cross-encoder. **Lazy-imported**; absent →
  `RerankerUnavailable` → graceful fallback to the passthrough reranker. Install only when you want real
  reranking.

### Dev/test packages (`dependency-groups.dev`)
- **pytest ≥8.2**, **pytest-cov ≥5.0**, **pytest-asyncio ≥0.23**, **hypothesis ≥6.100** (property tests),
  **anyio ≥4.4**, **respx ≥0.23.1** (mock httpx for Ollama/Qdrant tests), **ruff ≥0.5**, **mypy ≥1.10**,
  **pytest-textual-snapshot ≥1.0** (TUI snapshots).

### Local infrastructure (external processes, not pip)
- **Ollama** — local LLM daemon at `http://127.0.0.1:11434`. Endpoints used: `/api/chat` (completions),
  `/api/embed` (embeddings), `/api/tags` (installed models). All inference is local; cloud is opt-in.
- **Qdrant** — vector DB at `http://127.0.0.1:6333`. HNSW params `m=16`, `ef_construct=100`, scalar int8
  quantization, payload indexes on `grade`/`published_date`/`source` (design §14.15). Optional — falls
  back to `InMemoryStore`.

### Models (Ollama / HuggingFace tags)
- **Embeddings:** `bge-m3` (BAAI; 1024-dim; multilingual; dense+sparse+multi-vector) — preferred.
  `nomic-embed-text` (768-dim, ~274 MB, CPU-friendly) — alternate. Hashing stub when neither present.
- **Reasoning/synthesis (the `researcher`/`planner`/`aux_context` roles):** resolved from the local
  catalog to installed tags such as `qwen3:14b-q4_K_M`, `llama3.1:8b`. The catalog is hardware-aware
  (picks a model that fits measured RAM on this Apple M4 / 24 GB box).
- **Reranker (optional):** `BAAI/bge-reranker-v2-m3` (HuggingFace, via FlagEmbedding); the catalog also
  names a Qwen3-Reranker family.
- **Prompt-injection (planned, not wired):** `protectai/deberta-v3-base-prompt-injection`.

### Algorithms & papers (embedded above; cite when improving)
- **TTD-DR** — Google, "Test-Time Diffusion for Deep Research" — the Investigate loop shape (skeleton →
  research → denoise → iterate).
- **PRISMA** — Page et al. 2021 — the systematic-review screening funnel (identified → screened →
  included → excluded) reported by Survey.
- **MCDA / weighted-sum + one-at-a-time sensitivity** — Decide's aggregation and crux. Adjacent
  literature to evaluate against: AHP (Saaty), TOPSIS, ELECTRE; Monte-Carlo weight sensitivity.
- **Weighted-vote temporal reconciliation** — Reconstruct's modal-date-by-source-count rule (no single
  citation; the design's own heuristic). Temporal taggers to compare: HeidelTime, SUTime.
- **Recursive question-tree decomposition** — the Deep-tier engine (budget-bounded BFS with dedup
  termination); relate to plan-and-solve / tree-of-thought decomposition.
- **Adversarial / multi-agent debate** — Du et al. 2023, "Improving Factuality and Reasoning via
  Multiagent Debate" — basis for Adjudicate and the §0.8 refutation pass.
- **ReSum** — context-compaction primitive (summarize-and-replace working set); design §14.11.
- **Discovery curve** — Undermind's marginal-information-gain termination signal; design §11.
- **Okapi BM25** — sparse retrieval, `k1=1.2`, `b=0.75`.
- **Reciprocal Rank Fusion** — Cormack, Clarke & Büttcher 2009; `k=60` (Elastic/Qdrant default).
- **Contextual Retrieval** — Anthropic technique (prepend doc context before embedding); `rag/contextual.py`.
- **HNSW** — Malkov & Yashunin; Qdrant's ANN index.
- **Spotlighting** — Hines et al., "Defending Against Indirect Prompt Injection" (delimiting /
  datamarking / encoding).
- **WEP / Words of Estimative Probability** — Sherman Kent; **ICD-203** analytic standards (the five
  confidence bands).
- **Brier score** — Brier 1950; calibration metric `(p − outcome)²`.

### New internal modules (night sprint — no external dep)
- **`modes/depth.py`** — depth-tier → engine-knob map + `auto_tier` (question-type → tier).
- **`modes/exhaustive.py`** — recursive question-tree engine (Deep tier).
- **`verification/adversarial.py`** — skeptic refutation pass over key claims.
- **`verification/coverage.py`** — plan-coverage critic + missing-angle finder.
- **`verification/discipline.py`** (extended) — independent-source triangulation, fabricated-citation
  guard, contradiction detection.
- **`dispatcher.py:_provenance_manifest`** — per-artifact reproducibility manifest.
- **`eval/research_benchmark.py`** — the "better than frontier" scorecard + planted-hallucination proof.
- **`notify/templates.py`** — per-artifact Telegram review templates.

### Internal-only (no external dep, but reference points)
- **HMAC audit chain** — tamper-evident log; key from keychain.
- **Sandbox broker / scanners** — EICAR / zip-bomb / JS-in-PDF / JS-in-HTML detection before any fetched
  bytes are parsed.
- **Governor** — hierarchical token-bucket budget + degradation tiers + loop detector + the runtime RAM
  guard that gates real model loads.
