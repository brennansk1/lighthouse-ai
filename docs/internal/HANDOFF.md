# Handoff — Lighthouse (for the next agent to continue)

**Branch:** `claude/exciting-lamport-002bc3` · **Base:** `main` @ `a642f44` ·
**Ahead by ~24 commits.** Read this first, then the four Build-Tree artifacts
(below) — they are the source of truth, not this file.

---

## 0. Orientation (read in this order)

1. **`GOAL.md`** — what Lighthouse is *for* and the quality ranking
   (trustworthiness > privacy > auditability > honesty > hardware adaptivity;
   competitive bar = on par with Claude/Gemini deep research on local models).
   Every decision is weighed against this.
2. **`BUILD_MANIFEST.md`** — the living status ledger: every in-scope node, its
   contract, and status (✔️/⬜/🔒). This is the single source of truth for "what's
   done."
3. **`BUILD_TREE.md`** — the feature tree (BACKEND + FRONTEND spines) with status.
4. **`RECON.md`** — baseline datum, blast-radius scope, and the NO_TOUCH set
   (surfaces you must not change without explicit sign-off: egress guard/AIRGAP,
   HMAC audit-chain format, grounding-gate thresholds, public CLI surface, AGPL
   opt-in posture, pyrate-limiter `<4`, offline/no-daemon test posture).
5. **`NIGHT_SPRINT_REPORT.md`** — narrative of everything done this session +
   next steps (its §0 is the latest gap-closing follow-up).
6. **`FUTURE_FEATURES.md` §11** — the weighed roadmap (R-A…R-D).

**Working method (the framework these artifacts come from):** discovery before
code; contracts before integration; evidence (run tests / vision-check) before
marking anything done; keep the baseline suite green; commit one logical change
at a time. Update the Manifest after every step.

---

## 1. Environment (already set up on this machine — Apple M4, 24 GB)

- **Python/deps:** `uv sync --all-extras` done; full quality stack installed
  (FlagEmbedding, sentence-transformers, transformers, yara, pikepdf, …).
- **Ollama:** running with `qwen3.5:9b`, `qwen3.5:4b`, `bge-m3` (embedder), plus
  larger models. **Disk is tight (~94% full)** — do not pull big models.
- **Baseline gates:** `uv run pytest -q` · `uv run ruff check src tests` ·
  `uv run mypy src/lighthouse_ai`. Overnight datum: **3222 passed / 82 skipped /
  0 failed**, ruff+mypy clean. Re-confirm green before any push.
- **Real-backend tests** are opt-in: `LIGHTHOUSE_REAL_BACKEND=1`. Default suite
  never calls a real LLM and never starts daemons (dev-box stability — this box
  crashed once; respect it).

### Run it
```bash
uv run lighthouse-supervisor            # full app; dashboard http://127.0.0.1:8765
# or a daemon-free dashboard for UI work:
LIGHTHOUSE_DATA_DIR=<dir> .venv/bin/python3 scripts/_serve_dashboard.py
```
A scratch validation data dir with real drafts + a demo artifact (`d-demo`,
which has a persisted evidence snapshot so the chat is grounded) lives under the
session scratchpad; `.claude/launch.json` points the dashboard preview at it.

### Memory gotcha (important)
Under memory pressure, local-model synthesis is slow (~4 min/section seen at
25–39% free RAM) and a full Deep run can exceed 10 min. Close memory-hungry apps
before a Deep run, or pin the small model: `LIGHTHOUSE_FORCE_MODEL=qwen3.5:9b`.
This is a hardware artifact, not a bug.

---

## 2. What was done this session (grouped; see `git log a642f44..HEAD`)

**Build-Tree framework pass (UPGRADE→OPTIMIZE→EXTEND):**
- Stage 1 UPGRADE: stale-test repair, PEP 639 license metadata, lockfile refresh,
  doc-drift audit.
- Stage 2 OPTIMIZE: CLI startup + retrieval micro-benchmark — both measured,
  no change warranted (closed).
- Stage 3 EXTEND: **generation watchdog** (`BackendStalled` through
  backend→gateway→dispatcher + dashboard alert step); **deep-tier resume** made
  an observable lifecycle (`job.resumed`/`job.requeued` audit, `kind="resumed"`
  trace); dashboard renders stalled/resumed/degraded steps.

**Major feature — Artifact Chat** (`docs/ARTIFACT_CHAT_DESIGN.md`): chat with any
artifact, grounded in a persisted evidence snapshot, escalates to research when
thin, honest per-turn backend badge. Backend `modes/artifact_chat.py` +
`GET/POST /api/artifacts/{id}/chat` + a chat panel in
`web/static/app-pages-redesign.jsx`. Verified end-to-end on real Ollama.

**~12 bug fixes** (each with a regression test, mostly in
`tests/test_night_hardening.py`): a **blocker** (one corrupt DB row 500'd the
whole jobs list — `_json_field`), disk-preflight safety, CLI-draft→dashboard
parity, SSE silent-death reconnect, survey false-negative, entailment retry
storm, deepdive degrade-not-crash, empty-CSV headers, Markdown export of
structured artifacts, pynvml warning, init model-name clarity.

**Trust — mock-masquerade eliminated:** `gateway.complete()` now degrades to the
largest INSTALLED model that fits before mocking (was: silent mock). Provenance
labels a partly-mocked run `degraded` with a visible trace step. **Proven:**
forcing a too-big model degraded to a real `qwen3.5:9b` answer, not a mock.

**Quality — reliable inline citations:** explicit citation instruction + one-shot
retry in the deep-dive and chat synthesizers. **Proven:** a section over real
evidence cited `[1][2]` correctly on the first try.

**Privacy:** SSRF/DNS-rebinding egress guard (`net.py`) — a public name can't
resolve into internal space; cloud-metadata endpoint blocked; local services
(SearXNG/Qdrant on 127.0.0.1/LAN) still allowed.

**Measurement:** `eval/frontier_parity.py` — the R-A grader (breadth, grounding,
citation-verifiability, contradiction-honesty, open-question-honesty) so
"on par with frontier?" is a tracked number. Run a research question, then grade
the artifact's `body_json`.

---

## 3. Known gaps / next steps (prioritized)

1. **Frontend-perfection pass (TOP).** The UI is functional and the parts touched
   are polished, but NOT verified-perfect: 6 of 9 tabs not vision-checked; no
   accessibility (WCAG AA) audit; no responsive/dark-mode sweep; no per-view
   loading/empty/error-state verification. **Chat panel limits to close:**
   (a) reopened chats lose the rich per-turn view — `GET .../chat` returns only
   role/text/raw citation ids, so the backend badge, confidence band, and
   citation snippets don't survive a reload (persist richer turns in
   `ask_store` / a companion table); (b) streaming is request-response, not
   incremental — the server publishes `chat.token` SSE but the UI shows a
   "thinking…" state (wire the incremental render); (c) research escalation is
   arXiv-only v1 (broaden to recommender-driven multi-source per the design doc).
2. **Activate the entailment gate.** It is honest-by-design today (reports "not
   checked" without a scorer; never fabricates a pass), but inactive — MiniCheck
   isn't installed. `sentence-transformers`/`transformers` ARE installed, so an
   HHEM (`vectara/hallucination_evaluation_model`) or NLI cross-encoder path can
   be wired in `verification/entailment.py` (lazy, graceful). NB: the real model
   is a ~1.5 GB download — verify it before shipping the wiring (don't ship
   unverified model code; this project's rule is "measured, not assumed").
3. **Full deep-dive quality run + R-A grade.** On a freshly-booted box (more free
   RAM), run the 5 `BENCHMARK_QUESTIONS` in `eval/frontier_parity.py` through
   Deep tier, grade each, and record the frontier-parity numbers. This is the
   empirical "on par with frontier?" answer that's still a harness, not a result.
4. **Lower-priority, deliberately deferred:** Qdrant dimension-mismatch crash when
   switching embedders with Qdrant running (in-memory store is the default, so it
   doesn't bite today); acquisition budget counts injection-blocked docs against
   the source budget; Debate/Digest modes are shallow ("not deep" per the docs).
5. **Live-only release gates** (out of scope for local use): 24h soak, code
   signing, cross-platform Linux, PyPI publish — see `docs/RELEASE.md`.

---

## 4. Gotchas & rules

- **NO_TOUCH surfaces** (RECON.md §4) — don't change without explicit sign-off.
- **Don't ship unverified model code** into a verification path.
- **Keep the suite green**; commit one logical change at a time; update the
  Manifest. Never reach green by weakening/skipping a check.
- **Honesty invariant is load-bearing** — never let a degraded/mock result
  masquerade as real (the whole mock-masquerade fix exists for this).
- The scratch validation dir is disposable; the user's real data dir is
  `~/.lighthouse` (via `LIGHTHOUSE_DATA_DIR` unset).
- `scripts/_serve_dashboard.py` is a dev-only daemon-free server for UI work.
