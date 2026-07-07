# RECON — Lighthouse UPGRADE/OPTIMIZE/EXTEND (started 2026-07-05)

Goal: see GOAL.md (read that first). Working tree: worktree
`exciting-lamport-002bc3`, branch `claude/exciting-lamport-002bc3`, base a642f44.

## 1. Baseline green state (Phase R datum)

| Check | Command | Result |
|---|---|---|
| Lint | `uv run ruff check src tests` | ✅ All checks passed |
| Types | `uv run mypy src/lighthouse_ai` | ✅ 0 issues, 276 files |
| Tests | `uv run pytest -q` | ✅ 3160 passed, 105 skipped, 0 failed (210 s) — after repairing one stale test (`test_init_pull_tag_scales_with_ram` pinned pre-qwen3.5 tag; fixed in 509c99c). Datum: **3160 / 105 / 0**. |

Constraints from project memory (binding):
- No background/daemon processes in tests; no real LLM calls by default.
- Real-backend tests opt-in via `LIGHTHOUSE_REAL_BACKEND=1` (~83–106 skips expected).
- Dev box: Apple M4 24 GB (T2 tier); admission gate prevents swap.

## 2. Scope (blast radius)

Task is repo-wide (all three passes, no user constraint), but the *change*
scope will be selected from findings, not "everything." In-scope candidate
areas (from incident log, PRODUCTION_CHECKLIST, CAPABILITIES):

- **UPGRADE**: dependency drift (all minor: starlette 1.1→1.3, typer 0.21→0.26,
  fastapi 0.136→0.139, structlog 25→26 …); lockfile refresh; any dead code /
  doc drift found in audit.
- **OPTIMIZE**: only metric-gated targets discovered during work; none
  pre-identified (offline perf was not flagged as a problem; live-run numbers
  pending). Do NOT optimize speculatively.
  - Measured 2026-07-05: CLI startup `lighthouse --help` = **0.131 s warm**
    (0.48 s cold incl. uv). Verdict: no optimization warranted; candidate closed.
  - Remaining candidate: offline retrieval-path micro-benchmark (chunk → BM25 →
    hybrid RRF) — measure first, optimize only if egregious.
- **EXTEND** (goal-justified candidates):
  1. **Generation watchdog** — hung-but-listening backend (wedged Ollama,
     incident 2026-06-10) currently looks like an eternally-running job;
     abort + audited "backend stalled" after N s of no progress. Serves
     honesty invariant directly. (docs/dev/LIVE_RUN_2026-06-10.md)
  2. **Deep-tier resume wiring** — checkpoint is serializable, dispatcher
     wiring missing (🔌 in PRODUCTION_CHECKLIST). Serves the "unbounded
     depth" competitive wedge.
  3. Question Library (golden-set framings) — ⬜ in checklist.
  4. Browser QA (Playwright) harness — scripts exist (browser_*.py); making
     them a repeatable gate is release work.

## 3. Codebase map (as-is; from delegated inventory, 2026-07-05)

- `src/lighthouse_ai/`: 20 subpackages + ~35 root modules, ~275 modules,
  ~49K LOC. Key spines:
  - BACKEND: pipeline.py, dispatcher.py, supervisor.py, gateway.py, cli.py;
    rag/ (14), modes/ (17), sources/ (29), verification/ (15), governor/ (10),
    sandbox/ (6), framing/ (3), backends/ (2, Ollama), eval/ (9), skills/ (7),
    compounding/ (4), subconscious/ (6), notify/ (5), targets/ (5), output/ (2).
  - FRONTEND: web/static/ — 21 assets; React via CDN + babel-standalone
    (in-browser JSX compile), 13 JSX modules, tokens.css; served by FastAPI
    routes.py; 9 tabs. TUI: tui/ — 5 files, Textual, parity with webapp.
- Tests: 160 files, subdirs compounding/ governor/ rag/ subconscious/
  verification/; markers integration/litestream/slow; coverage ~82%.
- scripts/: check.sh, soak.py, supervisor_smoke.py, browser_{smoke,flow,track,
  ux_sweep}.py, eval_legal.py, docker-compose stack.
- deploy/: systemd unit + launchd plist + README.
- No TODO/FIXME in src (only scaffold templates); no NotImplementedError stubs.
  Intentional graceful-degradation stubs: modes/survey.py `_stub_*`,
  modes/decide.py `_stub_score`, pipeline.py hash-stub embedder — these are
  designed fallbacks, not debt.
- Declared-not-built: `general_web.fetch_url_js` (Tier-B JS render), Tier-C
  browsers (spec-only).

## 4. NO_TOUCH set & non-goals

| Surface | Why |
|---|---|
| Egress guard semantics (`LIGHTHOUSE_AIRGAP=1`, audit-egress) | Falsifiable-privacy invariant; any change needs explicit user sign-off |
| HMAC audit-chain format | Tamper-evidence + replay compatibility |
| Grounding/entailment gate thresholds | Zero-fabricated-citations invariant |
| Public CLI command surface | Documented in README/Guide; user-facing contract |
| `pdf-fast` extra stays opt-in (AGPL) | MIT licensing posture |
| Legacy mode-key alias map (Deep-Dive/Monitor/QUC/Debate) | Back-compat |
| pyrate-limiter pin `<4` | Deliberate; 4.x migration is its own separately-tested task |
| Default test posture (no real backends, no daemons) | Dev-box stability (memory: crashed once) |

Non-goals this effort: PyPI publish, code signing, 24h soak execution,
cross-platform Linux validation (live-only release gates — need real
hardware/time, tracked in docs/RELEASE.md, not buildable here); Tier-C
fingerprint browsers; pyrate-limiter 4.x migration.

## 5. Characterization coverage

Coverage ~82% overall; persistence/governor/verification target ≥90%. For any
node modifying under-tested code, a characterization-test leaf precedes it
(none identified yet; revisit per-leaf).
