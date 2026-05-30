# Lighthouse — Production Readiness Checklist

Status snapshot: **269 Python modules · ~49,000 source lines · 127 test files · 2816 tests pass · 103 opt-in skips · 37 research-skill sources · ruff clean · mypy 0 (blocking) · coverage ~82%**. A 4-wave full-codebase audit fixed ~32 real bugs (redirect-SSRF, audit-chain tamper-evidence, skill import-guard escapes, data-loss/durability, dead planner path, …) — each with a regression test. Shipped since the last snapshot: Sandbox workspace, Watch-a-website (v2), intent recipes, skill-scaffold generator, steerability/reproducibility, Settings API-key onboarding, global Pause, hardware OOM/utilization guardrails, Watch-alert notifications, and the in-app Info-tab guide.
Legend: ✅ done & tested (offline) · 🟡 built but needs-real-backend/live-data · 🔌 built, needs runtime wiring · ⬜ not started.

A "vertical slice" of the product works **end-to-end, locally, today**: ingest documents → frame the question → retrieve with real `bge-m3` embeddings → synthesize with a real local LLM (Ollama) → enforce citation discipline → record calibration positions → stage a draft → approve it in the dashboard → export to Logseq. Everything below tracks the gap from that slice to full production.

> **Where we are:** the v1.0 capability surface is **built and green offline** (2476 tests).
> The remaining gate to a distributable release is overwhelmingly **live-data validation** —
> most subsystems were built test-first against mocked backends and still need to be exercised
> against real LLMs, real source APIs (the 36 skills), real optional ML models, and a real
> browser. The **Deployment readiness** section directly below is the go/no-go summary; the
> per-feature acceptance tables (further down) hold the detail.

---

> **Running the live pass on the Mac mini?** Hand a fresh session
> **[`docs/dev/LIVE_TESTING_HANDOFF.md`](./dev/LIVE_TESTING_HANDOFF.md)** — a self-contained cold-start
> runbook (environment setup, the phased commands below, thresholds, and where to record results).

## Deployment readiness — what to polish + fully test with live data

Everything in this section is **built and unit-green offline**; the work is to validate it with
real data and harden it. Grouped by priority.

### A. Real-LLM research quality (highest leverage — the core product claim)
- 🟡 **Framing planner** (`framing/pipeline.py`) — run primary LLM path under
  `LIGHTHOUSE_REAL_BACKEND=1`; standard: ≥90% question-type agreement vs the golden set, frame
  output coherent; deterministic keyword fallback unchanged.
- 🟡 **Synthesizer denoiser** (`modes/deepdive.py`) — real synthesizer merges sections + emits
  `[CONTRADICTION]`/`[GAP]`; standard: RAGAS/DeepResearch-Bench faithfulness ≥ 0.80, no fabricated
  citations, contradiction-resolution visible.
- 🟡 **Debate LLM judge** (`modes/debate.py`) — names the load-bearing crux on real models.
- ✅ **Recommender pick quality** (`skills/recommender.py`, rule path, 2026-05-29 live) — gated
  skill-recommender **recall@5 = 1.000** (15 gold cases, was 0.40 before the fix). Live testing exposed
  two real defects, now fixed with regression tests: composing utilities (`retraction_watch`) were
  recommended as primary sources, and explicitly-named sources ("Reuters", "arXiv") were buried under the
  academic cluster. LLM-rerank lift over the rule path still optional to measure (rule path already
  saturates the gold eval).
- ✅ **End-to-end per mode** (Investigate/Survey/Reconstruct/Decide/Adjudicate/Ask/Watch, 2026-05-29
  live) — **7/7** ran through `dispatch_once` against the real gateway (`llama3.1:8b`, RAM ~7.2 GB free,
  no swap) and produced their artifact passing the discipline gate (valid provenance, numeric
  citation_coverage, no fabrication). Watch exposed + fixed a real dead-wire: `_adapt_watch` wasn't
  threading `topic_interests` to the LLM salience scorer (gap #15) — now wired, with regression tests.
- ✅ **Browser QA — dashboard renders in real chromium** (Playwright, 2026-05-29): all 7 nav pages
  (Research/Library/Watch/Sandbox/Health/Info/Settings) load with **zero console errors, zero uncaught
  exceptions, no white-screens** — confirming the in-browser babel-standalone JSX compile + React mount
  work (which the in-process TestClient API tests can't verify). Bounded harness
  `scripts/browser_smoke.py` (in-thread uvicorn, ephemeral port; screenshots to /tmp).
- ✅ **Browser QA — core interaction flows** (`scripts/browser_flow.py`, 2026-05-29): driving the live UI
  end-to-end — the 3-step Research wizard (pick mode → frame question → review → **Launch**) POSTs
  `/api/jobs` → 200 and the job appears (mode=investigate, queued); the global **Pause all** button flips
  the backend to `{status: paused_soft, paused: true}` and back; the **Sandbox upload** flow stores a
  benign file and **blocks an EICAR payload** through the live scanners (security boundary validated end-
  to-end through the UI, not just unit tests). Remaining: a11y/visual-regression.

### B. Live source fetching — the 37 skills (validate each against its real API)
- ✅ **37/37 skills live-fetched** (2026-05-29, `test_real_skills_fetch.py`, bounded `max_results=2`):
  no endpoint-shape drift, **zero unhandled exceptions**, audit line per fetch. Keyless sources returned
  real documents (arxiv, AP, BBC, BLS, census, clinicaltrials, crossref, federal_register, github,
  guardian, internet_archive, news_orchestrator, npr, oecd, openalex, pubmed, sec_edgar, semantic_scholar,
  wikidata, wikipedia, world_bank, …). Key-gated sources with no key configured degraded gracefully with
  an actionable `lighthouse trust add <domain>` note (congress 403, fred 400, govinfo 401). Remaining:
  validate the key-gated sources *with* keys set, and per-skill recall@k on a held-out set.
- 🟡 **General Web** snippet-fallback + SearXNG path on a live SearXNG.
- 🟡 **YouTube / IA-AV transcripts** via the shared `sources/transcript.py` against real captions.
- 🔌 **Tier-B JS rendering** (`general_web.fetch_url_js`) — currently a stub; build Crawl4AI/
  Playwright (scheduler-gated, RAM-capped, `fetch_backend="js"` tag + downgrade) before sites that
  need it count as covered.

### C. Optional ML models (measure with the model installed, not just the fallback)
- ✅ **Retrieval ranking quality** (real `bge-m3` + real `bge-reranker-v2-m3`, 2026-05-29 live):
  **recall@5 = 1.000, MRR = 1.000** both base and with FlagReranker — perfect ranking. **NOTE (live
  finding):** precision@5's ceiling here is **0.20** (the golden set labels one relevant doc per query),
  so the old `≥0.40`/`≥0.55` precision bars were unreachable by construction. The gated tests +
  `lighthouse eval` now gate on recall@5 + MRR; precision@5 is reported informationally against its
  ceiling.
- ✅ **Entailment/HHEM faithfulness gate** (real `sentence-transformers`, 2026-05-29 live): **mean =
  1.000** on the 20-pair golden set (threshold ≥ 0.80) — all entailing claims scored above threshold.
- ✅ **ProtectAI deBERTa injection classifier** (real `transformers`+`optimum`, 2026-05-29): 24/24
  integration tests — the ML scorer composes behind the regex gate, verdict shape/threshold unchanged,
  graceful regex fallback when libs absent. (Full ROC vs regex on a labeled corpus still to be measured.)
- ✅ **Sandbox hardening** (real YARA + pikepdf, 2026-05-29): redteam corpus **29/29** — OpenAction-JS
  PDF quarantined, malformed PDF quarantined, EICAR detected, benign PDF/HTML clean (**0 false
  positives**). Installing the libs surfaced + fixed 3 latent issues (pikepdf-10 test-helper API,
  `YaraScanner._get_rules` availability consistency, a pikepdf-typed mypy error). Real scanners now active
  by default. Remaining for full ⬜→✅: a larger real-world hostile corpus + ClamAV.

### D. Surfaces & ops
- ⬜ **Browser QA (Playwright)** of every dashboard tab — 0 console errors, axe a11y pass,
  keyboard-reachable; verify the new source picker, contradictions, known-unknowns, trust matrix,
  `doctor news` surfacing. (Only static/Babel checks done.)
- 🔌 **Calibration loop live** — wire the resolver cron (`supervisor.py` hook exists, gated) and
  observe a real Position resolve + Brier update; surface per-skill/per-mode calibration in Track.
- 🔌 **Deep-tier resume** — serializable tree state exists; wire dispatcher-level checkpoint to
  `state.db` and prove a resumed multi-hour run.
- 🟡 **Persistent vectors / replication** — Qdrant up; Litestream binary installed; restore drill.
- 🟡 **Packaging — clean-room install verified** (2026-05-29): `uv build` produces a wheel that bundles
  all package data (23 web/static files incl. index.html, model catalog yaml, 37 skill manifests + 37
  SKILL.md). Installed into a **fresh py3.11 venv with base deps only**: all 3 console scripts
  (`lighthouse`/`lighthouse-supervisor`/`lighthouse-tui`) work, `lighthouse eval --offline` runs
  (recall@5/MRR 1.000), and the bundled dashboard + skills + catalog are accessible. Remaining: signed
  macOS app + launchd/systemd unit + PyPI publish flow.
- 🟡 **Supervisor integration smoke** (`scripts/supervisor_smoke.py`, 2026-05-30): all **5 daemon loops**
  (subconscious/monitor/dispatch/resolver/backup) boot and tick for 30 s without dying, `/api/health`
  responds 200, global Pause flips `{paused_soft}`, web shuts down cleanly, RAM stable. The **full 24 h
  soak** (slow-leak detection) still ⬜.
- ✅ **Security review** of egress/injection/sandbox boundary (2026-05-29): Areas 1/2/4 well-defended;
  fixed a scan-time zip-bomb DoS; 2 low-priority residuals in `FUTURE_FEATURES.md` §10.
- ⬜ **24h supervisor soak** (no OOM/slow-leak), **cross-platform** (Linux/systemd), **signed app +
  launchd/systemd unit**, **PyPI publish**.

### Deployment standard — the bar EVERY feature must clear (go/no-go)
1. **Tested** — offline-deterministic unit tests **and** a real-backend/live integration test
   gated on `LIGHTHOUSE_REAL_BACKEND=1`, both green in CI.
2. **Measured** — any quality claim has a number on the golden set meeting its threshold
   (precision@5 ≥ 0.40, faithfulness ≥ 0.80, source recall@10 ≥ 0.8, sandbox 100%/0-FP), not assumed.
3. **Degrades safely** — absent optional dep / blocked egress / offline ⇒ a clean fallback, never a
   crash; every silent fallback logged and surfaced.
4. **Audited & honest** — provenance + HMAC audit record what ran; zero fabricated citations;
   contradictions surfaced; confidence never overstated (WEP downgrade applied).
5. **Visible** — exposed in the UI/CLI with plain-language labels and a clear failure/empty state.
6. **Repo gates** — `ruff` clean, `mypy` clean on public modules, CI green on macOS + Linux,
   coverage ≥ 80% overall (≥ 90% persistence/governor/verification).

### Phased timeline to first deployment
- **Phase 1 — Measure (the core claim):** A (real-LLM quality) + C-reranker/entailment on the golden
  set + stand up CI (pytest+ruff+mypy, macOS+Linux). Exit: precision@5 + faithfulness thresholds met,
  CI green. *This is the gate that proves "better than frontier."*
- **Phase 2 — Live sources:** B — validate the 36 skills against real APIs in tiers (regulated-wedge
  first: PubMed/ClinicalTrials/CourtListener/SEC EDGAR/Federal-Register; then academic/econ/news);
  per-skill recall@k recorded. Exit: every shipped skill has a green live test + a coverage number.
- **Phase 3 — Surfaces & ops:** D — browser QA, calibration cron + Deep-tier resume wired, Qdrant +
  Litestream, sandbox hardening on a real corpus, security review. Exit: the go/no-go bar met for
  every feature.
- **Phase 4 — Package & ship:** 24h soak + DR drill, cross-platform, packaging + signing, docs pass.
  Exit: a researcher can `pip install lighthouse-ai` and reach the Definition of done below.

---

## Stage 0 — Foundations & durability

- ✅ Python package (`uv`, `pyproject.toml`, MIT, src layout)
- ✅ `lighthouse` CLI (typer + rich): init, start, stop, status, doctor, pause, resume
- ✅ Supervisor process + FastAPI control plane (127.0.0.1:8765) with `/health`
- ✅ SQLite spine with §26.1 PRAGMA discipline (WAL, busy_timeout, synchronous=NORMAL, FK on)
- ✅ Schema migrations (5 DBs: state, audit, intents, positions, hypotheses)
- ✅ Outbox + Saga compensation + Effector (idempotent, retry/backoff, dead-letter)
- ✅ Governor: hierarchical token buckets, degradation tiers, trip/reset, cost report
- 🟡 Litestream replication — config + lag reporting + `LitestreamRunner` built; **binary not installed**, replication not started
- ✅ restic backup + integrity job — wired: `lighthouse backup`, `lighthouse integrity` (§26.3/§26.5). 🟡 not yet on a cron/supervisor schedule.
- ⬜ 24-hour soak test; cross-platform (Linux systemd) validation

## Stage 1 — Hardware adaptation, models, RAG, sandbox

- ✅ Hardware probe (platform/arch/RAM/GPU/backends/tier) + `chosen_models.yaml` writer
- ✅ Model Gateway: role routing, fingerprinting, drift detection, **real Ollama dispatch**, mock fallback
- ✅ Budget-aware model selection (§5.2) + **MoE-paging awareness** + **runtime RAM guard** (won't OOM)
- ✅ Model pull preflight (disk-safety: refuses pulls that would fill the disk)
- ✅ `lighthouse models {list,pull,info,prune,bind}` — resolves capability-classes → real installed tags
- ✅ RAG: semantic chunker, BM25, RRF fusion, hybrid search, contextual-retrieval helper
- ✅ **Contextual Retrieval**: LLM-generated 1-sentence preamble prepended to each chunk at ingest (Anthropic pattern)
- ✅ Real embeddings via **`bge-m3` (Ollama, 1024-dim)** — verified, semantics correct
- ✅ **Reranker always-on** (`prefer_real=True`): **FlagReranker (`bge-reranker-v2-m3`)** active when FlagEmbedding installed; `ScoreReranker` fallback otherwise
- 🟡 Vector store: `InMemoryStore` (real) + **`QdrantStore` (code-complete, Qdrant not running)** — `docker compose up` to enable
- ✅ Sandbox broker + quarantine + scanners (EICAR, PDF-JS, HTML-script, zip-bomb) + redteam
- 🟡 Real sandbox: pure-Python scanners only — **bubblewrap/sandbox-exec isolation, ClamAV, YARA, qpdf, oletools** not wired
- ✅ Document ingestion (`ingest.py`) wired into `research --url` (fetch → sandbox → extract → corpus). 🟡 trafilatura/pypdf optional (regex/text fallback active until installed).

## Stage 2 — Question framing + adaptive RAG

- ✅ Framing pipeline: question typing, critique, frame multiplication, decomposition, load-bearing detection — **LLM-powered** (planner role, keyword baseline fallback)
- ✅ Adaptive RAG router (vector / agentic / graph / recency / none)
- 🟡 Classifiers are rule-based — **ML question classifier (DistilBERT)** not trained
- ⬜ Question Library (golden-set framings) lookup

## Stage 3 — Deep-Dive (TTD-DR backbone)

- ✅ Skeleton → researcher fan-out → denoiser → discovery-progress termination
- ✅ **IterResearch shared scratchpad**: `CompactedContext` injected into each round's researcher prompts
- ✅ **Real denoiser**: synthesizer LLM resolves contradictions, emits `[CONTRADICTION]` / `[GAP]` markers
- ✅ **Debate auto-wiring**: fires `run_debate()` on load-bearing `[CONTRADICTION]` sections; adds crux as new sub-question
- ✅ **Entailment gate** (`verification/entailment.py`): lazy MiniCheck/HHEM — 🔌 `minicheck` PyPI package absent; gate degrades gracefully to 1.0 (no-penalty) without it
- ✅ **Auto web retrieval**: fetches arXiv + OpenAlex when corpus is empty at research start (CRAG-style pre-loop) — 🔌 SearXNG mid-loop fetch seam exists, SearXNG integration not yet wired
- ✅ ReSum-style `compact()` (structured) — 🟡 naive truncation, not the full recipe
- ⬜ Adversarial search / ACH, FActScore atomic verification, argument-graph inference
- ⬜ LangGraph runtime (currently plain-Python orchestration; no checkpoint/stream/resume)

## Stage 4 — Verification, calibration, compounding knowledge

- ✅ WEP bands (ICD-203), Brier scoring, Position Registry, hypothesis tracking, skills storage
- ✅ HMAC-chained audit log (append, seal, verify)
- ✅ **Quality discipline gate** (§12): claim extraction, citation coverage, two-source rule, WEP downgrade
- ✅ **Calibration loop closed** — research emits Positions; `lighthouse positions-due`; 90-day positions with auto-resolve
- ✅ **Auto-resolver** (`verification/resolver.py`): Halawi et al. style — machine-resolvable positions auto-resolved at deadline; `lighthouse resolver run` CLI
- ✅ **Citation source diversity**: distinct source domains counted per report
- ✅ **Backend fallback warnings**: silent fallbacks logged and surfaced to user
- ✅ Reproducibility: `lighthouse replay <job_id>` wired (reconstructs the model-call trace + drift verify against installed digests, §27.8); `provenance.py` PROV-O emitter built. 🔌 PROV-O sidecar not yet emitted per research run.
- ⬜ Re-verification scheduler; track-record-based prior adjustment; A-MEM auto-linking / dossiers

## Stage 5 — Web dashboard (production)

- ✅ 7 pages: Home, Jobs, Drafts, Topics, Positions, Health, Settings (React + babel-standalone, served by FastAPI)
- ✅ Component library (skeletons, modals, side panes, toasts, accessible tables), hash router, **Cmd-K palette**, **error boundary**, **light/dark theme**, SSE live updates
- ✅ **Editable research plan**: `PlanPreview` shown before each run, user can edit before confirming
- ✅ **Elicit-style extraction table** in draft reader
- ✅ JSON API (~25 endpoints) + SSE event bus
- ⬜ **Browser render verification** (static checks pass: Babel compile, shared-scope no-collision, serving, symbol contract — but no visual QA yet)

## Stage 6 — TUI + remaining modes

- ✅ Textual TUI: 7 screens, themed (coastal light/dark), widgets, command palette, flat keymap, offline-graceful (34 tests)
- ✅ Mode A Monitor (RSS, live) · Mode C QUC · Mode D Digest · Mode E Debate
- 🟡 Modes simplified: Debate judge, Digest scheduling/notification, Monitor novelty/retraction-watch not deep

## Cross-cutting subsystems (built in parallel sprints)

- ✅ Governor guards wired: **loop detector** in the Gateway (raises `LoopTripped` on runaway), **injection gate** screens every ingested chunk (injected content never enters the corpus). 🔌 `egress_proxy` built+tested but not yet on the fetch path.
- ✅ **Scheduler Gate** (`governor/scheduler_gate.py`, OpenHuman §1): host-courtesy throttle (power/CPU/server → Aggressive/Normal/Throttled/Paused); cooperative `permit()` wraps Deep-Dive LLM calls; `lighthouse doctor` reports policy. See `OPENHUMAN_INTEGRATION.md`.
- ✅ **Hotness Score** (`compounding/hotness.py`, OpenHuman §2): deterministic LLM-free entity-importance with named-term breakdown; available as a Monitor salience scorer. 🟡 persistence table + dossier materialisation deferred.
- ✅ Notifications (`notify/`): desktop / Discord / email + dispatcher; fired on `draft_ready` from the research command. 🔌 not yet fired on `budget_trip` / `monitor_alert` from the Governor/modes.
- ✅ Source adapters: RSS, **arXiv**, **OpenAlex**, **PubMed**, **Crossref** (all return `Document` objects)
- ✅ Logseq export (filesystem markdown) — `lighthouse export <draft> --logseq <dir>`
- ✅ **`lighthouse audit-egress` CLI command**
- ⬜ Integrations: Zotero, Telegram bot, Obsidian/Notion, menu-bar app (adapters exist, not wired into main flow)
- ⬜ Specialty adapters: SEC EDGAR, CourtListener, USPTO, SearXNG web search
- ⬜ Cloud escalation (litellm + PII strip + cost preview)
- ⬜ Injection gate ML model (ProtectAI deBERTa); Spotlighting wired into prompt construction

---

## Pending test / verification passes (gates to "production")

- [ ] **Browser render QA** of all 7 webapp pages (manual + ideally Playwright)
- [ ] **Real-backend integration suite** run green with `LIGHTHOUSE_REAL_BACKEND=1` (Ollama + Qdrant up)
- [x] ~~Wire replay, restic/integrity, ingestion, notifications into the CLI~~ (done — `replay`/`backup`/`integrity`/`research --url`/draft_ready notify)
- [x] ~~Wire the Governor guards (loop detection, injection gate) into the gateway + research loop~~ (done — egress proxy built+tested, not yet on fetch path)
- [ ] Wire egress proxy into the fetch path; emit PROV-O sidecar per run; schedule backup+integrity on a cadence
- [ ] Fire notifications on `budget_trip` / `monitor_alert`
- [ ] **Coverage target** (design: ≥80% on persistence/supervisor — currently met there; raise overall)
- [ ] **Lint + type-check clean**: `ruff check` and `mypy` with no errors
- [ ] **Cross-platform**: Linux (systemd unit, bubblewrap, /var paths) validated
- [ ] **24-hour supervisor soak** (no OOM, no leak) + disaster-recovery drill (kill mid-write → restore)
- [ ] **Sandbox redteam in CI** (weekly), real ClamAV/YARA enabled
- [ ] **Security review** of the egress/injection/sandbox boundary
- [ ] **Packaging**: PyPI publish flow, Homebrew tap / signed macOS app, launchd/systemd install verified
- [ ] **Replay determinism** check (byte-exact where digests match; structural otherwise)

## Definition of done (v1.0)

A researcher can `pip install lighthouse-ai`, run `lighthouse init && lighthouse start`, point it at sources, and get **honest, cited, calibrated** research — running entirely on their own hardware — with the dashboard/TUI for control, durable storage with automatic recovery, and every claim traceable through a tamper-evident audit log.

---

# Acceptance criteria & test standards

This section is the bar each feature must clear before we call it production-ready.
Every row lists the **tests required**, the **standard (pass threshold)**, and the
current **status**: ✅ met · 🟡 partial / not yet measured · ⬜ not tested.
Thresholds come from the design doc's per-sprint testing requirements where stated;
otherwise they are set here.

Test-type legend: **U** unit · **I** integration (real deps, skip-if-absent) ·
**E** end-to-end · **P** property-based (Hypothesis) · **Chaos** fault-injection ·
**Perf** latency/throughput · **Sec** adversarial.

## 1. Persistence & durability

| Feature | Tests required | Standard to pass | Status |
|---|---|---|---|
| SQLite PRAGMA discipline | U: every `.db` opens with all §26.1 PRAGMAs; readback asserts | 100% of opens pass PRAGMA assertions; WAL on every on-disk db | ✅ |
| Migrations | U: forward apply, idempotent re-run, CHECK constraints reject bad rows | re-run is a no-op; bad inserts raise | ✅ |
| Outbox / saga | U+P+Chaos: idempotency by key; kill effector mid-drain | **zero** duplicate or orphaned writes after recovery | ✅ (chaos at 50 intents; ⬜ scale to 1000) |
| Litestream replication | I: start replicate, write, restore to fresh path, integrity ok | replica lag **<10s** sustained; restore integrity `ok` | 🟡 binary not installed in CI |
| restic backup | I: init → backup → check → snapshots | `restic check` clean; restore RTO **<1 min** for state.db | 🟡 wired, not yet I-tested with real restic |
| Disaster recovery | E: kill supervisor mid-write → restore → schema intact | in-flight jobs marked `interrupted`; no corruption | 🟡 sqlite-backup variant ✅; full litestream drill ⬜ |
| 24h soak | Perf: supervisor runs 24h under load | no OOM, no fd/conn leak, RSS stable | ⬜ |

## 2. Hardware adaptation & model gateway

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| Hardware probe | U: tier classification across RAM/VRAM/GPU matrix | correct tier for every floor/ceiling case | ✅ |
| Budget-aware selection | U: every tier floor fits its model under §5.2 math | no dense model over-commits its tier floor; MoE may page | ✅ |
| Runtime RAM guard | U: refuse load when `need + margin > available`; I: real low-RAM | never loads a model that would swap; falls back to mock | ✅ U; 🟡 real low-RAM observed manually |
| Pull preflight | U: refuse pull that breaches disk margin; CLI never starts download | leaves **≥5 GB** free; oversized pull → exit 1, no `/api/pull` call | ✅ |
| Fingerprint + drift | U: digest capture; drift refuses byte-replay without `--allow-drift` | mismatch flagged; replay refused unless override | ✅ |
| Real LLM round-trip | I (`LIGHTHOUSE_REAL_BACKEND=1`): one real Ollama completion | non-mock text; tokens > 0; deterministic at temp 0 (± kernel) | 🟡 verified manually, not in CI |

## 3. RAG / retrieval

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| Chunker | U: boundary, overlap, code-block preservation, metadata propagation | 100-token overlap present; code blocks intact | ✅ |
| Hybrid search (dense+BM25+RRF) | I: ingest 10 papers, known queries | **recall@5 + MRR** (precision@5 ceiling is 0.20 on this golden set) | ✅ **live-measured 2026-05-29** (real `bge-m3`): recall@5 **1.000**, MRR **1.000** — perfect ranking. precision@5 0.20 = its mathematical ceiling (1 relevant doc/query), not a miss; the old ≥0.40 bar was mis-calibrated and has been corrected to gate on recall@5/MRR |
| Contextual retrieval | I: recall vs no-context baseline | **≥10% recall lift** (Anthropic pattern) | ⬜ |
| Reranker | I: MRR vs hybrid baseline | **≥5% MRR lift** over hybrid | ⬜ (stub reranker only) |
| Faithfulness (ragas) | E: 20-pair golden set | **faithfulness ≥ 0.7** | ⬜ |
| Retrieval latency | Perf: 1000-chunk corpus | ingest <60s on T2; query **p95 <300ms** | ⬜ |
| Real embeddings (bge-m3) | I: 1024-dim, similar>dissimilar cosine | dim correct; semantic ordering holds | ✅ verified |

## 4. Sandbox & ingestion security

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| Scanner verdicts | U: EICAR, zip-bomb, JS-PDF, script-HTML, SVG-script | each correctly reject/quarantine | ✅ |
| Redteam suite | Sec (weekly CI): all known-hostile artifacts | **100% blocked**, 0 escapes | ✅ mini suite; ⬜ ClamAV/YARA real corpus |
| Injection gate | U+Sec: known injection prompts; ingest screening | injected chunks **never** enter corpus; FP rate measured | ✅ U + wired at ingest; 🟡 FP rate on real text ⬜ |
| Quarantine quota/eviction | I: fill to quota, evict, WORM preserved | eviction triggers; WORM-tagged files survive | 🟡 manifest ✅; quota/eviction ⬜ |
| Real isolation | I: bubblewrap/sandbox-exec download of hostile file | escape attempts contained at OS level | ⬜ (pure-Python scanners only) |

## 5. Honesty: discipline, calibration, audit

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| Claim extraction + citation gate | U: coverage, two-source rule, WEP downgrade | coverage floor enforced; unsourced → lower band | ✅ |
| Calibration loop | U+E: research emits Positions; resolve → Brier | every run records positions; Brier computed on resolve | ✅ |
| Brier / reliability | I: scored over a resolved golden set | reliability diagram tracks diagonal; calibration error reported | 🟡 plumbing ✅; real track-record ⬜ |
| HMAC audit chain | U+Sec: append/verify; tamper any row → chain breaks | tamper detected at exact seq; wrong key fails all | ✅ |
| Provenance / replay | U+E: PROV-O round-trip; `replay` reconstructs trace + drift | trace order exact; drift flagged; refuse byte-replay on drift | ✅ U/E; 🟡 PROV-O sidecar per run ⬜ |

## 6. Governor & cost control

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| Token buckets | U+P+Concurrency: hierarchical debit; 10-thread race | sum never negative; math exact under concurrency | ✅ |
| Degradation tiers | U: thresholds 50/70/85/95/100% | correct tier at each boundary | ✅ |
| Loop detection | U: per-job/per-node caps, recursion, repeat; gateway raises | trips at cap; `LoopTripped` from gateway on runaway | ✅ U + gateway-wired |
| Egress proxy | U: allowlist + privacy tiers + log | PRIVATE blocked; non-allowlisted blocked; all conns logged | 🟡 built+U; ⬜ not wired into fetch path |
| Kill switch | I: `kill` drains then stops; Telegram-confirm | graceful drain, no cross-store corruption | 🟡 API kill ✅; Telegram-confirm ⬜ |

## 7. Surfaces (web + TUI)

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| API endpoints | U: every `/api/*` returns expected shape | 200 + schema for all ~25 endpoints | ✅ |
| SSE event bus | U: publish/subscribe, drop on full queue | events delivered; no unbounded growth | ✅ |
| Webapp JS integrity | U: each file compiles; combined-scope no redeclaration; symbol contract | Babel clean; no global collision; consumed symbols exported | ✅ |
| Webapp render | E (Playwright): 7 pages render, no console errors, a11y audit | 0 console errors; axe a11y pass; keyboard reachable | ⬜ **no browser QA yet** |
| TUI screens | U (Textual pilot): boot, 7-page nav, per-screen data, modals, offline | screens render seeded data; offline degrades, no crash | ✅ (34 tests) |
| Responsive/theme | E: light/dark toggle, narrow viewport | no layout break; theme persists | ⬜ |

## 8. Research modes (end-to-end)

| Feature | Tests required | Standard | Status |
|---|---|---|---|
| QUC | E offline + I real | cited, grounded answer; positions recorded | ✅ offline+real verified |
| Deep-Dive | E offline + I real | multi-section, sourced, terminates on progress plateau | ✅ offline+real verified |
| Monitor | I: live RSS → classify → HTML | dedupe works; alerts vs digest split; report written | ✅ |
| Debate / Digest | U + I | judge summary; scheduled briefing dispatched | 🟡 stubs; depth ⬜ |
| Specialty sources | I (respx + live): arXiv, OpenAlex, +PubMed/EDGAR | parse correctly; rate-limited; graded | 🟡 arXiv/OpenAlex ✅; others ⬜ |

## 9. Engineering quality gates (whole repo)

| Gate | How | Standard | Status |
|---|---|---|---|
| Test suite | `uv run pytest` | **100% pass**, 0 unexpected skips | ✅ 814 pass, 3 opt-in skips |
| Coverage | `pytest --cov` | **≥80%** overall; ≥90% on persistence/governor/verification | ✅ **82% overall (gate met)**; persistence 99%, governor 82–100%, verification high (adversarial/positions/hypotheses 98–100%, contradiction 92%, discipline 82%). Low spots are offline-uncoverable: `entailment.py` 34% (lazy-model path), `resolver.py` 78% (live-research path) — both need a real backend to exercise |
| Lint | `ruff check` | 0 errors | ✅ ruff clean |
| Types | `mypy src` | 0 errors on public modules | ✅ **0 errors across 259 files; now a blocking CI gate** |
| CI | GitHub Actions | suite + lint + types green on every push (macOS + Linux) | ✅ `ci.yml`: ruff + **mypy (blocking)** + pytest + build on {ubuntu, macOS} × py{3.11, 3.12} |
| Cross-platform | run suite on Linux | green; systemd unit + /var paths work | ⬜ |
| Security review | manual + Sec tests | egress/injection/sandbox boundary reviewed; no high findings | ⬜ |
| Packaging | build + install | `pip install` works; entry points run; launchd/systemd install verified | ✅ clean-room install verified (wheel bundles static dashboard + 37 skills + catalog; 3 console scripts run; offline eval works); ⬜ launchd/systemd + signing |

## Top of the queue (highest-leverage gaps)

The **Deployment readiness** section at the top is now the authoritative queue. The single
highest-leverage move remains **Phase 1 — Measure**: run the golden-set + DeepResearch-Bench
evals under real backends to put numbers on the core "better-than-frontier" claim (real-LLM
framing/synthesis quality, retrieval precision@5, faithfulness), and stand up CI
(pytest + ruff + mypy, macOS + Linux) to gate everything after it. Then Phase 2 validates the
36 skills against live APIs, Phase 3 hardens surfaces/ops, Phase 4 packages and ships.

(Many items previously listed here are now done offline: reranker default-on, specialty adapters
SEC EDGAR/CourtListener/+30 more, ProtectAI deBERTa injection layer, sandbox YARA/pikepdf,
contradiction artifact, calibration auto-resolver, deep-tier VOI+synthesis. They move to "needs
live-data validation," not "not started.")
