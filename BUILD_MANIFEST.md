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
| B3.4 | Doc-drift micro-audit | README/CAPABILITIES factual counts not contradicted by measured baseline; PRODUCTION_CHECKLIST rows for shipped nodes updated when B5/B6 land | B5.*, B6.* | ⬜ | design-doc §8.3 LangGraph claim is stale vs. checklist — note, don't rewrite the 250 KB doc |
| B4.1 | OPTIMIZE: CLI startup | Measured; optimize only if egregious | — | ✔️ | 0.131 s warm / 0.48 s cold — **closed, no work warranted** (RECON.md) |
| B4.2 | OPTIMIZE: retrieval micro-benchmark | Synthetic corpus, stub embedder: chunk→BM25→hybrid RRF timed; record numbers in RECON.md; spawn an optimization leaf ONLY if egregious (>1 s for ~200-doc corpus query, or superlinear blowup) | — | ✔️ | Measured 2026-07-05: 200 docs → query p50 0.64 ms / p95 0.65 ms; 1000 docs → p50 2.81 ms (×4.4 for ×5 docs, ~linear); ingest 0.05 s / 0.27 s. **No optimization warranted — closed, no change made.** Stage 2 complete |
| B5.1.1 | `BackendStalled` + stream stall deadline | New `class BackendStalled(OllamaUnavailable)` w/ attrs `model`, `stalled_after_s`, `call` ∈ {"chat","embed"}. `_chat_stream` runs with per-request `read=stall_timeout` (constructor kwarg, default `DEFAULT_STALL_TIMEOUT` = env `LIGHTHOUSE_STALL_TIMEOUT_S` or 300.0); read-timeout during stream → `BackendStalled`. Other HTTP errors unchanged (`OllamaUnavailable`) | — | ⬜ | Reuse decision: httpx built-in per-read timeout IS the watchdog — no new dep, no threads. Subclass keeps existing handlers working |
| B5.1.2 | Internal streaming for all `chat()` | `chat()` posts `stream: True` always and routes via `_chat_stream` (`on_token` now optional); signature + `ChatResponse` semantics byte-identical for callers; total generation time no longer capped at 600 s (stall-gated per chunk instead); respx tests updated to stream fixtures — that wire-shape change is the *intended* behavior change, nothing else | B5.1.1 | ⬜ | Removes silent 600 s total-cap on legit long syntheses (goal: depth wedge) |
| B5.1.3 | `embed()` timeout right-sizing | Per-request `read=embed_read_timeout` (kwarg, default env `LIGHTHOUSE_EMBED_TIMEOUT_S` or 120.0); read-timeout → `BackendStalled(call="embed")`. Incident's `/api/embed` wedge surfaces in ≤120 s, not 600 s | B5.1.1 | ⬜ | embeds complete in seconds normally; 120 s is generous |
| B5.1.4 | Gateway propagation + dispatcher stall surfacing | (a) `gateway.complete()` catch-all at gateway.py:1050 gains a `BackendStalled` re-raise BEFORE the generic degrade-to-mock — a wedged backend must never mock-masquerade; all other failures keep existing fallback. (b) `run_job` except-path special-cases `BackendStalled`: audit `backend.stalled` {job_id, error, model, stalled_after_s, call} + progress event kind="stalled" (in last emitted phase; `ProgressEmitter` gains best-effort `last_phase`/`last_pct`) + existing `job.failed` + bus `job.status` failed. Mirrors `governor.tripped` precedent | B5.1.1 | ⬜ | Job fails LOUDLY with audited cause — the incident's ask. Offline suite unaffected (mock path never reaches a real chat call) |
| B5.1.5 | Stalled-backend tests | Mock transport whose stream hangs → `BackendStalled` raised w/ correct attrs (chat + embed); `chat()` non-streaming callers get identical `ChatResponse` from aggregated stream; dispatcher test: stalled job → status failed + `backend.stalled` audit row + kind="stalled" job_event. All offline, ms-scale timeouts, no sockets/daemons | B5.1.1–4 | ⬜ | New test surface (none exists for stall today) |
| B5.2.1 | Explicit resume lifecycle | On checkpoint hit in `_adapt_investigate_deep` (dispatcher.py:731-736): audit `job.resumed` {job_id, nodes_done, pending} + progress kind="resumed" label "Resumed from checkpoint — N done, M pending" + `meta["resumed"]` persisted to jobs.metadata_json via existing run_job meta flow | — | ⬜ | Resume stops being an invisible accident |
| B5.2.2 | Reaper checkpoint awareness | `reap_stuck_jobs` gains optional `paths` kwarg; when given, audits requeue per job incl. `checkpoint: bool` (deep checkpoint file exists). Existing callers (supervisor.py:331) updated; bare call still works | B5.2.1 | ⬜ | Verify existing reap audit event name first (live-run doc mentions `dispatch.reaped`) |
| B5.2.3 | Crash→resume E2E proof | Offline test drives: deep job row `running` + real checkpoint file → `reap_stuck_jobs` → claim → `run_job` (offline stub research) → asserts: completes to `review`, checkpoint deleted, `job.resumed` audit row exists, previously-done nodes NOT re-researched (research_fn call-count proof), meta.resumed present | B5.2.1, B5.2.2 | ⬜ | Closes checklist 🔌 gap's offline-provable half; multi-hour live proof stays in LIVE_TEST_PLAN |
| B6.1 🖼️ | Dashboard renders "stalled" | `JobTrace`/`TraceStep` (web/static/app-lib.jsx:858-1012) give kind="stalled" a distinct visual (alert styling + label), so a stalled job reads as *stalled/failed*, never eternally-running. Evidence: screenshot `visuals/B6.1_stalled_trace.png` vision-checked | B5.1.4 | ⬜ | SSE `job.step` payload shape unchanged (new `kind` value only) |
| B6.2 🖼️ | Dashboard renders "resumed" | kind="resumed" renders an info marker with nodes-done count in the trace. Evidence: `visuals/B6.2_resumed_trace.png` vision-checked | B5.2.1 | ⬜ | |
| B6.3 | TUI passthrough check | TUI job/status views don't break on new event kinds (verify-only; change only if broken) | B5.1.4, B5.2.1 | ⬜ | tui/screens.py renders from same API |
| N1 🔒 | Egress guard / AIRGAP semantics | must not change | — | 🔒 | |
| N2 🔒 | HMAC audit-chain format | `append_event` API used as-is; new event *types* OK, format changes NOT | — | 🔒 | backend.stalled / job.resumed are new types, allowed |
| N3 🔒 | Grounding-gate thresholds | must not change | — | 🔒 | |
| N4 🔒 | Public CLI surface | no new/renamed commands this effort | — | 🔒 | |
| N5 🔒 | AGPL opt-in posture · legacy aliases · pyrate-limiter <4 · offline/no-daemon test posture | must not change | — | 🔒 | |

Progress: **3 ✔️ / 13 ⬜ / 0 🧩 / 0 🚫 / 5 🔒** (B3.1, B4.1 verified; B1/B2
existing spines verified by baseline run, tracked in BUILD_TREE.md).

Frontend↔backend seam (locked): `job_events` rows / SSE `job.step` payload
`{phase, kind, label, pct, data}` — this effort adds only new `kind` values
`"stalled"` and `"resumed"`; no field changes. `jobs.metadata_json` gains
optional `resumed: {nodes_done, pending}`.
