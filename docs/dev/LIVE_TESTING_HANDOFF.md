# Lighthouse — Live-Testing Handoff

> **Read this first.** You are a fresh Claude session picking up Lighthouse to run the
> **live-hardware validation pass** on the user's Mac mini. Everything below is self-contained — you do
> not need prior conversation context. The product is **feature-complete and green offline**; your job
> is to validate it against **real backends** (a real local LLM, real source APIs, real optional ML
> models, a real browser) and **record the numbers**. Companion docs:
> `docs/dev/DEV_LOG.md` (full progress + backlog), `docs/PRODUCTION_CHECKLIST.md` (the acceptance
> tables + Deployment readiness), `README.md` (overview).

## Prime directives (do not violate)
1. **Local-first is the product.** Nothing leaves the user's hardware. Do NOT add cloud LLM calls or
   send the corpus anywhere. All validation is local.
2. **Do not crash the machine.** The user's Mac crashed once from memory pressure. **Never** run
   uncontrolled parallel model loads. Start with the **smallest** model that fits, watch RAM, and trust
   the built-in guardrails (`ollama_slot` admission, the KV/context OOM headroom, the global Pause).
   When in doubt, use a smaller model and `LIGHTHOUSE_OLLAMA_QUEUE` admission on.
3. **No background processes** beyond the supervisor the user starts. Run validation as foreground,
   bounded commands.
4. **Record, don't assume.** The point of this pass is to replace "should be ≥X" with measured numbers.
   Update the relevant rows in `docs/PRODUCTION_CHECKLIST.md` → "Deployment readiness" and the acceptance
   tables, and append a results section to `docs/dev/DEV_LOG.md`.

## Current state
- Branch `main` (latest pushed). Offline suite: ~2860 pass / ~103 skip, **mypy 0**, **ruff clean**,
  coverage ~82%, CI green on macOS + Linux × py3.11/3.12. ~32 real bugs fixed in a 4-wave audit.
- Confirm a clean baseline before live work:
  ```bash
  uv sync
  uv run ruff check src tests && uv run mypy src/lighthouse_ai
  uv run pytest -q            # expect ~2860 pass, ~103 skip (the skips are what you're about to enable)
  ```

## Hardware → model tiers (from `src/lighthouse_ai/catalog/models.yaml`)
- **T2 = 24 GB (the Mac mini target):** roles bind to `qwen3.6-35b-a3b` — a **MoE that pages experts
  from SSD** (≈3.3B active), embeddings `bge-m3` (1024-dim), plus a cross-encoder reranker. The
  hardware guardrails are tuned so this fits without swapping; a dense 32B is correctly *blocked* from
  admission.
- **T1 = 16 GB:** `qwen3.5-9b`. If RAM is tight or the MoE tag isn't installed, start here.
- The gateway picks the **best model that fits** the live free-RAM budget and steps down gracefully;
  `ollama_slot` is the cross-process RAM admitter. If a model can't be admitted it falls back to a
  smaller one or the mock — it should never load-and-swap.

## Environment setup (do once)
```bash
# 1. Ollama + models (pick per RAM; bge-m3 is required for real retrieval)
brew install ollama            # or the official installer; then `ollama serve` if not auto-started
ollama pull bge-m3             # embeddings (~1.2 GB) — REQUIRED
ollama pull qwen3:30b-a3b      # 24 GB MoE reasoner (pages) — or `qwen3:14b` / `qwen3:8b` if tighter
# (the catalog names are capability-classes; resolve_against_installed maps them to your real tags)

# 2. Optional ML extras (install only what a given phase needs — they pull torch/transformers)
uv sync --extra reranker        # FlagEmbedding (bge-reranker-v2-m3) — for retrieval precision
uv sync --extra faithfulness    # sentence-transformers (MiniCheck/HHEM) — for the faithfulness gate
uv sync --extra extraction      # trafilatura/pdfplumber/docling — better extraction fidelity
uv sync --extra politeness --extra sandbox-hardening --extra injection-ml --extra youtube
uv sync --extra js-render && uv run playwright install chromium   # Tier-B JS render + browser QA

# 3. Optional Qdrant (persistent vectors; in-memory works without it)
docker compose -f ~/.lighthouse/stack/lh-stack.yml up -d   # if present; else skip

# 4. Free API keys for live SOURCE validation (set as env OR via the dashboard Settings → "Connect your
#    data sources"; the keyring path is preferred). Env var names the adapters read:
export FRED_API_KEY=...    BEA_API_KEY=...    BLS_API_KEY=...    CENSUS_API_KEY=...
# Congress.gov / GovInfo / CourtListener / The Guardian / regulations.gov take an api_key — set via
# Settings (stored in the OS keychain) or pass per-call. Semantic Scholar works keyless (rate-limited).
# Self-hosted web search: export LIGHTHOUSE_SEARXNG_URL=http://localhost:8888

# 5. The switch that un-skips the live tests:
export LIGHTHOUSE_REAL_BACKEND=1
```

## The validation plan (phased — record numbers as you go)
All gated tests live in `tests/test_real_*.py` (+ `test_backends_ollama.py`, `test_modes_real_backend.py`,
`test_rag_real_backends.py`). They **skip** unless `LIGHTHOUSE_REAL_BACKEND=1` **and** Ollama is
reachable on `127.0.0.1:11434` (some additionally `importorskip` the ML extra). Thresholds come from
`docs/PRODUCTION_CHECKLIST.md`.

### Phase 1 — Measure the core quality claim (highest leverage)
This is what proves "better than frontier on trust." Do this first.
```bash
# Real-backend smoke: one real Ollama completion + bge-m3 embedding round-trip
LIGHTHOUSE_REAL_BACKEND=1 uv run pytest tests/test_backends_ollama.py tests/test_rag_real_backends.py -v

# Retrieval quality on the golden set (needs bge-m3; reranker extra for the ≥0.55 case)
LIGHTHOUSE_REAL_BACKEND=1 uv run pytest tests/test_real_retrieval_quality.py -v
uv run lighthouse eval        # prints precision@5 / recall@5 / MRR with the real embedder+reranker
#   TARGETS: precision@5 ≥ 0.40 (stub baseline is 0.20); ≥ 0.55 with contextual retrieval + FlagReranker.
#   If <0.40 with the real reranker, that's a finding — capture it and investigate before claiming the bar.

# Faithfulness gate (needs the faithfulness extra)
LIGHTHOUSE_REAL_BACKEND=1 uv run pytest tests/test_real_faithfulness.py -v   # TARGET mean ≥ 0.80

# Per-mode end-to-end against the real LLM (investigate/survey/reconstruct/decide/adjudicate/ask/watch)
LIGHTHOUSE_REAL_BACKEND=1 uv run pytest tests/test_real_modes_e2e.py tests/test_modes_real_backend.py -v
#   Assert each artifact passes the discipline gate (cited, grounded, ZERO fabricated citations).
```
**Record:** the precision@5 / MRR / faithfulness numbers + per-mode pass/fail into the PRODUCTION_CHECKLIST
§3 (RAG) and §5 (honesty) rows and the Deployment-readiness "A/C" bullets.

### Phase 2 — Live source APIs (the 37 skills)
```bash
LIGHTHOUSE_REAL_BACKEND=1 uv run pytest tests/test_real_skills_fetch.py -v   # one live fetch per skill
```
Validate per source: the real endpoint shape still parses, rate limits respected, auth keys work,
graceful degradation when a domain isn't trust-added. Use `uv run lighthouse doctor news` for the news
outlets. Do the **regulated-industry wedge first** (PubMed, ClinicalTrials, CourtListener, SEC EDGAR,
Federal Register/GovInfo/Congress). Record per-skill recall@k via `eval/skill_eval.py`. Sources are
rate-limited and many block cloud IPs — local is fine; be patient and small (`max_results` low).

### Phase 3 — Surfaces & ops
- **Browser QA (Playwright):** start the app (`uv run lighthouse init && uv run lighthouse-supervisor`,
  open `http://127.0.0.1:8765/`). Walk every tab: Research wizard (recipes → source picker →
  launch), Library (artifact + "How the evidence connects" + known-unknowns + contradictions), Watch
  ("Monitor a website" verify→criteria→save), Sandbox (upload→scan→analyze), Settings (API keys +
  Reproducibility lock), Health (Sources card), Info (in-app guide), and the **global Pause** button
  (confirm it actually stops the loops — check logs show ticks skipped). Capture console errors / a11y.
- **Calibration loop live:** the resolver cron runs only under `LIGHTHOUSE_REAL_BACKEND=1`; record a
  Position resolving + a Brier update over time.
- **Sandbox hardening:** with `--extra sandbox-hardening`, run the redteam corpus; confirm YARA/pikepdf
  catch hostile payloads with **no false positives** on benign (incl. EICAR still rejected).
- **Persistence/replication:** bring up Qdrant + (optional) install the `litestream` binary; restore drill.

### Phase 4 — Package & ship
24h supervisor soak (no OOM/leak), cross-platform (Linux/systemd), packaging (`pip install` + signed
macOS app + launchd/systemd), a security review of the egress/injection/sandbox boundary. (The Tauri
one-click desktop app — bundling local Ollama/Qdrant — is a separate build task needing Node/Tauri;
see `FUTURE_FEATURES.md` §1/§8.)

## Safety knobs while testing
- **Global Pause:** the dashboard "⏸ Pause all" button or `uv run lighthouse pause` stops every 24/7
  loop (resume with `lighthouse resume`). Use it to reclaim the machine.
- **Admission queue:** `LIGHTHOUSE_OLLAMA_QUEUE` defaults on — keep it on; it prevents stacked cold
  model loads. The scheduler gate throttles on battery / high CPU.
- If RAM gets tight: pull a smaller reasoner (`qwen3:8b`), or set `offline` to force stubs while you
  debug non-LLM paths.

## Where to write results
1. **`docs/PRODUCTION_CHECKLIST.md`** — flip the relevant 🟡/⬜ rows to ✅ with the measured number, or
   to a finding if a threshold misses. Update the "Deployment readiness" A–D bullets.
2. **`docs/dev/DEV_LOG.md`** — append a "Live validation results (date)" section: numbers, what passed,
   what didn't, and any new bug found (fix it with a regression test, keep the suite green, commit).
3. Commit + push each increment to `main` (the user wants frequent pushes). Keep `mypy 0` + `ruff clean`.

## If you find a bug during live testing
Fix it the same way the audit did: a failing-first regression test (deterministic/offline where
possible), the fix, confirm the full suite + mypy + ruff are green, commit + push. Real backends surface
things mocks can't — expect a few.

## Deep references (in-repo)
`docs/MODE_PROCESSES.md` (7 modes), `SKILL_FRAMEWORK.md` + `MODE_SKILL_INTEGRATION.md` +
`SKILL_LIBRARY_V1.md` (skills/sources), `docs/lighthouse_design.md` (design), `FUTURE_FEATURES.md`
(roadmap), `docs/research_depth_matrix.md` (depth tiers).
