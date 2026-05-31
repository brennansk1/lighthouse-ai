# Overnight build — morning status

> **⚠️ HISTORICAL (superseded).** This captures the `night/finish-to-quality` era
> (~1295 tests). The current state is far ahead (2889 tests, live-validated). For
> where things actually stand, read `DEV_LOG.md` → "Current state" and the bar in
> `../DEFINITION_OF_DONE.md`. Kept for provenance only.

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

## Real-LLM validation (all backend=ollama, provenance recorded — no mock masquerade)
| Mode | Wall-clock | Artifact |
|------|-----------|----------|
| Decide | ~slow on 14B → fixed by #55 (aux model) | matrix |
| Adjudicate | 168s | verdict |
| Ask | 65s | transcript |
| Investigate (standard depth) | 788s (~13 min) | report |

Investigate at standard depth is minutes-scale on a 14B reasoner (4 rounds ×
sections), bounded by the LoopDetector — use Quick for fast turnarounds; the
depth doc carries the hardware caveat. Survey/Reconstruct/Watch are
offline-dispatch-tested; their real value needs ingested documents/sources
(see #28/#29).

## Also shipped (second wave)
- **Deep tier wired (#56):** depth=deep routes Investigate to the recursive
  exhaustive engine (budget-capped tree, grounded-or-known-unknown leaves).
- **Auto depth (#54):** `/api/classify` → question-type → suggested tier; wizard
  defaults to Auto ("Auto chose Standard…").
- **Reviewable plan (#50):** the Review step shows the framing plan
  (load-bearing sub-questions) before launch — Gemini-style, but grounded.
- **Exports (#31), depth selector (#53), model-role speed (#55), docs (#34),
  UX sweep (#30), test coverage (#33)** — all done.

## Genuinely remaining (larger / needs supervision — not started)
- **#28 Grounding auto-fetch** — network egress (arXiv/OpenAlex) into the
  dispatcher; left for supervised work (sandbox/egress review).
- **#29 Survey/Reconstruct wizard inputs** — needs a document-ingestion UI.
- **#52 Long-run resilience** — full checkpoint/resume of an in-flight Deep tree
  (progress emission is the next safe slice).
- **#32 Code + security review** of the night's diff.
- **#39/#40/#41** Survey/Reconstruct/Watch real-LLM validation — needs an
  ingested corpus / sources to be meaningful (offline dispatch is tested).

## Tally
24 tasks completed tonight (#26, #30–#38, #42–#56, #50, #53–#55 + adjudicate
min-tier). Suite **1297 passing, 5 skipped**, ruff clean, ~28 commits on
`night/finish-to-quality`.

## How to run
```bash
.venv/bin/python -m pytest -q                 # offline suite (1295 pass)
LIGHTHOUSE_REAL_BACKEND=1 .venv/bin/python -m pytest tests/test_modes_real_backend.py
.venv/bin/python -m lighthouse_ai.eval.research_benchmark   # grounding scorecard
# Dashboard: .venv/bin/python -m lighthouse_ai ...  (serve(run=True) for live dispatch)
```
