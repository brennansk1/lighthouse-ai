# BUILD_MANIFEST — Lighthouse UPGRADE/OPTIMIZE/EXTEND (2026-07-05)

## Goal Statement (from GOAL.md — read first)

Local-first, air-gapped deep-research instrument for confidential corpora,
aiming to be **on par with or better than Claude/Gemini deep research on local
LLMs mapped to the hardware**. Wedge: unbounded trusted depth, enforced
citation honesty, provable privacy, tamper-evident audit. Quality ranking:
trustworthiness > privacy > auditability > honesty > hardware adaptivity.

## Baseline datum (Phase R)

`pytest -q` → **3160 passed / 105 skipped / 0 failed** · `ruff check src tests`
clean · `mypy src/lighthouse_ai` clean (276 files). Every change must return
the suite to at least this state. Sequencing: UPGRADE → OPTIMIZE → EXTEND.
**Datum raised after B3.3 (e7587e2): 3183 / 82 / 0** — the binding floor from
here on.

## Manifest

| ID | Feature | Contract / Acceptance criteria | Depends on | Status | Evidence / Notes |
|---|---|---|---|---|---|
| B3.1 | Baseline repair: stale pull-tag test | Suite green at datum; test asserts resolver's current intent (qwen3.5:9b @16 GB, qwen3:32b @64 GB) | — | ✔️ | 509c99c; `pytest tests/test_cli_new_commands.py` → 37 passed; full suite 3160/105/0 |
| B3.2 | PEP 639 license metadata | `pyproject.toml`: `license = "MIT"`, `license-files = ["LICENSE"]`, deprecated classifier dropped; `uv build`-time warning gone; suite green | — | ✔️ | commit (see git log "PEP 639"); `uv build` → no license warning, both artifacts built; covered by B3.3 full-suite run |
| B3.3 | Lockfile refresh | `uv lock --upgrade` within existing ranges; pyrate-limiter stays <4 (🔒); full suite + ruff + mypy green after | B3.2 | ✔️ | e7587e2; suite **3183/82/0** (23 former optional-dep skips now pass; total 3265 unchanged); ruff clean; mypy clean; pyrate-limiter 3.9.0 |
| B3.4 | Doc-drift micro-audit | README/CAPABILITIES factual counts not contradicted by measured baseline; PRODUCTION_CHECKLIST rows for shipped nodes updated when B5/B6 land | B5.*, B6.* | ✔️ | PRODUCTION_CHECKLIST: Deep-tier resume 🔌→✅ + generation-watchdog ✅ rows; design-doc §8.3 LangGraph claim annotated (not rewritten); FUTURE_FEATURES §11 reliability para → shipped. README "3140+/~106" not contradicted (current 3189/82) — left as-is |
| B4.1 | OPTIMIZE: CLI startup | Measured; optimize only if egregious | — | ✔️ | 0.131 s warm / 0.48 s cold — **closed, no work warranted** (RECON.md) |
| B4.2 | OPTIMIZE: retrieval micro-benchmark | Synthetic corpus, stub embedder: chunk→BM25→hybrid RRF timed; record numbers in RECON.md; spawn an optimization leaf ONLY if egregious (>1 s for ~200-doc corpus query, or superlinear blowup) | — | ✔️ | Measured 2026-07-05: 200 docs → query p50 0.64 ms / p95 0.65 ms; 1000 docs → p50 2.81 ms (×4.4 for ×5 docs, ~linear); ingest 0.05 s / 0.27 s. **No optimization warranted — closed, no change made.** Stage 2 complete |
| B5.1.1 | `BackendStalled` + stream stall deadline | New `class BackendStalled(OllamaUnavailable)` w/ attrs `model`, `stalled_after_s`, `call` ∈ {"chat","embed"}. `_chat_stream` runs with per-request `read=stall_timeout` (constructor kwarg, default `DEFAULT_STALL_TIMEOUT` = env `LIGHTHOUSE_STALL_TIMEOUT_S` or 300.0); read-timeout during stream → `BackendStalled`. Other HTTP errors unchanged (`OllamaUnavailable`) | — | ✔️ | commit abd9973; httpx built-in per-read timeout IS the watchdog — no new dep, no threads. Verified by B5.1.5 tests + full suite 3188/82/0 |
| B5.1.2 | Internal streaming for all `chat()` | `chat()` posts `stream: True` always and routes via `_chat_stream` (`on_token` now optional); signature + `ChatResponse` semantics byte-identical for callers; total generation time no longer capped at 600 s (stall-gated per chunk instead); respx tests updated to stream fixtures — that wire-shape change is the *intended* behavior change, nothing else | B5.1.1 | ✔️ | abd9973/da1af54; 2 fixtures migrated to JSON-lines; identical `ChatResponse` proven by `test_chat_parses_completion` |
| B5.1.3 | `embed()` timeout right-sizing | Per-request `read=embed_read_timeout` (kwarg, default env `LIGHTHOUSE_EMBED_TIMEOUT_S` or 120.0); read-timeout → `BackendStalled(call="embed")`. Incident's `/api/embed` wedge surfaces in ≤120 s, not 600 s | B5.1.1 | ✔️ | abd9973; `test_embed_stall_raises_backend_stalled` + non-timeout-stays-Unavailable test |
| B5.1.4 | Gateway propagation + dispatcher stall surfacing | (a) `gateway.complete()` catch-all gains a `BackendStalled` re-raise BEFORE the generic degrade-to-mock — a wedged backend must never mock-masquerade; all other failures keep existing fallback. (b) `run_job` except-path special-cases `BackendStalled`: audit `backend.stalled` {job_id, error, model, stalled_after_s, call} + progress event kind="stalled" (in last emitted phase; `ProgressEmitter` gained `last_phase`/`last_pct`) + existing `job.failed` + bus `job.status` failed | B5.1.1 | ✔️ | abd9973; `test_run_job_backend_stall_surfaces_loudly` asserts audit event payload + kind="stalled" job_event |
| B5.1.5 | Stalled-backend tests | Mock transport whose stream hangs → `BackendStalled` raised w/ correct attrs (chat + embed); `chat()` non-streaming callers get identical `ChatResponse` from aggregated stream; dispatcher test: stalled job → status failed + `backend.stalled` audit row + kind="stalled" job_event. All offline, ms-scale timeouts, no sockets/daemons | B5.1.1–4 | ✔️ | da1af54; 4 backend stall tests + dispatcher stall test; full suite **3188/82/0**; ruff+mypy clean |
| B5.2.1 | Explicit resume lifecycle | On checkpoint hit in `_adapt_investigate_deep`: audit `job.resumed` {job_id, nodes_done, pending} + progress kind="resumed" label "Resumed from checkpoint — N done, M pending" + `meta["resumed"]` persisted to jobs.metadata_json | — | ✔️ | 0fa986f; asserted by the E2E test (job.resumed payload, kind="resumed" step, meta.resumed) |
| B5.2.2 | Reaper checkpoint awareness | `reap_stuck_jobs` gains optional `paths` kwarg; when given, audits `job.requeued` per job incl. `checkpoint: bool` (deep checkpoint file exists). Existing callers (supervisor.py) updated; bare call still works | B5.2.1 | ✔️ | 0fa986f; new event `job.requeued` (existing `dispatch.reaped` log untouched); E2E asserts checkpoint=True |
| B5.2.3 | Crash→resume E2E proof | Offline test drives: deep job row `running` + real checkpoint file → `reap_stuck_jobs` → claim → `run_job` → asserts: completes to `review`, checkpoint deleted, `job.resumed` + `job.requeued(checkpoint=True)` audited, kind="resumed" step, meta.resumed present | B5.2.1, B5.2.2 | ✔️ | 0fa986f `test_deep_job_resumes_from_checkpoint_end_to_end`; full suite **3189/82/0**. Multi-hour live proof stays in LIVE_TEST_PLAN |
| B6.1 🖼️ | Dashboard renders "stalled" | `TraceStep` gives kind="stalled" a distinct visual (whole-row alert: pink bg, red left border, role=alert + failure-red chip), so a stalled job reads as *stalled/failed*, never eternally-running | B5.1.4 | ✔️🖼️ | d3559f7; `visuals/B6_stalled_resumed_trace.png` vision-checked (rendered via real app-lib.jsx). SSE payload shape unchanged (new `kind` value only). Vision caught + fixed a palette bug (--coral-2 is navy in the coastal theme → used #c62828) |
| B6.2 🖼️ | Dashboard renders "resumed" | kind="resumed" renders an info marker with nodes-done/pending counts in the trace | B5.2.1 | ✔️🖼️ | d3559f7; same `visuals/B6_stalled_resumed_trace.png` (middle row) vision-checked |
| B6.3 | TUI passthrough check | TUI job/status views don't break on new event kinds (verify-only; change only if broken) | B5.1.4, B5.2.1 | ✔️ | Verified by inspection: tui/screens.py reads `kind` only via `.get('kind','')`, no exhaustive switch → new kinds render generically. No change needed |
| N1 🔒 | Egress guard / AIRGAP semantics | must not change | — | 🔒 | |
| N2 🔒 | HMAC audit-chain format | `append_event` API used as-is; new event *types* OK, format changes NOT | — | 🔒 | backend.stalled / job.resumed are new types, allowed |
| N3 🔒 | Grounding-gate thresholds | must not change | — | 🔒 | |
| N4 🔒 | Public CLI surface | no new/renamed commands this effort | — | 🔒 | |
| N5 🔒 | AGPL opt-in posture · legacy aliases · pyrate-limiter <4 · offline/no-daemon test posture | must not change | — | 🔒 | |

### Roadmap backlog — Frontier-parity program (NOT_STARTED; weighed in FUTURE_FEATURES.md §11; not this effort's committed scope)

| ID | Feature | Contract / Acceptance criteria (roadmap-level; full decomposition when scheduled) | Depends on | Status | Priority / Notes |
|---|---|---|---|---|---|
| R-A | Frontier-parity measurement harness | Repeatable blind grader over LIVE_TEST_PLAN §2.7: rubric (source count, claim accuracy, citation verifiability, contradiction honesty, open-question honesty), a drop-zone for manually-collected frontier outputs, and a tracked report. Acceptance: `LIGHTHOUSE_REAL_BACKEND=1` run produces a scored Lighthouse-vs-frontier report; offline unit tests cover the grader on fixtures | eval/research_benchmark.py, eval/metrics.py (exist) | ✔️ | **P0** — do first; de-risks R-B/R-C/R-D; low new code |
| R-B 🖼️ | Multimodal document understanding | Hardware-gated local VLM path so figures/tables/scanned pages become citable chunks under the grounding gate; staged (1) table/scanned-text extraction → (2) chart/figure VLM reasoning; tier-gated (Thorough/Deep), routed through the admission gate; opt-in extra like `pdf-fast`. Acceptance per stage: a figure/table yields a citable chunk that the entailment gate can verify a claim against | admission gate, sandbox/ingest, grounding gate (NO_TOUCH thresholds) | ✔️ | **P1** — biggest real-document capability lever; largest build; needs its own contract + hardware budgeting |
| R-C | Local-model quality amplification | Best-of-N synthesis ranked by reranker/entailment; verifier-guided regeneration on discipline-gate failure (regenerate span vs. WEP-downgrade); optional cross-model ensemble for load-bearing claims. Depth-gated (Thorough/Deep) + **metric-gated**: must show measured faithfulness/quality lift on the R-A harness or be reverted (OPTIMIZE discipline) | R-A (measurement), reranker/entailment/discipline (exist) | ✔️ | **P1** — attacks the "on par" quality half; sequenced behind R-A so the lift is proven not assumed |
| R-D 🖼️ | Report-grounded Ask follow-up | Ask grounded in a *completed artifact's* corpus + citation set; synchronous turn endpoint with a live gateway in the web process + continuation UI (per FUTURE_FEATURES §6). Acceptance: a follow-up on a staged artifact returns a grounded turn whose citations resolve to that artifact's sources, gated identically to a fresh Ask | ask.py, ask_store.py (exist); web live-gateway plumbing | ✔️ | **P2** — cheap parity win; refines existing §6, not a second chat feature |

Progress (this effort's committed scope): **16 ✔️ / 0 ⬜ / 0 🧩 / 0 🚫 / 5 🔒**
— **ALL committed scope complete and verified.** Stage 1 UPGRADE (B3.1–B3.4),
Stage 2 OPTIMIZE (B4.1–B4.2, both closed by measurement), Stage 3 EXTEND
(B5.1 watchdog, B5.2 deep-resume, B6 dashboard) all ✔️. B1/B2 existing spines
verified by baseline run. Plus **4 ⬜ roadmap backlog** (R-A…R-D) — planned,
not scheduled. Final full suite: **3189 passed / 82 skipped / 0 failed**;
ruff + mypy clean; baseline preserved and raised.

Frontend↔backend seam (locked): `job_events` rows / SSE `job.step` payload
`{phase, kind, label, pct, data}` — this effort adds only new `kind` values
`"stalled"` and `"resumed"`; no field changes. `jobs.metadata_json` gains
optional `resumed: {nodes_done, pending}`.
