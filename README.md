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
- **Web dashboard**: 7 pages (Home, Jobs, Drafts, Topics, Positions, Health, Settings),
  SSE live updates, light/dark theme, Cmd-K palette, editable research plan
  (PlanPreview before each run), Elicit-style extraction table in draft reader
- **TUI**: 7 Textual screens, themed coastal light/dark, offline-graceful
- **CLI**: `lighthouse`, `lighthouse-supervisor`, `lighthouse-tui` console scripts;
  `lighthouse audit-egress`, `lighthouse resolver run`, and more
- **Backend fallback warnings**: silent fallbacks logged and surfaced to the user
- **Citation source diversity**: distinct source domains counted per report
- **CI**: GitHub Actions, ruff clean, pytest

## What is not yet wired

- SearXNG mid-loop CRAG fetch — seam is in place, SearXNG integration pending
- Litestream replication — config written, binary optional
- Logseq / Zotero / Telegram integrations — adapters exist, not wired into main flow
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

| Mode | Name | Description |
|------|------|-------------|
| A | Monitor | Continuous RSS / source watch; classify → alert or digest |
| B | Deep-Dive | Multi-round iterative research with denoiser + debate + entailment gate |
| C | QUC (Quick) | Single-pass cited answer with calibration position |
| D | Digest | Scheduled briefing synthesized from monitored sources |
| E | Debate | Structured pro/con with LLM judge; auto-fired on contradictions |

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

**814 tests passing · 3 skipped (opt-in real-backend / litestream binary) · ruff clean · CI green · macOS M4 24 GB verified**

## Development

```bash
uv run pytest -q                          # 814 pass, 3 skip
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
