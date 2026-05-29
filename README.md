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
- **Source adapters**: arXiv, OpenAlex, PubMed, Crossref (all return `Document` objects)
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

## What is not yet wired

- SearXNG mid-loop CRAG fetch — seam is in place, SearXNG integration pending
- Litestream replication — config written, binary optional
- Zotero integration — adapter pending. **Logseq + Telegram are wired**: Logseq
  renders all 7 artifact types to graph pages; Telegram sends per-artifact
  review pings (honoring `[ui].notify_enabled`)
- Deep-tier recursive engine is built + tested; full dispatch wiring with
  per-node grounded research is in progress
- `minicheck` PyPI package does not exist yet — entailment gate degrades gracefully
- FedRAMP / HIPAA compliance one-pager — planned Sprint 32
- RAPTOR long-document tree — planned
- LangGraph — plain Python for-loop (intentional; LangGraph deferred)

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

**1283 tests passing · 3 skipped (opt-in real-backend / litestream binary) · ruff clean · macOS M4 24 GB verified (real Ollama: Decide validated end-to-end, backend=ollama, RAM-gated)**

## Development

```bash
uv run pytest -q                          # 1283 pass, 3 skip
uv run ruff check src tests               # 0 errors
LIGHTHOUSE_REAL_BACKEND=1 uv run pytest tests/test_backends_ollama.py  # real LLM
```

Contributions welcome. Open an issue to discuss before large PRs. All new features
require unit tests; integration tests for real-backend paths must be gated on
`LIGHTHOUSE_REAL_BACKEND=1` and must not start background processes.

## Links

- [`PRODUCTION_CHECKLIST.md`](./PRODUCTION_CHECKLIST.md) — line-by-line status
- [`lighthouse_design.md`](./lighthouse_design.md) — full design specification
- [`MODE_PROCESSES.md`](./MODE_PROCESSES.md) — per-mode process details
- [`SPRINT_QUALITY.md`](./SPRINT_QUALITY.md) — sprint acceptance criteria

## License

MIT. See [LICENSE](./LICENSE).
