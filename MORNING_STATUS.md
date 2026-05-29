# Overnight build — morning status

Branch: `night/finish-to-quality` (all work committed; nothing pushed). Suite:
**1295 passing, 5 skipped** (real-backend + litestream gated), ruff clean.

## What shipped tonight (committed)

**Foundation — real-LLM safety**
- **RAM-safety guard (#26):** model selection respects *live-free* RAM (not total
  capacity), a free-RAM floor defers the dispatch tick instead of thrashing, and
  the gateway tallies the backend actually used so a "mock masquerade" (a real run
  silently degraded to mock) is visible. Validated: a real Decide run picked a
  fitting 14B and produced real output (`backend=ollama`, no OOM).

**The competitive thesis — trustworthiness frontier tools lack**
- **Provenance manifest (#48):** every artifact records mode, depth, backend,
  models, source count, metrics, content hash — deterministic + reproducible.
- **Triangulation + contradictions + fabricated-citation guard (#47):** key
  claims need ≥2 *independent* sources; contradictions surfaced; a cited chunk id
  that doesn't exist fails the gate.
- **Adversarial refutation (#45):** a skeptic tries to refute each key claim;
  refuted/contested claims don't stand.
- **Coverage critic (#46):** coverage scored against the framing plan's
  load-bearing sub-questions; gaps drive another round or become known-unknowns.
- **Depth tiers (#44, #53):** Quick / Standard / Thorough / Deep wired to engine
  knobs AND exposed in the Research tab (Deep requires a budget). Investigate
  honors depth and runs the critic (Standard+) and adversarial pass (Thorough+).
- **Deep recursive engine (#51):** `run_exhaustive` decomposes a question into a
  bounded, dedup-terminating tree with grounded-or-known-unknown leaves — the
  depth Claude/Gemini's 10–20-min time-box can't reach.
- **Benchmark (#49):** scores artifacts against the bar and proves the grounding
  gate catches a planted hallucination.

**Speed / production**
- **Model-role discipline (#55):** Decide/Survey/Reconstruct structured calls use
  the fast aux model, not the heavy reasoner (the cause of the slow Decide run).
- **Adjudicate min-tier (#36):** Quick is promoted to Standard server-side.

**Integrations & docs**
- **Telegram (#42):** per-artifact-type review templates, budget refs removed.
- **Logseq (#43):** structured rendering for all 7 artifact types.
- **Exports (#31):** md/csv/json verified for all 7 artifact types.
- **README + depth matrix (#34):** updated to the 7-mode, depth-tiered system.
- **Test coverage (#33):** real-backend-gated mode tests + a create_app
  no-daemon safety test.
- **UX (#30):** all 8 tabs render with purpose statements, zero console errors.

## Real-LLM validation
- **Decide:** ✅ `backend=ollama`, correct matrix, no OOM (~slow on 14B → fixed by #55).
- **Adjudicate:** ✅ 168s, `backend=ollama`, verdict + provenance.
- **Investigate (standard depth):** real run is slow on a 14B reasoner (many
  rounds × sections) — bounded by the LoopDetector, but minutes-scale. Use Quick
  for fast turnarounds; the depth doc carries the hardware caveat.

## Remaining (clearly scoped tasks #28, #29, #32, #37–#41, #50, #52, #54, #56)
- **#56 Wire Deep tier into Investigate dispatch** — the exhaustive engine is built
  + tested standalone; depth=deep currently runs a 12-round deepdive (reasonable),
  the recursive-tree route is the enhancement.
- **#52 Long-run resilience** — checkpoint/resume for hours-long Deep runs.
- **#28 Grounding (auto-fetch)** — corpus modes ground when documents are attached;
  auto-fetch wiring is network-touching, left for supervised work.
- **#29 Survey wizard inputs** — needs a document-ingestion UI (larger piece).
- **#50 reviewable plan / #54 auto-tier** — need a classify endpoint.
- **#32 code+security review**, **#37–#41 remaining real-LLM mode validations**.

## How to run
```bash
.venv/bin/python -m pytest -q                 # offline suite (1295 pass)
LIGHTHOUSE_REAL_BACKEND=1 .venv/bin/python -m pytest tests/test_modes_real_backend.py
.venv/bin/python -m lighthouse_ai.eval.research_benchmark   # grounding scorecard
# Dashboard: .venv/bin/python -m lighthouse_ai ...  (serve(run=True) for live dispatch)
```
