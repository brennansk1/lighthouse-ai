# Lighthouse — Overnight Finish-to-Quality Plan

Goal: take Lighthouse from "all 7 modes wired" to "production-grade, ready for
real use" overnight, autonomously. This file is the source of truth for the
quality bar and the work queue. Each task lists its **Definition of Done (DoD)**.

## Non-negotiable invariants (carry forward — never violate)
- **Resource safety first.** The Mac crashed once. No process started by
  `create_app()`. Single gated daemon, one job per tick. Real-LLM dispatch must
  pick models that fit *measured free RAM* and must never OOM. Add a free-RAM
  floor admission check; rely on the single `ollama_slot` seam — no second queue.
- **Offline determinism.** Every engine deterministic when `gateway=None`. The
  default test suite is offline + LLM-free. Real-backend tests gate behind
  `LIGHTHOUSE_REAL_BACKEND=1`.
- **No budget anywhere.** Display-layer renames only (internal keys/columns/API
  field names stable). Python is always `.venv/bin/python`.
- **Every gate stays:** LoopDetector, InjectionGate, SchedulerGate, RAM admission.

## Global Definition of Done (applies to every change)
1. `.venv/bin/ruff check src/ tests/` clean.
2. `.venv/bin/python -m pytest -q` fully green; new code paths covered offline.
3. No JS console errors on any page.
4. Work committed on a feature branch with a clear message.
5. Resource-safety invariants above demonstrably hold.

---

## Quality standards by feature

### Research modes (all 7)
- Launchable from the wizard with every input the engine needs.
- Offline: deterministic stub artifact, no crash.
- Real Ollama: substantive, **grounded** artifact (real sources where the mode
  is corpus-backed) that fits in RAM and completes without OOM.
- Artifact persists to Library, renders in its typed viewer, exports md/csv/json.

### Dashboard (every page)
- Purpose statement; loading, empty, and error+retry states; plain-English copy.
- Keyboard-accessible, basic aria, responsive down to a narrow window.
- Zero console errors.

### Backend
- Endpoints typed + validated; clear 4xx messages.
- Audit-chain entries for state-changing actions.
- No silent failures; everything logged.

### Tests
- Offline unit test per new path; real-backend gated integration per mode.

### Docs
- README quickstart, architecture overview, per-mode reference, run guide.

---

---

## MODE QUALITY STANDARD (the bar every research mode must clear)

This is the acceptance checklist. A mode is "done" only when **every** item
passes. Each mode is taken **one at a time** through a test-and-refine loop:
**run → evaluate against this bar → list gaps → refine → re-run → repeat** until
all items pass, then lock with tests and commit before moving to the next mode.

### Universal checklist (all 7 modes)
1. **Launch** — launchable from the Research wizard with every input it needs;
   missing/invalid inputs give a clear 400, not a 500 or empty artifact.
2. **Offline determinism** — with `gateway=None`: well-formed, non-empty,
   schema-complete artifact; no crash; same input → same output (deterministic).
3. **Real backend** — with a RAM-fitting Ollama model: a *substantive* artifact
   that (a) populates all required schema fields, (b) is grounded — claims tied
   to real sources/citations for corpus-backed modes, no fabricated sources,
   (c) is coherent and on-topic, (d) passes the citation/discipline gate.
4. **No mock masquerade** — a run that silently fell back to `mock-lowmem`/`mock`
   under a real gateway is a FAIL; surface the backend used and require real
   output (or defer the job) when the user asked for real.
5. **Persist** — lands in Library: correct `artifact_type`, `status='staged'`,
   job → `review`; Positions recorded where the mode supports calibration.
6. **Render** — displays in its typed viewer; all key fields visible; zero
   console errors.
7. **Export** — md / csv / json each produce complete, sensible content.
8. **Resource-safe** — completes in reasonable wall-clock on a fitting model;
   never OOMs; degrades gracefully (defer, not swap) when RAM is tight.
9. **Tested** — offline unit test (determinism + shape) AND a
   `LIGHTHOUSE_REAL_BACKEND=1`-gated integration test.

### Per-mode acceptance criteria
- **Watch → digest:** polls sources/topic; digest of new+salient items with
  category + salience; duplicates suppressed; alerts vs digest split correct.
- **Ask → transcript:** answer turn is responsive to the question and cites the
  retrieved chunks it used; supports follow-up turns; no ungrounded claims.
- **Investigate → report:** sectioned report addressing the question; per-claim
  citations; each claim graded for faithfulness; established/disputed/unknown
  coverage.
- **Survey → table:** PRISMA screen with correct identified/included counts;
  one cell per (doc × attribute) with citation + entailment flag; cells faithful
  to the source doc.
- **Reconstruct → timeline:** dated events extracted (date, actors, action),
  deduped, date conflicts resolved by weighted vote, ordered chronologically,
  per-event certainty + sources.
- **Decide → matrix:** every option×criterion cell scored; weighted totals +
  argmax winner; sensitivity sweep; crux statement that is meaningful and
  Adjudicate-ready.
- **Adjudicate → verdict:** N distinct, substantive perspectives; weighed; a
  verdict that names the real crux of disagreement (not a flattened take).

### The per-mode loop (definition of "until desired quality")
```
for mode in [Watch, Ask, Investigate, Survey, Reconstruct, Decide, Adjudicate]:
    repeat:
        run offline  -> check items 1,2,5,6,7
        run real     -> check items 3,4,8   (skip real only if RAM cannot fit
                                             the smallest model; note it)
        score against universal + per-mode criteria -> list concrete gaps
        if no gaps: lock tests (item 9), commit, break
        else: refine engine/adapter/viewer, repeat
```

---

## Work queue (priority order)
P1   Real-LLM RAM-safety guard (foundation)               -> task #26
P1.5 Per-mode test-and-refine loops, one at a time        -> tasks #35-#41
P2   Substantive grounding (corpus retrieval/auto-fetch)  -> task #28
P3   Wizard input completeness per mode                   -> task #29
P4   UX polish + artifact viewers/exports                 -> tasks #30, #31
P5   Code review + security review                         -> task #32
P6   Test coverage hardening                               -> task #33
P7   Documentation                                         -> task #34

Note: P2 (grounding) and P3 (wizard inputs) are pulled *into* each mode's loop
as needed — a mode is not "done" until it is grounded and launchable. The
standalone P2/P3 tasks remain as backstops / cross-cutting cleanup.
