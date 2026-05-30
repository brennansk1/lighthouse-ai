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
