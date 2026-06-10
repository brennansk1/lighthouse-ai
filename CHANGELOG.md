# Changelog

All notable changes to Lighthouse are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased] — Feature-priority sweep: invariant hardening + export (2026-06-10)

### Fixed
- **Fabricated-citation detection now runs on the main research path.** The
  pipeline's discipline gate was called without the run's evidence chunks, so
  the citation-integrity check (out-of-range `[N]` → fabricated), triangulation,
  and the entailment gate were all silently skipped — a direct gap against the
  zero-fabricated-citations invariant. Evidence is now passed; runs with no
  evidence keep the historical skip.
- **Entailment never grades a fabricated citation.** A claim whose citation ids
  resolve to no real chunk used to be scored against an arbitrary fallback
  chunk; it now stays in the denominator as not-entailed.
- **Egress allowlist label-boundary matching**: degenerate hosts with empty
  labels (`.arxiv.org`, `a..arxiv.org`) no longer match a subdomain allowlist
  entry (defense-in-depth; DNS would have rejected them anyway).
- **Provenance sidecar tmp name**: atomic writes now use `<name>.tmp` instead of
  `with_suffix(".prov.tmp")`, which doubled the suffix and could collide two
  sidecars sharing a stem.

### Added
- **`lighthouse export --markdown FILE`** (`targets/markdown.py`): standalone,
  portable Markdown report with the run's full W3C PROV-O manifest embedded —
  models, source slots, content hash, and the raw sidecar in a fenced block
  (FUTURE_FEATURES §7, smallest honest slice). The Logseq path now also passes
  `body_json`/`artifact_type` through, enabling the typed renderers the CLI
  previously bypassed.

## [Unreleased] — Deep sweep: modernization + UX polish (2026-06-10)

### Added
- **Live synthesis streaming**: `OllamaBackend.chat(on_token=…)` streams the
  completion; the gateway's new `token_sink` forwards synthesizer tokens, the
  dispatcher publishes them as SSE `synthesis.token` events, and the dashboard's
  run trace renders a "Writing synthesis…" pane that fills as the model writes.
  The audit record is unchanged (it hashes the final assembled text).
- **`lighthouse doctor` privacy & secrets section**: airgap kill-switch state in
  plain language, the effective secrets backend (OS keychain vs file fallback via
  the new `SecretStore.backend_status()`), a hard failure when `secrets.toml` is
  readable by other users, and a disk-space line (<5 GB free is an issue).
- **`lighthouse audit-egress --summary`**: a one-paragraph plain-English verdict
  (call count + hosts) so a non-technical reader can check the privacy claim
  without parsing the table.
- **First-run card**: `lighthouse init` ends with the three steps to a first
  research run (pull → start → research) plus the dashboard URL and a pointer to
  `doctor`.
- Dedicated unit suites for `net_politeness` (31 tests — canonicalization,
  robots cache, rate budgets and crawl-delay under injected clocks) and
  `provenance` (43 tests — record shape, JSONL log invariants, sidecar
  determinism, torn-line tolerance).

### Changed
- **Uniform scheduler-gate coverage**: debate, quc, exhaustive (synthesis + VOI
  nudge), and monitor's gateway salience scorer now wrap their LLM calls in the
  host-courtesy gate like the other engines (keyword-only `gate=None` params —
  no-op when unwired). `modes/_gate.complete_structured_or` replaces six
  hand-rolled try/call/parse/fallback blocks across survey/reconstruct/decide.
- CI also runs on `claude/**`/`feature/**` pushes and `workflow_dispatch`, so
  gate drift surfaces before a PR.

### Fixed
- **mypy back to 0 errors** (11 had accumulated): the guarded fetch path now
  uses precise httpx-compatible types (covariant `Mapping`-based query params,
  `Mapping[str, Any]` POST data, `bool | UseClientDefault` redirects), and
  `sources/searxng.py` narrows its optional injected client correctly.
- `lighthouse init` now honors `$LIGHTHOUSE_DATA_DIR` like every other command
  (it used to silently write to `~/.lighthouse`).

## [Unreleased] — Production-grade push (2026-05-31)

Established `docs/DEFINITION_OF_DONE.md` as the authoritative bar (7 per-feature
gates + a 10-point release gate + a first-class UX-simplicity standard), then took
the calibration "trust" pipeline and several checklist gaps to that bar.

### Added
- **Definition of Done** (`docs/DEFINITION_OF_DONE.md`) — the production-grade rubric
  every feature is measured against; wired from the README, checklist, and DEV_LOG.
- **Evidence-derived position probabilities** (`calibration.probability_from_evidence`):
  source count / independence / entailment / contradiction → the probability a claim is
  true, replacing the near-vacuous fixed heuristics (Investigate 0.75/0.5, Survey 0.7).
- **Evidence retriever for resolution** (`verification/evidence.py`): re-fetches a claim
  from public sources at the deadline so the resolver decides from fresh evidence, never
  the model's own memory; offline/none → defer. Machine-classifiable claims get a default
  criterion (`resolver.default_criterion`); the supervisor loop wires the retriever.
- **Honest calibration display** (`positions.calibration_report` + Track tab): log score,
  Murphy Brier decomposition, per-WEP-band reliability with Beta-Binomial shrinkage +
  90% credible intervals, plus a **human-resolution queue** ("Needs your call") with
  one-click Came-true/Didn't; `GET /api/positions/human-queue`.
- **PROV-O sidecar on every run path**: the dispatcher (7 dashboard modes) now also writes
  a self-contained `<draft_id>.prov.json`, matching the pipeline.
- **Budget-trip / loop-guard notifications**: a run stopped by a guard pings the user and
  emits `governor.tripped` (`notify.notify_budget_trip` + dispatcher edge).
- **Key-required pre-flight** (`SkillManifest.requires_key_env`): hard-keyed sources
  (fred, bea) short-circuit with actionable guidance instead of a doomed 4xx request.
- **Browser QA harnesses**: `scripts/browser_track.py` (Track tab) and
  `scripts/browser_ux_sweep.py` (all 9 tabs — zero console errors, no white-screens).

## [Unreleased] — Sprints 30–32 (2026-05-28)

### Fixed
- **Reranker determinism**: `ScoreReranker` (the active fallback when FlagEmbedding
  is absent) accumulated document-frequency state across calls, so the same
  (query, candidates) drifted to different rankings as call history grew — making
  retrieval non-deterministic and breaking recall monotonicity (recall@5 < recall@3
  in the golden-set eval). IDF is now computed per-call from the candidate pool;
  rankings are a pure function of inputs. Regression tests added.

### Added
- **Tick Overlap Guard** (`subconscious/overlap.py`, OpenHuman §4): `GenerationGuard`
  so a slow background pass overtaken by the next scheduled one discards its writes
  instead of double-committing; wired into `resolver.run_resolver_pass`.
- **Reflection / Escalation split** (`subconscious/`, OpenHuman §3): passive
  reflections (provenance, never auto-post, cap of 5/tick, acting spawns a fresh job)
  vs actionable escalations (status + priority). WAL store, tick engine (scheduler-gated
  + overlap-guarded), stale-position escalation producer, **Intelligence dashboard page**
  (8th page — reflections + escalations tabs, Act button → job, status transitions),
  `GET /api/reflections`, `GET /api/escalations`, `POST /api/reflections/{id}/act`,
  `PATCH /api/escalations/{id}/status` endpoints, `escalations_open` sidebar counter.
- **Payload compaction** (`rag/compaction.py`, OpenHuman §5): deterministic, LLM-free
  pre-context compaction with a builtin<user<project rule overlay, grapheme-safe
  transforms, and token-savings stats; wired into `ingest_text` for HTML payloads.
- **Tool-policy risk tiers** (`governor/tool_policy.py`, OpenHuman §6): `ToolCapability`
  tiers + `TaskProfile`; two-point enforcement (prompt-visibility filter capped at 7 +
  runtime refusal logged to the audit chain); content-derived steps clamped to read-only.
- **Archivist** (`compounding/archivist.py`, OpenHuman §8): `clean_turns` → `compose_md`
  → `archive_report`/`archive_conversation`, content-addressed (idempotent), optional Logseq.
- **Per-module READMEs** (OpenHuman §7) for `governor/`, `subconscious/`, `compounding/`.
- **Scheduler Gate** (`governor/scheduler_gate.py`, OpenHuman §1, P0): host-courtesy
  throttle — the third axis alongside the Governor's budget + RAM guard. Resolves
  power/CPU/server signals to a policy (Aggressive/Normal/Throttled/Paused) and gates
  every LLM call through a cooperative `permit()` (sync translation of OpenHuman's async
  gate; `threading.Semaphore` global slot). Wired into Deep-Dive's researcher/synthesizer
  calls and the pipeline (real runs only); `[governor.scheduler_gate]` config block;
  env overrides (`LIGHTHOUSE_ON_AC_POWER`/`_BATTERY_CHARGE`/`_CPU_USAGE`/`_SERVER_MODE`,
  garbage→real-probe); `lighthouse doctor` reports current policy + reason.
- **Hotness Score** (`compounding/hotness.py`, OpenHuman §2, P0): deterministic, LLM-free
  entity-importance formula (`ln(mentions+1) + 0.5·distinct_sources + recency_decay +
  graph_centrality + 2·query_hits`), `TOPIC_CREATION_THRESHOLD = 10.0`, piecewise recency
  decay, and a `HotnessBreakdown` that decomposes every score into five named terms for the
  "why salient" tooltip. `distinct_sources` uses *independent*-source semantics (matches the
  discipline layer). Available as a Monitor salience scorer via `make_hotness_salience`.
  `EntityHotnessStore` persistence: `entity_hotness` SQLite side-table, `record_mention`
  (set-based source dedup), `should_materialise`/`hot_entities` dossier gate; wired into
  `ResearchPipeline.ingest_text` and `research()` via `track_entity()`.
- **`lighthouse eval` CLI**: runs the golden-set retrieval eval and reports
  precision@k / recall@k / MRR. Uses real backends (bge-m3 via Ollama, FlagReranker)
  when available, falling back to test-tier stubs otherwise; `--offline`, `--json`,
  `--k` flags. `eval.build_index()` now accepts injected embedder/store/reranker so
  the same harness becomes a production quality gate.
- **Entailment gate** (`verification/entailment.py`): lazy MiniCheck-Flan-T5-Large
  (primary) + HHEM-2.1-Open (fallback) entailment scorer; DisciplineReport gains
  `entailment_coverage` + `entailment_checked`; graceful 1.0 fallback when models absent
- **IterResearch shared scratchpad**: `CompactedContext` (open_questions/established_facts/
  ruled_out) injected into each round's researcher prompts — implements Tongyi's IterResearch
  dynamic workspace reconstruction (Alibaba-NLP/Tongyi DeepResearch, arXiv:2510.24701)
- **Real denoiser**: synthesizer LLM resolves contradictions and emits [CONTRADICTION]/[GAP]
  markers; `_parse_synthesizer_sections` round-trips the structured output back to Sections
- **Debate auto-wiring**: `_extract_debate_subquestions` fires `run_debate()` on load-bearing
  sections with [CONTRADICTION] markers; dispute crux added as a new sub-question (cap 2/round)
- **Auto-resolver** (`verification/resolver.py`): Halawi et al. (NeurIPS 2024) style
  machine-resolvable position resolution; `attempt_auto_resolve`, `run_resolver_pass`,
  `classify_resolution_kind`; `lighthouse resolver run` CLI command
- **Egress audit**: `lighthouse audit-egress` CLI command produces a Rich table of all
  network calls from the HMAC audit log; supports optional report file output
- **Editable research plan UI** (`PlanPreview`): before each research job, the user can
  review the framing (question type, critique warnings, sub-questions with inline edit/add/
  remove, framing selection) — implements Gemini Deep Research collaborative-planning UX
- **Elicit-style extraction table** (`EvidenceTable`): shows cited chunks as Source/Excerpt/
  Grade/Entailment rows in the draft reader; CSV export; `EntailmentBadge` component
- **Contextual Retrieval at ingest**: `llm_preamble_fn` generates 1-sentence LLM context
  per chunk prepended before embedding + BM25 (Anthropic Contextual Retrieval technique,
  Sep 2024; 67% top-20 retrieval failure reduction when combined with reranker)
- **Reranker always-on**: `make_reranker(prefer_real=True)` — FlagReranker
  (BAAI/bge-reranker-v2-m3) active by default when FlagEmbedding installed
- `POST /api/research/plan` endpoint: returns `FramedQuestion` as JSON for the plan preview UI
- `faithfulness` optional dep group: `minicheck>=0.1`, `sentence-transformers>=2.0`
- SearXNG API client (`sources/searxng.py`) for future mid-loop CRAG web fetch

### Changed
- Deep-Dive termination: `progress_threshold` 0.1→0.05; requires open_questions unchanged
  AND progress flat; adds `min_entailment_for_early_stop` seam parameter
- Deep-Dive `max_rounds` default 2→3
- Discipline gate `check()` now accepts `evidence_chunks=` for per-claim entailment scoring
- `DisciplineReport` gains `entailment_coverage: float = 0.0` and `entailment_checked: bool`
- `DraftReport` gains `evidence_chunks: list[HybridResult]` (accumulated across all rounds)
- `ResearchResult` gains `warnings: list[str]` (backend fallback messages)
- `Position` gains `resolve_by: str | None` (auto-set to +90 days) and `resolution_criterion`
- Backend fallback warnings now emitted via structlog and surfaced in CLI output
- `make_embedder` / `make_vector_store` return 3-tuples `(obj, name, warns)`

### Fixed
- `_record_positions`: removed dead `UPDATE positions SET resolved_at = NULL` block
- `StatusPill`: `done`/`completed` → green; `failed`/`rejected` → red (was incorrect)
- `ConfidencePill`: full WEP vocabulary including "remote" → `.wep.remote` (deep red)

## [0.2.0] — Sprint 29 (2026-05-28)

### Added (Sprint 29 — Six Researcher-Identified Quality Gaps)
- **LLM-powered framing**: `run_framing(gateway=...)` calls planner role with JSON-schema
  prompt; falls back to deterministic keyword baseline on any exception
- **Real denoiser** (Sprint 29 version): `_denoise(sections, *, gateway, job_id)` calls
  synthesizer; stub path (gateway=None) preserves citation-dedupe behavior
- **Auto web retrieval**: `_auto_fetch()` queries arXiv + OpenAlex when corpus is empty;
  gated by `not offline and _chunks_ingested == 0`
- `PipelineConfig.auto_fetch_sources` + `auto_fetch_max_results` config fields
- **Source diversity**: `check_source_diversity(evidence_chunks)` counts distinct
  `metadata["source"]` domains; `DisciplineReport.distinct_sources`
- **Calibration resolve_by**: `record_position()` defaults `resolve_by` to +90 days;
  `_ensure_extras` guards two new DB columns

### Changed (Sprint 29)
- `run_deepdive` threads `gateway` + `job_id` through to `run_framing()`
- Backend warnings: `make_embedder`/`make_vector_store` return 3-tuples; CLI prints warnings

## [0.1.0] — Sprints 1–28 (2026-05-28)

### Added (Sprints 1–28 — Infrastructure + Research Loop)
- Full SQLite-WAL spine: outbox+saga, intent drain, HMAC-chained audit log
- Governor: hierarchical token buckets, degradation tiers, runtime RAM guard via psutil
- Real Ollama dispatch: `backends/ollama.py` (chat, embed, pull, list_models)
- Real bge-m3 embeddings (1024-dim), QdrantStore (HNSW m=16, ef_construct=100)
- HybridSearch: BM25 (Okapi, k1=1.2, b=0.75) + dense ANN + RRF (k=60, Cormack 2009)
- FlagReranker (`BAAI/bge-reranker-v2-m3` via FlagEmbedding, lazy import)
- WEP confidence bands (ICD-203/Sherman Kent), Brier calibration scoring
- Sandbox: EICAR/PDF-JS/HTML-script/zip-bomb scanners, quarantine, broker
- Source adapters: arXiv, OpenAlex, PubMed, Crossref (all return `list[Document]`)
- Injection gate (weighted-regex + Spotlighting), egress proxy, loop detector
- Five research modes: Monitor (A), Deep-Dive (B), QUC (C), Digest (D), Debate (E)
- Web dashboard: 7 pages, SSE live updates, Cmd-K palette, light/dark theme
- Textual TUI: 7 screens, coastal theme
- ResearchPipeline: real-or-stub backends, discipline gate, calibration, audit
- Hardware probe: Apple M4 24GB (T2), budget-aware model selection
- CI: GitHub Actions, ruff, pytest; 792 → 814 tests

[Unreleased]: https://github.com/brennansk1/lighthouse-ai/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/brennansk1/lighthouse-ai/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/brennansk1/lighthouse-ai/releases/tag/v0.1.0
