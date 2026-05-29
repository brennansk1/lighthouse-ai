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

## Work queue (priority order)
P1 Real-LLM safety + correctness (foundation)
P2 Substantive grounding (corpus retrieval / auto-fetch in dispatch)
P3 Wizard input completeness per mode
P4 UX polish pass (states, a11y, responsive, console-clean)
P5 Code review + security review, fix findings
P6 Test coverage hardening (offline + real-backend gated)
P7 Documentation

See the task list (TaskCreate IDs 26+) for the executable breakdown.
