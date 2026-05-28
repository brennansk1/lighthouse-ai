# Changelog

All notable changes to Lighthouse are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased] — Sprints 30–32 (2026-05-28)

### Added
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
