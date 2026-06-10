# Lighthouse — local-first deep research

**Air-gapped, citation-audited research on a confidential corpus that never leaves
your machine.** Point Lighthouse at a corpus you can't send to a cloud service — a
legal matter, a patient set, a deal room — and get back deep, sourced research where
every claim cites a real document and the whole run is yours alone.

Three things it is built to hold true:

- **It stays on your machine.** The work runs locally on your own hardware and models.
  Nothing is sent to a research-as-a-service backend, and you can prove it yourself
  (see *Verify it yourself* below).
- **Every claim is grounded.** A claim that can't be traced to a real cited source
  chunk is dropped or flagged — never asserted. Zero fabricated citations is a hard
  invariant, at every depth tier.
- **Every run is auditable.** An HMAC-chained, tamper-evident log records which model
  ran, which sources were used, and a content hash for the result — so any reader can
  see exactly what produced it, and replay it.

![Lighthouse dashboard](docs/img/dashboard.png)
<!-- MAINTAINER: capture a real screenshot of the running dashboard (the Research tab
     landing page) and commit it to docs/img/dashboard.png. Do NOT fabricate this image. -->

> ### What this does NOT yet claim
>
> Lighthouse is in its validation phase. Be clear-eyed about the gaps:
>
> - **Not yet validated on your corpus.** The pipeline is built and green offline, but
>   it has not been exercised against your documents or measured for quality on them.
> - **No independent security review.** The egress, injection, and sandbox paths have
>   not yet had a third-party audit.
> - **Live measurement numbers pending.** Quality thresholds (retrieval precision,
>   faithfulness, calibration) are defined but not yet measured end-to-end on real data.
>
> See [`CAPABILITIES.md`](./CAPABILITIES.md) for the full, honest status and the path to
> a release.

## Verify it yourself

The privacy claim is meant to be **falsifiable**, not taken on faith — the corpus stays
on your machine and you can confirm it two ways:

- **`lighthouse audit-egress`** prints a signed report of every external network call in
  the tamper-evident audit log. If your run touched no external source, it confirms
  Lighthouse operated in airplane-mode for that window.
- **`LIGHTHOUSE_AIRGAP=1`** is a kill switch: with it set, the egress guard refuses *all*
  outbound network calls before any fetch is attempted. Run a research job under it and
  watch the corpus never leave the box.

Lighthouse is **designed to support workflows in regulated settings** — legal, clinical,
financial, and government work where documents cannot go to a third-party cloud — by
keeping the corpus local and the trail auditable. It is a tool you operate; it does not
by itself make you compliant with any regulation, and there is no certification behind it.

## What it does

A full research slice runs end-to-end, locally, today: ingest documents → frame the
question with an LLM-powered pipeline → retrieve with `bge-m3` embeddings + BM25 +
FlagReranker → **acquire as it learns** (a thin line of inquiry triggers new
per-sub-question web searches mid-run, through the egress/politeness rails) →
synthesize with a local LLM via Ollama, **streamed live to the dashboard** →
enforce a citation-discipline gate → record calibration positions → stage a draft →
review it in the dashboard with typed views per artifact (decision matrices with
what-would-flip-this analysis, evidence tables with contested-cell markers, timelines
with disputed-date splits, structured debate verdicts). Every claim carries a
confidence band and the HMAC-chained audit log makes the entire run tamper-evident.

The full capability surface, the path to deployment, and the test/status wall live in
**[`CAPABILITIES.md`](./CAPABILITIES.md)**. The in-app **Guide** tab walks every feature
in plain language.

## Quick start

Install from source with `uv` — this is the primary, supported path today:

```bash
# 1. Prerequisites
brew install ollama
ollama pull bge-m3          # embeddings (1.2 GB)
ollama pull qwen3:14b       # researcher / synthesizer

# 2. Install Lighthouse from source
git clone https://github.com/<your-org>/lighthouse.git
cd lighthouse
uv sync

# 3. Initialize + readiness check
uv run lighthouse init
uv run lighthouse doctor

# 4. Start (optional: Qdrant for persistent vectors)
docker compose -f ~/.lighthouse/stack/lh-stack.yml up -d  # optional
uv run lighthouse-supervisor    # then open http://127.0.0.1:8765/

# 5. Research
uv run lighthouse research "Why did psychology's replication crisis emerge?"
```

> **Footnote — `pip install lighthouse-ai` / `uvx lighthouse-ai` are not available yet.**
> Lighthouse is **not yet published to PyPI**, so the packaged install paths do not work
> today. Install from source with `uv sync` as above until a release is cut.

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
| Quick | ~1–3 min | fast grounded scan, one upfront source pass |
| Standard | ~5–10 min | iterative: thin sub-questions re-search the web mid-run (≤60 docs) |
| Thorough | ~20–60 min | wider acquisition (≤150 docs, multi-phrasing) + adversarial refutation + two-source rule + coverage critic |
| Deep | hours (budgeted) | recursive question tree; every branch runs its own searches (≤400 docs) and chases the most-cited links — checkpointed |

**The invariant: depth scales coverage and confidence, never trust.** Every tier
runs the grounding gate — a claim is entailed by a real cited source or it is
dropped/flagged, never asserted. Claude & Gemini deep research time-box to
~10–20 min (≈ Standard); Thorough and Deep buy the same acquire-as-you-learn
loop more time, more sources, and a skeptic pass — depth a time-boxed service
structurally can't reach, with citation honesty they don't enforce.

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

Lighthouse is **pre-alpha, feature-complete for v1.0 scope, in its validation
phase before release.** The detailed test/build status wall, the path to deployment,
and the full capability inventory live in **[`CAPABILITIES.md`](./CAPABILITIES.md)**.

## Development

```bash
uv run pytest -q                          # 3140+ pass, ~106 skip
uv run ruff check src tests               # 0 errors
uv run mypy src/lighthouse_ai             # 0 errors (blocking CI gate)
LIGHTHOUSE_REAL_BACKEND=1 uv run pytest tests/test_backends_ollama.py  # real LLM
```

Contributions welcome. Open an issue to discuss before large PRs. All new features
require unit tests; integration tests for real-backend paths must be gated on
`LIGHTHOUSE_REAL_BACKEND=1` and must not start background processes.

## Documentation

- [`CAPABILITIES.md`](./CAPABILITIES.md) — **the full capability surface, path to
  deployment, and test/status wall** (the detailed inventory behind this README)
- [`docs/MODE_PROCESSES.md`](./docs/MODE_PROCESSES.md) — **the 7 research modes in
  full detail** (algorithm, techniques, provenance, and optimality notes per mode)
- [`docs/WEB_SCRAPING.md`](./docs/WEB_SCRAPING.md) — web acquisition / scraping
  capabilities + evaluation strategies
- [`docs/research_depth_matrix.md`](./docs/research_depth_matrix.md) — depth tiers
  (Quick → Deep) × mode output
- [`docs/research_prompts/`](./docs/research_prompts/) — ready-to-run prompts to
  research better strategies/libraries for the modes and the scraping stack
- [`docs/lighthouse_design.md`](./docs/lighthouse_design.md) — full design specification
- [`docs/DEFINITION_OF_DONE.md`](./docs/DEFINITION_OF_DONE.md) — the production-grade bar (what "done" means)
- [`docs/PRODUCTION_CHECKLIST.md`](./docs/PRODUCTION_CHECKLIST.md) — release-readiness status
- [`docs/RELEASE.md`](./docs/RELEASE.md) — the live-only release gates (soak, cross-platform, signing, PyPI) made turnkey
- [`docs/LIVE_TEST_PLAN.md`](./docs/LIVE_TEST_PLAN.md) — **the live validation matrix**: every test that must run on real hardware/backends, each with its pass standard
- [`deploy/`](./deploy/) — systemd / launchd service units for running the supervisor
- [`docs/webapp_tui_design.md`](./docs/webapp_tui_design.md) — dashboard / TUI design
- `docs/dev/` — working notes (sprint plans, build logs)

## License

MIT. See [LICENSE](./LICENSE).
