# Lighthouse — Autonomous Dev Log

> **Purpose.** Continuity notes for the self-managed senior-developer workflow. Read this first when
> resuming (e.g. after a token-limit reset) to know exactly where things stand and what's next.
> Update it as work lands. The git history is the source of truth; this is the map.

## Guiding principle — design for the user
Every feature is designed and built from the **end-user's** mental model and need first, not the
implementation's. Concretely: plain-language labels (no internal jargon — "we can read this page", not
"extract_tier=static"), discoverable in the UI, sane defaults, clear empty/error states, and a real
answer to "what does this let me *do*?". Target users: regulated-industry researchers (trust,
provenance, reproducibility) AND the general public (one-click, no terminal). When in doubt, optimize
for the user's clarity and control over engineering elegance.

## Operating mode
- I (the assistant) act as the senior developer with full oversight; the user is the manager and does
  not need to hand me tasks. I set my own tasks, work the backlog to a finished project, and commit +
  push to `main` in increments so nothing is lost.
- **Invariants every commit must hold:** full suite green (`uv run pytest -q`), `mypy` 0 across
  `src/lighthouse_ai`, `ruff` clean. New features are offline-deterministic with lazy/graceful
  fallbacks; live-only paths gated by `LIGHTHOUSE_REAL_BACKEND=1`.
- **Live-hardware validation** (real Ollama, heavy models, browser, large uploads, soak, packaging) is
  parked until the user provides their Mac mini. The gated integration harness (`tests/test_real_*`)
  is already written so that validation is turnkey then.

## Live validation results (2026-05-29, on the user's Mac mini)
Running the gated real-backend suite (`LIGHTHOUSE_REAL_BACKEND=1`, macOS arm64, 25.8 GB RAM, Ollama with
`bge-m3` + `llama3.1:8b`) surfaced and fixed three real issues — the value of live testing over mocks:

- **Real LLM path ✓.** `llama3.1:8b` returned the exact requested string in 3.7 s through the
  gateway→Ollama path; RAM 11.5→7.2 GB (8B resident), no swap. Real (non-mock) completion confirmed.
- **Real retrieval ✓.** `bge-m3` embeddings on the golden set: **recall@5 = 1.000, MRR = 1.000** —
  perfect ranking (the one relevant doc per query retrieved at rank 1 every time).
- **FINDING #1 — precision@5 threshold was mis-calibrated.** The golden set labels **exactly one
  relevant doc per query** (6 cases / 8 docs, disjoint topics), so precision@5's ceiling is `1/5 = 0.20`
  by construction — the old `≥0.40`/`≥0.55` bars were mathematically impossible, not retrieval failures.
  *Fix:* gate on recall@5 + MRR (the metrics meaningful at this density), keep precision@5 informational
  against its ceiling, fix the `lighthouse eval` CLI to headline MRR/recall. Did **not** inflate
  relevance labels to fake a pass — the corpus has one right answer per query.
- **FINDING #2 — recommender quality bugs (recall@5 0.40 → 1.00).** The gated skill-recommender eval
  exposed real source-picker defects: (a) `retraction_watch`, a *composing utility*, was recommended as
  a top **primary** source in nearly every ranking; (b) the high-base academic cluster
  (openalex/crossref/pubmed) buried explicitly-named sources — "Find **Reuters** articles" ranked reuters
  #25, "Recent **arXiv** preprints" ranked arxiv #22. *Fix (`skills/recommender.py`):* exclude
  `composing`-tagged utilities from recommendations; add a decisive **explicit-mention** boost (de-spaced
  id-in-question + distinctive name tokens, len≥4 guard so "who" can't false-fire) applied post-blend;
  recognize "search the web" intent to surface `general_web`. Every named source now ranks #1; recall@5
  on the 15-case eval went **0.40 → 1.000**. Five offline regression tests added.

- **FINDING #3 — per-mode E2E (all 7 modes) against the real LLM.** Investigate/Survey/Reconstruct/
  Decide/Adjudicate/Ask/Watch each ran end-to-end through `dispatch_once` with the real gateway
  (auto-fit to `llama3.1:8b`, RAM held ~7.2 GB free, no swap) and produced their artifact
  (report/table/timeline/matrix/verdict/transcript/digest) passing the discipline gate (valid provenance,
  numeric citation_coverage, no fabrication). Watch initially failed with `backend='none'` which exposed
  a **real dead-wire**: `_adapt_watch` never passed `topic_interests` to `run_monitor`, so the
  interest-relative LLM salience (gap #15) was unreachable via the dispatch path. *Fix
  (`dispatcher.py`):* thread `topic_interests`/`interests` from the job meta into `run_monitor` (it then
  auto-selects the `aux_context` gateway scorer). With interests the watch E2E now exercises a real LLM
  salience round-trip (15 s); without them it stays honestly deterministic. Two offline regression tests
  pin both directions; the E2E `_assert_artifact` now accepts `backend='none'` as a valid deterministic
  state for watch.

- **Phase 2 — live source APIs (all 37 skills) ✓.** `test_real_skills_fetch.py` ran one bounded
  (`max_results=2`, politeness) live fetch per skill: **37/37 pass**, no endpoint-shape drift, no crashes.
  Keyless sources returned real documents (arxiv, AP, BBC, BLS, census, clinicaltrials, crossref,
  federal_register, github, guardian[public test key], internet_archive, news_orchestrator[multi-outlet],
  npr, oecd, openalex, pubmed, sec_edgar, semantic_scholar, wikidata, wikipedia, world_bank, …). Key-gated
  sources with no key configured degraded **gracefully** with an actionable `lighthouse trust add <domain>`
  note (congress 403, fred 400, govinfo 401). Minor polish observation (logged to FUTURE_FEATURES, not a
  bug): key-required skills fire the request with an empty key and let the server reject it rather than a
  pre-flight "key required" short-circuit — already graceful, just slightly wasteful.

- **FINDING #4 — gated chat-smoke picked an embedding model.** `test_real_ollama_chat_returns_tokens`
  selected the alphabetically-first installed model, which on this box is `bge-m3` (embedding-only) →
  Ollama 400 `"does not support chat"`. *Fix:* filter embedding models (bge-*/`*embed*`/all-minilm/
  arctic-embed) and prefer a small chat model. Bonus: the **Qdrant real-backend suite passed** (HNSW +
  scalar quantization + payload indexes + upsert/search/delete round-trips) — persistent vector store
  works on this machine, not just in-memory.

- **Phase 3 (partial) — sandbox security redteam with real scanners.** Installed `--extra
  sandbox-hardening` (yara-python + pikepdf, modest/reversible — no torch) and ran the redteam corpus.
  All 29 tests pass: an OpenAction-JavaScript PDF is **quarantined**, a benign PDF is **clean (no false
  positive)**, malformed PDFs quarantined, EICAR still detected, no FPs on benign HTML/PDF. Installing the
  real libs surfaced **three latent issues** (fixed): (a) the pikepdf test helpers used the pikepdf-9
  `pages.append(Dictionary)` form which pikepdf-10 rejects — switched to the stable `add_blank_page`, so
  the scanner is now actually exercised; (b) `YaraScanner._get_rules()` ignored `_yara_available()` (it
  relied on import failure), inconsistent with `supports()` — now honors it so disabling yara is respected
  even when importable; (c) a latent mypy error in `PikePdfScanner` (`pikepdf.Object` dynamic attr seen as
  non-callable) that only appears once pikepdf's real types are installed — fixed with an `Any` annotation.
  **Note:** the hardening libs remain installed, so the secured store now runs the real yara/pikepdf
  scanners by default (more secure). With them installed the full suite runs 6 more tests (2873 pass).

- **FINDING — politeness layer broke against current optional-dep versions.** Installing `--extra
  politeness` (protego/courlan/pyrate-limiter) surfaced three real issues (fixed): (a) the `pyrate-limiter
  >=3.6` pin silently allowed the **4.x rewrite** which removed `BucketFullException` and changed the
  Rate/Limiter API `net_politeness.py` targets → pinned `>=3.6,<4` (4.x migration is a deliberate,
  separately-tested task; rate-limiting is politeness-sensitive); (b) the pyrate-backed rate budget used
  whole-second windows, so a 50 req/s, burst-1 config was throttled to **1 req/s — 50× slower than
  configured and inconsistent with the pure-Python fallback** → switched to **millisecond** windows so
  both backends agree and high rates work; (c) `canonicalize()` stopped stripping URL `#fragments`
  (courlan version behavior) → strip the fragment explicitly so dedup/rate-keying never depends on
  courlan's version. 68/68 politeness+scrapability tests pass with the real libs.

- **Night sprint — full optional-ML stack installed + validated.** Installed every non-browser extra
  (politeness, sandbox-hardening, pdf-fast, extraction, faithfulness, injection-ml, reranker, youtube) and
  ran the real-library tests. **Model-quality results (all on real hardware, RAM ≥ 9.9 GB free, no swap):**
  faithfulness gate **mean = 1.000** (≥0.80 bar, 20-pair set); FlagReranker retrieval **recall@5 = MRR =
  1.000**; injection-ml deBERTa 24/24 integration. Installing the real libs surfaced **6 more real bugs**
  (fixed, see commits): pyrate-limiter 4.x break + ms-window rate divergence + courlan fragment strip;
  youtube-transcript-api 1.x `get_transcript`→`fetch`; docling 2.x `DocumentStream` (both call sites);
  pipeline `offline=True` not hermetic for the reranker; `discipline.check` marking entailment_checked on
  empty evidence. docling/youtube fixes validated live (real PDF convert; real 2089-char transcript).

All fixes are offline-deterministic with regression tests; full suite **2888 pass / 83 skip**, mypy 0,
ruff clean. Live validation: Phase 1 (core quality) ✓, per-mode E2E 7/7 ✓, Phase 2 source APIs 37/37 ✓,
Ollama + RAG-real + Qdrant-real gated ✓, sandbox redteam (real yara+pikepdf) 29/29 ✓, politeness layer
(real protego/courlan/pyrate) 68/68 ✓, optional-ML stack (faithfulness/reranker/injection/extraction/
youtube) ✓.
- **Browser QA ✓** — `scripts/browser_smoke.py` (bounded, in-thread uvicorn + headless chromium): all 7
  dashboard pages render with zero console/page errors. Fixed a fragile js-render absence test.
- **Packaging ✓ (clean-room)** — `uv build` wheel bundles all package data (static dashboard, catalog,
  37 skills); installed into a fresh py3.11 venv with base deps only → 3 console scripts run, offline eval
  works, bundled data accessible. A user can `pip install` and run it.

**Live findings total this session: 16 real bugs fixed** (recommender ×3, precision bar, watch dead-wire,
chat-smoke, sandbox ×3, politeness ×3, youtube-1.x, docling-2.x, offline-reranker, entailment-empty,
js-render-test). Remaining toward ship: 24 h soak, cross-platform/systemd, code-signing, security review.
Remaining live phases (heavier setup): faithfulness gate (needs the `faithfulness` extra — torch/
sentence-transformers), Playwright browser QA (Phase 3), 24 h soak + packaging (Phase 4).

## Milestone (this session) — offline product feature-complete
Suite **2850 pass / 103 skip**, mypy 0 (269 modules), ruff clean, coverage ~82%. Shipped + pushed:
the whole skills/recommender/source-picker stack; mode↔skill integration + contradiction handling;
frontier-gap core; acquisition stack; **Sandbox** workspace; **Watch-a-website** (v2, with alerts);
intent **recipes**; **skill-scaffold generator**; **steerability/reproducibility**; **Settings** API-key
onboarding; **global Pause**; **hardware** OOM/utilization guardrails; **in-app Info-tab guide**; the
**Graph-RAG primitive** (`rag/graph.py`); top-level docs synced; **4-wave audit (~32 real bugs fixed)**.

### Precise remaining work (deliberate, next sessions)
- ✅ **Graph-RAG surfacing** — DONE: `/api/graph/draft/{id}` + the Library "How the evidence connects"
  panel. A further enhancement (out of scope for now) is wiring `CorpusGraph.query()` into the GRAPH
  retrieval ROUTE so graph signal boosts retrieval — that DOES touch the audited retrieval path, so do
  it deliberately with fresh tests, not casually.
- **One-click desktop app (Tauri)** — bundles local Ollama/Qdrant; needs Node/Tauri build tooling →
  scaffold + doc here, real build on a dev box.
- **P3 live validation** (await Mac mini): real-LLM quality (precision@5/faithfulness), live source-API
  validation across the 37 skills, optional-ML-model measurement, Playwright browser QA, 24h soak,
  cross-platform, packaging/signing, security review. Gated harness `tests/test_real_*` makes it turnkey.
  **→ Hand a fresh session `docs/dev/LIVE_TESTING_HANDOFF.md`** — a self-contained cold-start runbook
  (env setup, phased commands, thresholds, where to record results).
- **Deferred small items:** budget-trip notifications (governor buckets lacks config access);
  ram_aware_concurrency wiring to raise default LLM concurrency (OOM-sensitive — validate on real hw).

## Current state (update the date/commit when you touch this)
- Suite: ~2762 passing, ~103 skipped (gated). mypy 0 (267 files). ruff clean. CI: ruff+mypy(blocking)+
  pytest+build on {ubuntu,macOS}×py{3.11,3.12}. Coverage ~82%.
- Shipped: full skills framework + 36-source library + recommender + source picker; mode↔skill
  integration + contradiction artifact + per-mode handling + auto-Adjudicate; frontier-gap core
  (planner LLM, calibration loop, deep-tier VOI/synthesis/checkpoint); acquisition stack (politeness,
  ML injection, sandbox hardening, extraction chain, egress-on-fetch, PROV-O, quota, backup cron);
  Sandbox feature (store + analysis tools + API + tab); skill-scaffold generator; steerability;
  hardware-optimization (KV OOM headroom + MoE-aware fit + RAM-aware concurrency).
- **Audit complete:** 4 waves, ~32 real bugs fixed (redirect SSRF, audit-chain tamper-evidence, skill
  import-guard escapes incl. os/exec hardening, scanner bypasses, data-loss/durability, dead planner
  path, etc.). Every fix has a regression test.

## Active backlog (priority order)
**DONE this session (P0/P1 all shipped + pushed):** global pause (loops+API+webapp); 24/7 loops honor
pause; hardware optimization (KV OOM headroom, MoE-aware fit, ram_aware_concurrency helper — wiring it
to raise default concurrency is deferred pending real-hw validation, OOM-sensitive); Watch v2 (core +
surfacing + plain-language UI); intent recipes; Settings (API-key onboarding + reproducibility/lock);
Health "Sources" card + tui budget fix; skill scaffold generator; steerability; 4-wave audit (~32 bugs).

**P2 — remaining offline-buildable (next up):**
1. **Notifications on events** — fire desktop/Discord/Telegram on a Watch alert (the
   `run_web_monitor_tick(alert_sink=...)` seam is ready) and on a Governor budget trip. *(building now)*
2. **MkDocs docs site + tutorials** — content-heavy; adoption/credibility.
3. **Local Graph-RAG (scoped)** — entity/relation extraction over the corpus + a GRAPH retrieval route;
   larger, multi-file. Keep causal-inference a labeled stretch (don't overclaim). `FUTURE_FEATURES` §5.
4. **One-click desktop app (Tauri)** — bundles local Ollama/Qdrant; needs build tooling → scaffold +
   doc only in this environment, real build on a dev box.

**P3 — live-gated (await Mac mini):** real-LLM quality eval (precision@5/faithfulness), live source API
validation across the 36 skills, optional-ML-model measurement, Playwright browser QA, 24h soak,
cross-platform, packaging/signing, security review. The gated harness `tests/test_real_*` is written so
this is turnkey. Tracked in `docs/PRODUCTION_CHECKLIST.md` → Deployment readiness.

**Status:** the offline-buildable product is feature-complete and audited; what remains is P2 polish +
the named larger features (Graph-RAG, desktop app, docs site) + P3 live validation. Suite ~2812 green.

## How to resume after a token-limit reset
1. `git log --oneline -15` to see the latest increments.
2. Read this file's "Active backlog"; pick the top unfinished P0/P1 item.
3. `uv run pytest -q` + `uv run mypy src/lighthouse_ai` to confirm a green baseline.
4. Work the item in a feature-then-test loop, keep public signatures stable, commit + push when green.
5. Update "Current state" + check off the backlog item here.
