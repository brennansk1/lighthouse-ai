# Lighthouse — capabilities & status

This file is the detailed capability surface behind the README. It is a working
inventory of what is built, written for engineers and reviewers. For the
plain-language tour, see the **Guide** tab in the dashboard; for the buyer-facing
overview, see [`README.md`](./README.md).

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
- **Evidence-grounded auto-resolver** (`verification/resolver.py`): at the deadline a
  position is resolved **only from freshly retrieved evidence** (never the model's own
  memory — Panickssery et al. NeurIPS 2024); anything it can't settle defers to a
  **human-resolution queue** in the Track tab
- **WEP confidence bands** (ICD-203) + Brier scoring + **evidence-derived probabilities**
  (source count / independence / entailment / contradiction — not a fixed heuristic) +
  honest calibration display: log score, Murphy decomposition, per-band reliability with
  Beta-Binomial shrinkage + credible intervals (`verification/calibration.py`)
- **Research-skills library** — **37 sources**, one skill per source (academic, clinical,
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
- **Sandbox data workspace** — a secured two-zone store (your uploads + the assistant's
  analysis workspace) with a user-set size limit, broker-scanned on entry, plus a
  capability-restricted analysis toolset and a dashboard **Sandbox** tab
- **Watch a website** — point Watch at any URL: a plain-language "can we watch this?"
  check, choose what counts as a change (any change / mentions / a number crosses /
  a section changes), get alerts (incl. desktop/Telegram notify)
- **Intent recipes** in the wizard (e.g. "Draft a literature review") that pre-fill
  mode + depth + sources; **`lighthouse skill new`** scaffolds a custom source skill
- **Settings**: connect data sources (free API keys, stored on-device) + **reproducibility**
  (lock the model — fixed seed + temperature 0, recorded in the provenance sidecar)
- **Global Pause** (dashboard button + `lighthouse pause`) stops all 24/7 work so you can
  reclaim your machine; honored by every scheduled loop
- **Hardware-aware**: KV/context OOM headroom + MoE-paging-aware model fit + RAM-aware
  concurrency guardrails (won't swap a 24 GB box; picks the best model that fits)
- **In-app guide** in the Guide tab covering every feature in plain language
- **Compounding intelligence** (`subconscious/`, `compounding/`): a scheduler-gated,
  overlap-guarded tick engine emits passive **reflections** (provenance-tracked, never
  auto-posted, capped per tick — acting on one spawns a fresh job) and actionable
  **escalations**, surfaced in Track's **Intelligence** view; a deterministic, LLM-free
  **Hotness Score** ranks entity salience for Watch + dossier materialization; the
  **Archivist** content-addresses conversations/reports (idempotent, optional Logseq)
- **SQLite-WAL spine**: outbox + saga compensation + HMAC-chained (tamper-evident) audit log
- **Governor**: hierarchical token buckets, loop detector, injection gate, degradation
  tiers, cost report, **tool-policy risk tiers** (capability tiers + runtime refusal logged
  to the audit chain), and a **Scheduler Gate** — a host-courtesy throttle that resolves
  power/CPU/server signals to a policy (Aggressive/Normal/Throttled/Paused) every LLM call
  passes through: the third axis alongside the budget + RAM guard
- **Sandbox**: EICAR / PDF-JS / HTML-script / zip-bomb scanners + quarantine
- **Web dashboard**: 9 tabs (Research, Library, Watch, Track, Activity, Sandbox,
  Health, Guide, Settings) — Research is the landing page; SSE live updates, light/dark
  theme, per-artifact-type viewers (report/digest/table/timeline/matrix/verdict/
  transcript) with Markdown/CSV/JSON export; depth selector in the Research wizard; the
  **Intelligence** surface (reflections + escalations) lives inside Track
- **TUI**: 7 Textual screens, themed coastal light/dark, offline-graceful
- **CLI**: `lighthouse`, `lighthouse-supervisor`, `lighthouse-tui` console scripts;
  `lighthouse audit-egress`, `lighthouse resolver run`, and more
- **Backend fallback warnings**: silent fallbacks logged and surfaced to the user
- **Citation source diversity**: distinct source domains counted per report
- **CI**: GitHub Actions, ruff clean, pytest

## Path to deployment

The capability surface is built and **green offline** (2950 tests). The honest gap to a
distributable release is almost entirely **live-data validation** — most subsystems were
built test-first against mocked backends and still need to be exercised against real LLMs,
real source APIs, and a real browser. **Running the live pass?** Start with the cold-start
runbook **[`docs/dev/LIVE_TESTING_HANDOFF.md`](./docs/dev/LIVE_TESTING_HANDOFF.md)** (env setup,
phased commands, thresholds). `docs/PRODUCTION_CHECKLIST.md` is the authoritative go/no-go doc;
the short version:

**Needs polish + full live-data testing (built, not yet validated end-to-end with real data):**
- **Real-LLM research quality** — framing planner, synthesizer denoiser, debate judge, and
  recommender LLM rerank all work offline; run them under `LIGHTHOUSE_REAL_BACKEND=1` (Ollama
  `bge-m3` + `qwen3` + FlagReranker) and score against the golden set / DeepResearch Bench.
- **Live source fetching through the egress guard** — the 37 skills fetch through
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

## Status

**3080+ tests passing · ~106 skipped (opt-in real-backend / litestream binary / absent optional models) · ruff clean · mypy 0 (blocking CI gate) · 275 modules · ~49k source lines · 37 research-skill sources · coverage ~82% · 4-wave codebase audit complete (~32 real bugs fixed incl. a redirect-SSRF and the audit-chain tamper-evidence). macOS M4 24 GB live-validated (17 bugs fixed against real deps). The offline-buildable product is feature-complete; the calibration pipeline is now evidence-grounded (no self-grading), every run emits a PROV-O sidecar, and budget/monitor notifications are wired. Every feature is measured against [`docs/DEFINITION_OF_DONE.md`](./docs/DEFINITION_OF_DONE.md), and the R5–R8 release gates are now turnkey — a soak harness (`scripts/soak.py`), systemd/launchd service units, and a release runbook ([`docs/RELEASE.md`](./docs/RELEASE.md)). Remaining gate: *running* the 24h soak + signing + cross-platform pass and observing the live calibration loop on the box — see Path to deployment.**

Status label: **pre-alpha, feature-complete for v1.0 scope; validation-phase before release.**
See [`docs/PRODUCTION_CHECKLIST.md`](./docs/PRODUCTION_CHECKLIST.md) and
[`FUTURE_FEATURES.md`](./FUTURE_FEATURES.md).
