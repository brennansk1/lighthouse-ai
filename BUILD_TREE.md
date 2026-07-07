# BUILD_TREE — Lighthouse UPGRADE/OPTIMIZE/EXTEND (2026-07-05)

## Goal Statement (from GOAL.md — read first)

Lighthouse is a local-first, air-gapped deep-research instrument for
confidential corpora, aiming to be **on par with or better than Claude and
Gemini deep research while running entirely on local LLMs mapped to the
hardware tier**. Its structural wedge: unbounded depth (Thorough/Deep tiers vs.
cloud's ~10–20 min time-box), enforced citation honesty (entailment-gated,
zero fabricated citations), provable privacy (falsifiable egress guard), and
tamper-evident auditability. Quality ranking: trustworthiness > privacy >
auditability > honesty-about-status > hardware adaptivity. Full statement:
GOAL.md.

## Scope note

The product is feature-complete for v1.0 and offline-green (baseline
3160/105/0, ruff+mypy clean — RECON.md). Existing verified subsystems appear
below as collapsed branches at their real status; only this effort's in-scope
work is decomposed to leaves, per the blast-radius rule. Passes run in order:
Stage 1 UPGRADE → Stage 2 OPTIMIZE → Stage 3 EXTEND.

## Tree

```
T  Lighthouse (trunk: cli.py · supervisor.py · dispatcher.py · gateway.py ·
│             pipeline.py · schema.py — confirmed, no trunk-level change planned)
│
├── B1 BACKEND — EXISTING SPINE (as-is, out of change scope except noted)
│   ├── B1.a ✔️ rag/ · modes/ · sources/ (37 skills) · framing/ · verification/
│   │        governor/ · sandbox/ · eval/ · skills/ · compounding/ ·
│   │        subconscious/ · notify/ · targets/ · output/  — offline-green
│   ├── B1.b ✔️ backends/ollama.py — Ollama chat/stream/embed/pull client
│   │        (change target of B5.1; baseline behavior characterized by
│   │        tests/test_backends_ollama.py)
│   └── B1.c ✔️ dispatcher.py job lifecycle (queued→running→review/failed;
│            reaper; deep-checkpoint files) — change target of B5.2
│
├── B2 FRONTEND — EXISTING SPINE (as-is, out of change scope except noted)
│   ├── B2.a ✔️🖼️ web/static/ — React (CDN + babel-standalone), 13 JSX modules,
│   │        9 tabs, tokens.css; served by web/routes.py; SSE + /api/jobs
│   │        (change target of B6.1/B6.2: app-lib.jsx JobTrace/TraceStep)
│   └── B2.b ✔️ tui/ — Textual dashboard, webapp parity
│
├── B3 STAGE 1: UPGRADE (behavior held constant)
│   ├── B3.1 ✔️ Baseline repair — stale pull-tag test → green (509c99c)
│   ├── B3.2 ⬜ PEP 639 license metadata — pyproject `license = "MIT"` +
│   │        `license-files`, drop deprecated classifier; uv build warning gone
│   ├── B3.3 ⬜ Lockfile refresh within pinned ranges (`uv lock --upgrade`);
│   │        full suite re-run green; pyrate-limiter <4 pin respected
│   └── B3.4 ⬜ Doc-drift micro-audit — README/CAPABILITIES counts vs. measured
│            baseline (3160/105); note stale design-doc §8.3 LangGraph claim
│            where the checklist already carries the accurate framing
│
├── B4 STAGE 2: OPTIMIZE (metric-gated only)
│   ├── B4.1 ✔️ CLI startup — measured 0.131 s warm → CLOSED, no work warranted
│   └── B4.2 ⬜ Retrieval-path micro-benchmark (chunk → BM25 → hybrid RRF,
│            synthetic corpus, stub embedder) — MEASURE ONLY; spawns an
│            optimization leaf only if something egregious surfaces
│
├── B5 STAGE 3: EXTEND — BACKEND
│   ├── B5.1 Generation watchdog (incident 2026-06-10; honesty invariant)
│   │   ├── B5.1.1 ⬜ `BackendStalledError` + per-chunk stall deadline in
│   │   │        `_chat_stream` (reset on each iter_lines tick)
│   │   ├── B5.1.2 ⬜ Internal streaming for non-streaming `chat()` calls —
│   │   │        aggregate tokens; external signature/return unchanged;
│   │   │        characterization tests updated for wire-shape change
│   │   ├── B5.1.3 ⬜ `embed()` read-timeout right-sizing (dedicated, much
│   │   │        shorter than 600 s; constructor kwarg + module constant)
│   │   ├── B5.1.4 ⬜ Surfacing: dispatcher catches stall → audit
│   │   │        `backend.stalled` + `job.failed` reason + progress event
│   │   │        kind="stalled" through ProgressEmitter/SSE
│   │   └── B5.1.5 ⬜ Tests: stalled-backend simulation (mock stream that
│   │            hangs between chunks; tiny thresholds; no real sockets/sleeps
│   │            beyond ms-scale; no daemons)
│   └── B5.2 Deep-tier resume wiring (checklist 🔌; competitive-wedge: depth)
│       ├── B5.2.1 ⬜ Explicit resume lifecycle: `_adapt_investigate_deep`
│       │        audits `job.resumed` {nodes_done, pending} + progress event
│       │        kind="resumed"; jobs.metadata_json gains `resumed` marker
│       ├── B5.2.2 ⬜ Reaper awareness: `reap_stuck_jobs` notes existing deep
│       │        checkpoint in its audit trail when requeueing
│       └── B5.2.3 ⬜ E2E proof: crash → reap → requeue → resume, offline
│                simulated (drives reap_stuck_jobs → dispatch_once → run_job
│                on a depth=deep row with a pre-existing checkpoint)
│
├── B6 STAGE 3: EXTEND — FRONTEND
│   ├── B6.1 ⬜🖼️ Dashboard: JobTrace/TraceStep render kind="stalled" event
│   │        distinctly ("backend stalled" state, not eternally-running) —
│   │        vision-checked, artifact under visuals/
│   ├── B6.2 ⬜🖼️ Dashboard: resumed-from-checkpoint marker in job trace —
│   │        vision-checked, artifact under visuals/
│   └── B6.3 ⬜ TUI: confirm stalled/resumed events pass through job status
│            views without breakage (verify-only; change only if broken)
│
├── B7 🔒 NO_TOUCH (protected surfaces — see RECON.md §4)
│   egress guard/AIRGAP semantics · HMAC audit-chain format · grounding-gate
│   thresholds · public CLI surface · AGPL stays opt-in · legacy mode aliases ·
│   pyrate-limiter <4 pin · offline/no-daemon test posture
│
└── B8 ROADMAP — Frontier-parity program (NOT this effort's committed scope;
    │            weighed in FUTURE_FEATURES.md §11; full leaf decomposition
    │            deferred to Phase 2 when each epic is scheduled)
    ├── R-A ⬜ [P0] Frontier-parity measurement harness — make LIVE_TEST_PLAN
    │        §2.7 a repeatable blind grader; de-risks R-B/R-C/R-D. Low code
    ├── R-B ⬜🖼️ [P1] Multimodal document understanding — hardware-gated local
    │        VLM; figures/tables/scans become citable evidence. Staged:
    │        (1) table/scanned-text OCR → (2) chart/figure VLM (Thorough/Deep)
    ├── R-C ⬜ [P1] Local-model quality amplification — best-of-N judged by
    │        existing gates + verifier-guided regeneration; depth+metric-gated,
    │        sequenced behind R-A so the lift is measured
    └── R-D ⬜🖼️ [P2] Report-grounded Ask follow-up — Ask on a finished
             artifact's corpus+citations (refines FUTURE_FEATURES §6)
```

Roadmap priority ≠ Manifest status: R-* are ⬜ NOT_STARTED backlog, ordered
P0→P2. The immediate committed work remains B5 (watchdog, in flight) and B6.

Frontend↔backend seam for this effort: the `job_events` row / SSE `job.step`
payload (new `kind` values "stalled"/"resumed") and jobs.metadata_json —
contract locked in BUILD_MANIFEST.md before implementation.
