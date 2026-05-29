# Lighthouse — local-first deep research

> The deep-research tool for regulated-industry knowledge workers who cannot use
> Gemini/OpenAI/Perplexity Deep Research on their actual working corpus.

A full research slice runs end-to-end, locally, today: ingest documents → frame the
question with an LLM-powered pipeline → retrieve with `bge-m3` embeddings + BM25 +
FlagReranker → synthesize with a local LLM via Ollama → enforce a citation-discipline
gate → record calibration positions → stage a draft → review it in the dashboard.
Every claim carries a WEP confidence band and an HMAC-chained audit log makes the
entire run tamper-evident.

## Why local-first matters

- **HIPAA / ABA Model Rule 1.6 / GDPR / ITAR compliance**: your corpus never leaves
  your hardware — no BAA required, no data-processing addendum.
- **FedRAMP-adjacent posture**: air-gap compatible; audit trail ready for review.
- **Full tamper-evident provenance**: HMAC-chained log, PROV-O metadata, replay
  verification — every claim is traceable back to a source chunk and model call.
- **Reproducible outputs**: model fingerprinting + drift detection; replay reconstructs
  the exact model-call trace.
- **Cost-free after hardware**: no per-query API fees; runs on an Apple M4 24 GB
  today, scales down gracefully to smaller machines.

## What works today

- **Real end-to-end research** with Ollama (`qwen3:14b` / `llama3.1:8b`) + `bge-m3`
  1024-dim embeddings + Qdrant (or in-memory fallback)
- **HybridSearch**: BM25 + dense ANN + RRF k=60 + FlagReranker (`bge-reranker-v2-m3`,
  always-on when FlagEmbedding is installed)
- **Contextual Retrieval**: LLM-generated 1-sentence preamble prepended to each chunk
  at ingest time (Anthropic pattern)
- **LLM-powered framing pipeline**: classify → critique → multiply-frames → decompose
  (planner role, falls back to keyword baseline)
- **IterResearch shared scratchpad**: `CompactedContext` injected into each round's
  researcher prompts
- **Real denoiser**: synthesizer LLM resolves contradictions, emits
  `[CONTRADICTION]` / `[GAP]` markers
- **Debate auto-wiring**: fires `run_debate()` on load-bearing `[CONTRADICTION]`
  sections; adds crux as a new sub-question
- **Entailment gate** (`verification/entailment.py`): lazy MiniCheck/HHEM; degrades
  gracefully to no-penalty when the PyPI package is absent
- **Auto web retrieval**: fetches arXiv + OpenAlex when corpus is empty at research
  start (CRAG-style pre-loop)
- **Auto-resolver** (`verification/resolver.py`): Halawi et al. style — machine-
  resolvable positions auto-resolved at deadline
- **WEP confidence bands** (ICD-203) + Brier calibration scoring + 90-day positions
- **Research-skills library** — **36 sources**, one skill per source (academic, clinical,
  legal, U.S.-federal, financial, economic-data, engineering, reference, media, 6 news
  outlets + a news orchestrator), each a self-contained folder discovered by directory scan;
  capability-restricted runner (a skill can't bypass the fetch/broker path); unsigned skills
  carry a `community` tag + WEP downgrade
- **Mode-aware source recommender + checkbox picker** — the wizard shows sources grouped by
  category with the recommended ones pre-checked and a reason; `recommend(question, mode,
  depth)` blends manifest rules + `bge-m3` SKILL.md similarity + optional LLM rerank
- **Contradiction artifact** — first-class, 3-layer detection (chunk / claim / cross-skill);
  surfaced per mode; auto-escalates to Adjudicate on load-bearing cross-skill disputes
- **Deep tier** — value-of-information branch prioritization + cross-node synthesis weaving +
  serializable resumable tree state
- **Acquisition stack** — politeness layer (robots/crawl-delay/rate budgets), ML injection
  classifier (ProtectAI deBERTa) behind the regex gate, hardened sandbox (YARA + pikepdf),
  full extraction chain (trafilatura → pdfplumber → pypdf → pdfminer → docling)
- **Source adapters**: arXiv, OpenAlex, PubMed, Crossref, Semantic Scholar, SEC EDGAR,
  CourtListener, ClinicalTrials.gov, WHO, FRED/BEA/BLS/World Bank/OECD/Census, GitHub,
  PyPI/npm/crates, Wikidata, Wayback, news wires (all return `Document` objects)
- **`lighthouse doctor news`** — news-outlet reachability + trust matrix; **per-skill eval**
  (recall@k + per-skill Brier calibration)
- **SQLite-WAL spine**: outbox + saga compensation + HMAC-chained audit log
- **Governor**: hierarchical token buckets, loop detector, injection gate, degradation
  tiers, cost report
- **Sandbox**: EICAR / PDF-JS / HTML-script / zip-bomb scanners + quarantine
- **Web dashboard**: 8 tabs (Research, Library, Watch, Track, Activity, Health,
  Info, Settings) — Research is the landing page; SSE live updates, light/dark
  theme, per-artifact-type viewers (report/digest/table/timeline/matrix/verdict/
  transcript) with Markdown/CSV/JSON export; depth selector in the Research wizard
- **TUI**: 7 Textual screens, themed coastal light/dark, offline-graceful
- **CLI**: `lighthouse`, `lighthouse-supervisor`, `lighthouse-tui` console scripts;
  `lighthouse audit-egress`, `lighthouse resolver run`, and more
- **Backend fallback warnings**: silent fallbacks logged and surfaced to the user
- **Citation source diversity**: distinct source domains counted per report
- **CI**: GitHub Actions, ruff clean, pytest

## Path to deployment

The capability surface is built and **green offline** (2476 tests). The honest gap to a
distributable release is almost entirely **live-data validation** — most subsystems were
built test-first against mocked backends and still need to be exercised against real LLMs,
real source APIs, and a real browser. `docs/PRODUCTION_CHECKLIST.md` is the authoritative
go/no-go doc; the short version:

**Needs polish + full live-data testing (built, not yet validated end-to-end with real data):**
- **Real-LLM research quality** — framing planner, synthesizer denoiser, debate judge, and
  recommender LLM rerank all work offline; run them under `LIGHTHOUSE_REAL_BACKEND=1` (Ollama
  `bge-m3` + `qwen3` + FlagReranker) and score against the golden set / DeepResearch Bench.
- **Live source fetching through the egress guard** — the 36 skills fetch through
  `ctx.fetch → politeness → broker`; validate each against its real API (rate limits, auth
  keys, parser drift, graceful degradation when a domain isn't trust-added).
- **Optional ML models** — reranker (precision@5), entailment/HHEM (faithfulness), deBERTa
  injection (ROC) — measured with the model installed, not just the heuristic fallback.
- **Web dashboard** — browser QA (Playwright) of every tab; only static/Babel checks done.
- **Calibration loop & Deep-tier resume** — wire the resolver cron + dispatcher-level
  checkpoint and observe a real multi-day Position resolve + a resumed Deep run.
- **Ops** — Qdrant + Litestream up; 24h supervisor soak; cross-platform (Linux/systemd);
  packaging (`pip install` / signed app); security review of egress/injection/sandbox.

**Deployment standard (every feature must clear this bar):**
1. **Tested** — unit (offline-deterministic) **and** a real-backend/live integration test
   gated on `LIGHTHOUSE_REAL_BACKEND=1`, green.
2. **Measured** — where a quality claim exists, a number on the golden set meets its
   threshold (e.g. retrieval precision@5 ≥ 0.40, faithfulness ≥ 0.80), not assumed.
3. **Degrades safely** — absent optional dep / blocked egress / offline ⇒ a clean fallback,
   never a crash; every fallback logged.
4. **Audited & honest** — provenance + audit chain record what ran; no fabricated citations;
   contradictions surfaced; confidence never overstated.
5. **Visible** — surfaced in the UI/CLI with plain-language labels and a clear failure state.

## Known limitations / not yet wired
- **Optional model packages** (`minicheck`, FlagEmbedding, ProtectAI deBERTa) are not pulled
  by default — those gates degrade gracefully to heuristics until installed.
- **Tier-B JS rendering** (`general_web.fetch_url_js`) is a declared stub; **Tier-C**
  fingerprint browsers are spec-only (opt-in, future).
- **Document-ingestion UI** for Survey/Reconstruct is still a CLI/programmatic path.
- **Deep-tier checkpoint** is serializable but not yet wired to dispatcher-level resume.
- Litestream replication (binary optional), Zotero adapter, RAPTOR/LangGraph backbone —
  deferred by design.

Status: **pre-alpha, feature-complete for v1.0 scope; validation-phase before release.**
See [`docs/PRODUCTION_CHECKLIST.md`](./docs/PRODUCTION_CHECKLIST.md) and
[`FUTURE_FEATURES.md`](./FUTURE_FEATURES.md).

## Quick start

```bash
# 1. Prerequisites
brew install ollama
ollama pull bge-m3          # embeddings (1.2 GB)
ollama pull qwen3:14b       # researcher / synthesizer

# 2. Install Lighthouse
pip install lighthouse-ai   # or: uvx lighthouse-ai

# 3. Initialize
lighthouse init

# 4. Start (optional: Qdrant for persistent vectors)
docker compose -f ~/.lighthouse/stack/lh-stack.yml up -d  # optional
lighthouse-supervisor &
open http://localhost:8765

# 5. Research
lighthouse research "Why did psychology's replication crisis emerge?"
```

Running from source:

```bash
uv sync
uv run lighthouse init
uv run lighthouse doctor        # readiness check
uv run lighthouse-supervisor    # then open http://127.0.0.1:8765/
```

Other commands: `lighthouse status`, `cost report`, `positions-due`,
`models {list,pull,info,bind}`, `quarantine list`, `audit verify`,
`audit-egress`, `resolver run`, `sandbox redteam`, `export <draft> --logseq <dir>`,
`pause` / `resume`, `replay <job_id>`.

## Research modes

Lighthouse runs seven research modes, each producing one typed **artifact**:

| Mode | Artifact | What it does |
|------|----------|--------------|
| **Watch** | digest | Monitor entities/sources over time; salient items, alerts vs digest |
| **Ask** | transcript | Cited, conversational Q&A grounded in the corpus |
| **Investigate** | report | Bounded TTD-DR deep-dive; sectioned, per-claim citations |
| **Survey** | evidence table | Screen many docs → PRISMA flow + attribute grid with entailment |
| **Reconstruct** | timeline | Sourced chronology; dedup + weighted date-conflict resolution |
| **Decide** | matrix | Score options × weighted criteria; sensitivity sweep + crux |
| **Adjudicate** | verdict | Structured multi-perspective debate naming the crux |

Launch from the **Research** tab (a 3-step wizard) or `POST /api/jobs`; the
dispatcher runs them one-per-tick (RAM-gated) and stages the artifact in the
**Library**. Legacy mode keys (`Deep-Dive`, `Monitor`, `QUC`, `Debate`) still
resolve via the registry alias map.

### Research depth (Quick → Deep)

Every corpus mode takes a **depth tier** — see
[`docs/research_depth_matrix.md`](./docs/research_depth_matrix.md):

| Tier | Feel | Behavior |
|------|------|----------|
| Quick | ~1–3 min | fast grounded scan |
| Standard | ~5–10 min | balanced, coverage-checked (≈ frontier deep research) |
| Thorough | ~20–60 min | + adversarial refutation + triangulation + coverage critic |
| Deep | hours (budgeted) | recursive question-tree to exhaustion — checkpointed |

**The invariant: depth scales coverage and confidence, never trust.** Every tier
runs the grounding gate — a claim is entailed by a real cited source or it is
dropped/flagged, never asserted. Claude & Gemini deep research time-box to
~10–20 min (≈ Standard); Thorough and Deep are depth they structurally can't reach.

### What makes the output trustworthy

- **Verifiable grounding** — citation + entailment gate; **zero fabricated
  citations** (a cited chunk id must exist in the corpus or the claim is rejected).
- **Adversarial refutation** — a skeptic tries to refute each key claim; refuted/
  contested claims don't stand (`verification/adversarial.py`).
- **Coverage critic** — coverage scored against the framing plan's load-bearing
  sub-questions; gaps trigger another round or are recorded as known-unknowns
  (`verification/coverage.py`).
- **Triangulation + contradictions** — key claims need ≥2 independent sources;
  source disagreements are surfaced, not smoothed (`verification/discipline.py`).
- **Provenance manifest** — every artifact records mode, depth, backend used
  (real vs mock), models, source count, metrics, and a content hash —
  reproducible and auditable.
- **Measured calibration** — forecasts become Brier-scored Positions over time.

The `lighthouse_ai.eval.research_benchmark` harness scores artifacts against this
bar and proves the grounding gate catches a planted hallucination.

## Architecture

```
Sources (arXiv · OpenAlex · PubMed · Crossref · RSS)
        │
        ▼
   Ingest + Sandbox (scanners · quarantine · injection gate)
        │
        ▼
   Contextual Chunker ──► BM25 Index
        │                      │
        ▼                      │
  bge-m3 Embedder ──► Qdrant / InMemory ◄── HybridSearch (RRF k=60)
                                                    │
                                                    ▼
                               FlagReranker (bge-reranker-v2-m3)
                                                    │
                                                    ▼
   Framing Pipeline (classify · critique · multiply · decompose)
        │
        ▼
   IterResearch Loop (researcher fan-out · CompactedContext scratchpad)
        │
        ▼
   Denoiser (synthesizer LLM · [CONTRADICTION]/[GAP] markers)
        │
        ├──► Debate auto-wire (on load-bearing contradictions)
        │
        ▼
   Discipline Gate (citation coverage · two-source rule · WEP downgrade)
        │
        ▼
   Entailment Gate (MiniCheck/HHEM · sourced-claim verification)
        │
        ▼
   Auto-Resolver · Brier Calibration · WEP Positions
        │
        ▼
   HMAC-Chained Audit Log ──► Draft ──► Dashboard / TUI / Logseq export
```

## Status

**2476 tests passing · 52 skipped (opt-in real-backend / litestream binary / absent optional models) · ruff clean · 262 modules · ~44k source lines · 36 research-skill sources · macOS M4 24 GB verified (real Ollama: Decide validated end-to-end, backend=ollama, RAM-gated). Live-data validation across the 36 skills + real-LLM quality is the remaining gate — see Path to deployment.**

## Development

```bash
uv run pytest -q                          # 2476 pass, 52 skip
uv run ruff check src tests               # 0 errors
LIGHTHOUSE_REAL_BACKEND=1 uv run pytest tests/test_backends_ollama.py  # real LLM
```

Contributions welcome. Open an issue to discuss before large PRs. All new features
require unit tests; integration tests for real-backend paths must be gated on
`LIGHTHOUSE_REAL_BACKEND=1` and must not start background processes.

## Documentation

- [`docs/MODE_PROCESSES.md`](./docs/MODE_PROCESSES.md) — **the 7 research modes in
  full detail** (algorithm, techniques, provenance, and optimality notes per mode)
- [`docs/WEB_SCRAPING.md`](./docs/WEB_SCRAPING.md) — web acquisition / scraping
  capabilities + evaluation strategies
- [`docs/research_depth_matrix.md`](./docs/research_depth_matrix.md) — depth tiers
  (Quick → Deep) × mode output
- [`docs/research_prompts/`](./docs/research_prompts/) — ready-to-run prompts to
  research better strategies/libraries for the modes and the scraping stack
- [`docs/lighthouse_design.md`](./docs/lighthouse_design.md) — full design specification
- [`docs/PRODUCTION_CHECKLIST.md`](./docs/PRODUCTION_CHECKLIST.md) — release-readiness status
- [`docs/webapp_tui_design.md`](./docs/webapp_tui_design.md) — dashboard / TUI design
- `docs/dev/` — working notes (sprint plans, build logs)

## License

MIT. See [LICENSE](./LICENSE).
