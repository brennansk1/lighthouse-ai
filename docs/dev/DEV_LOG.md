# Lighthouse — Autonomous Dev Log

> **Purpose.** Continuity notes for the self-managed senior-developer workflow. Read this first when
> resuming (e.g. after a token-limit reset) to know exactly where things stand and what's next.
> Update it as work lands. The git history is the source of truth; this is the map.

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
**P0 — in flight (explicit asks):**
1. **Global pause** (webapp button + CLI) so the user can reclaim hardware. The CLI `pause` currently
   only writes `supervisor_state.status` which NOTHING reads → loops don't actually pause. Fix:
   single source of truth `is_paused(paths)` read by all 5 supervisor loops + a `/api/pause`,
   `/api/resume`, `/api/control` endpoint + a webapp toggle. *(building now)*
2. **24/7 scheduling**: the 5 daemon loops (dispatch 5s, monitor 60s, subconscious 60s, resolver 1h,
   backup 1h) are implemented in `supervisor.serve()`; ensure each honors the global pause and a
   digest cadence exists. Verify ticks fire (tests).
3. **Wire `ram_aware_concurrency`** at the gateway gate site (`pipeline.py`) — hardware follow-up
   (safety-additive: only clamps down).

**P1 — features that complete the product:**
- Watch v2 (web_monitor skill: scrapability pre-flight + trigger criteria + content diff + UI) — spec
  in `FUTURE_FEATURES.md` §1. Task #38.
- Intent recipes (preset mode+depth+sources "recipes" in the wizard) — public UX win.
- API-key onboarding wizard (Settings; over the existing keyring/secrets) — public UX.
- Surface steerability (seed/temp/top-p + locked mode) in the Settings UI.

**P2 — deployment-completing (offline parts):**
- `/api/sources/health` + live Health "Sources" card; fix tui budget display wiring.
- Notifications on `budget_trip` / `monitor_alert`.
- MkDocs docs site + tutorials.
- Local Graph-RAG (scoped: entity/relation extraction over the corpus) — larger.
- One-click desktop app (Tauri bundling local Ollama/Qdrant) — needs build tooling; scaffold only.

**P3 — live-gated (await Mac mini):** real-LLM quality eval (precision@5/faithfulness), live source
API validation across the 36 skills, optional-ML-model measurement, Playwright browser QA, 24h soak,
cross-platform, packaging/signing, security review. Tracked in `docs/PRODUCTION_CHECKLIST.md`.

## How to resume after a token-limit reset
1. `git log --oneline -15` to see the latest increments.
2. Read this file's "Active backlog"; pick the top unfinished P0/P1 item.
3. `uv run pytest -q` + `uv run mypy src/lighthouse_ai` to confirm a green baseline.
4. Work the item in a feature-then-test loop, keep public signatures stable, commit + push when green.
5. Update "Current state" + check off the backlog item here.
