# Lighthouse — Definition of Done (the production-grade bar)

> **What this document is.** The single, authoritative answer to *"is this done?"*
> It is the contract. A feature, fix, or change is **done** only when it clears
> **every** gate below — not when the code runs, not when tests pass, but when it
> is something a regulated-industry researcher *and* a non-technical member of the
> public can trust, understand, and use without help.
>
> **How to use it.** This file is the **rubric**. `docs/PRODUCTION_CHECKLIST.md` is
> the **status tracker** — where each feature currently sits *against this bar*.
> When the two disagree, this file wins on the standard; the checklist wins on the
> current state. Every time you mark something "done," cite the gates it cleared.
>
> **The one-line test for "done":** *Could we ship this to a paying, skeptical,
> non-technical user today and be proud of it — and would it still be honest if it
> failed?* If not, it is not done.

---

## 0. First principles (these override convenience)

1. **Trust over capability.** Lighthouse beats frontier tools on *trustworthiness*,
   not fluency. Any change that makes the output less honest, less grounded, less
   reproducible, or less auditable is a regression — even if it looks better.
2. **Design for the user's mental model, not the implementation's.** Plain language,
   no internal jargon in any surface ("we can read this page," never
   `extract_tier=static`). The user should never need to know how it works to use it.
3. **Simple by default, powerful on demand.** The common path is one obvious action
   with a sane default. Power and configuration are progressively disclosed, never
   in the user's face. **Complexity in the UI is a bug.** (See §4.)
4. **Honest when it fails.** A clean, plain-language failure/empty state beats a
   crash or a silent wrong answer every time. Confidence is never overstated.
5. **Resource-safe.** Offline-deterministic by default; no background processes
   started implicitly; never OOM the machine (defer, don't swap); real-LLM/heavy
   paths gated behind `LIGHTHOUSE_REAL_BACKEND=1`.

---

## 1. The per-feature Definition of Done (all 7 gates must pass)

A feature is done only when **every** gate is green. This is the checklist to run
against any mode, endpoint, UI surface, or subsystem before calling it complete.

### Gate 1 — Functional & complete
- Does what it claims, on the **whole** intended input range — not just the happy path.
- All states handled: success, **empty**, **loading**, **error + retry**, **offline**,
  **optional-dep-absent**, **permission/key-missing**.
- No declared stubs or "TODO: wire later" on the shipped path. If a capability is
  partial, it is **labeled** as such in the UI and in §3 of the checklist — not
  silently half-built.
- Inputs validated; bad input yields a clear **4xx with a human message**, never a
  500 or a malformed/empty artifact.

### Gate 2 — Tested (this is what "fully tested" means)
- **Offline unit test** for every new code path: deterministic (same input → same
  output with `gateway=None`), covers success + each failure/empty branch.
- **Integration test** for any real-backend/live path, **gated on
  `LIGHTHOUSE_REAL_BACKEND=1`**, that exercises the real dependency (LLM, source API,
  ML model, browser) — written so a live pass is turnkey, never started by default.
- **Property/fuzz test** where inputs are adversarial or invariants are load-bearing
  (parsers, scanners, token buckets, audit chain, dedup).
- **Regression test** pinning every bug we fix, so it can't return.
- Coverage: **≥80% overall**, **≥90% on persistence / governor / verification**.
  A line left uncovered is justified in writing (e.g. "lazy real-model path,
  exercised only under the live gate") — never just missing.
- The full offline suite is **green** (`pytest -q`), `ruff` clean, `mypy` 0 — the
  per-commit invariant. A red or skipped-without-reason test means not done.

### Gate 3 — Measured (no unverified quality claims)
- Any claim of quality has a **number on a fixed set that meets a written threshold**,
  not an assumption. Standing thresholds:
  - retrieval **recall@5 ≥ 0.8** and **MRR** reported (precision@k judged against its
    real ceiling for the eval set, not a mis-calibrated bar);
  - faithfulness / entailment **≥ 0.80** on the golden pairs;
  - source skill: a **recall@k** number on a held-out set + a green live fetch;
  - sandbox: **100% of known-hostile blocked, 0 false positives** on the benign corpus;
  - calibration: reliability reported with **uncertainty** (shrinkage + intervals),
    never a point estimate that pretends to more data than exists.
- If a number can't be measured yet (needs the live box), the feature is **🟡 "built,
  not measured"** in the checklist — never **✅**.

### Gate 4 — UX bar (simple, plain, humane) — see §4 for the full standard
- One obvious primary action; sane defaults; progressive disclosure of options.
- Plain-language labels and copy throughout; zero internal jargon on any surface.
- Loading, empty, and error states are designed (not blank, not a stack trace) and
  tell the user what to do next.
- Zero console errors; keyboard-reachable; basic ARIA; legible in light **and** dark;
  usable down to a narrow window.

### Gate 5 — Degrades safely
- Absent optional dependency, blocked egress, offline, missing API key, or low RAM ⇒
  a **clean, labeled fallback**, never a crash. The default install is fully usable.
- Every silent fallback or degradation is **logged** and **surfaced** to the user in
  plain language ("running without the reranker — install X for sharper results").
- Nothing the feature does can crash or corrupt an in-flight research run.

### Gate 6 — Honest & auditable
- Provenance recorded (mode, depth, backend real-vs-mock, models, sources, metrics,
  content hash); state-changing actions append to the HMAC audit chain.
- **Zero fabricated citations** — a cited chunk id that doesn't exist fails the gate.
- Contradictions surfaced, not smoothed; confidence bands applied and never inflated;
  a "no mock masquerade" check (a run that silently fell back to mock under a real
  gateway is a failure, not a pass).

### Gate 7 — Documented & discoverable
- The user can **find** it (it's in the UI/CLI with a purpose statement) and
  **understand** it (the in-app Info guide + README cover it in plain language).
- Developer-facing: docstring on public functions; the change is reflected in
  `MODE_PROCESSES.md` / `PRODUCTION_CHECKLIST.md` / `DEV_LOG.md` as appropriate.
- No doc claims a capability the code doesn't have (the README/checklist are honest).

---

## 2. The release gate (what makes the *whole product* done)

The per-feature gates make a *feature* done. These make **v1.0 shippable**. All must
be green before we call the product production-grade:

- **R1 — Core claim measured live.** Real-LLM framing/synthesis quality, retrieval,
  and faithfulness scored on the golden set under `LIGHTHOUSE_REAL_BACKEND=1`, meeting
  thresholds. The "better than frontier on trust" claim is *measured*, not asserted.
- **R2 — Every shipped source skill** has a green live fetch + a recall number, and
  key-gated sources verified *with* keys and degrade gracefully *without*.
- **R3 — Every dashboard tab** passes browser QA (real Chromium): renders, zero
  console errors, axe a11y pass, keyboard-reachable, light/dark, interaction flows
  (wizard launch, pause, upload-blocks-EICAR) work end-to-end.
- **R4 — Calibration loop closed live:** a real Position resolves from real evidence
  (not parametric self-grading), Brier/reliability updates, surfaced honestly in Track.
- **R5 — Durability proven:** 24h supervisor soak (no OOM, no fd/conn leak, RSS
  stable) + a disaster-recovery drill (kill mid-write → restore → schema intact).
- **R6 — Cross-platform:** suite green on Linux + macOS; systemd unit and launchd
  plist install and run.
- **R7 — Security reviewed:** egress / injection / sandbox boundary reviewed, no high
  findings open; redteam corpus green in CI.
- **R8 — Packaged & installable:** `pip install lighthouse-ai` (or signed app) →
  `init` → `start` → a real research run, on a clean machine. Signed macOS app +
  PyPI publish flow verified.
- **R9 — Repo gates standing:** CI green (pytest + ruff + mypy, macOS + Linux),
  coverage thresholds met, on every push.
- **R10 — Definition-of-done met for every feature** in the checklist — no ✅ that
  hasn't actually cleared §1.

---

## 3. The UX standard (§4 expanded — first-class, because the user asked for it)

> The product is for regulated-industry researchers **and** the general public.
> "Avoid complicated UI/UX" is a binding requirement, not a nicety. When engineering
> elegance and user clarity conflict, **user clarity wins.**

**The simplicity rules (each is a pass/fail check on every screen):**

1. **One primary action per screen.** The thing the user most likely wants is the
   biggest, most obvious control. Everything else is secondary and quieter.
2. **Sane defaults, so the common case needs zero configuration.** A first-time user
   should get a good result by pressing the obvious button — depth, sources, and mode
   pre-chosen sensibly (with "Auto" where it fits) and explained in one short line.
3. **Progressive disclosure.** Advanced options (reproducibility lock, source picker
   detail, budgets) are tucked behind a clear "more options" affordance — present for
   power users, invisible to everyone else.
4. **Plain language everywhere.** Every label, button, tooltip, empty state, and error
   reads like a person wrote it for a non-expert. No internal keys, no acronyms
   without expansion, no leaked implementation detail. ("We couldn't read this page"
   not "extract_tier=static failed".)
5. **Every state is designed.** Loading shows progress or a skeleton; empty explains
   what would go here and how to fill it; error says what happened and the one thing
   to try next (with a retry). A blank screen or a raw error is a failure.
6. **Tell the user what they get.** Each surface answers "what does this let me *do*?"
   in a one-line purpose statement.
7. **No dead ends.** Every error and empty state offers a next step. Every long task
   shows it's working and can be paused.
8. **Honest confidence, visibly.** The red→green confidence band and "review this"
   framing are always present so the user is never misled about certainty.
9. **Accessible & responsive.** Keyboard-reachable, basic ARIA, legible contrast in
   light and dark, no layout break in a narrow window.
10. **Consistent.** The same action looks and behaves the same everywhere; one visual
    language across all tabs.

A UI change that adds a control, a setting, or a concept must **justify the added
complexity against these rules** — or simplify instead. The default answer to "should
we add another option here?" is *no; pick a better default.*

---

## 4. How work proceeds (the loop, so quality is built in, not bolted on)

For every item taken to done:

```
1. Confirm a green baseline (pytest -q, mypy, ruff) before touching code.
2. Build the smallest coherent slice, user-facing behavior first.
3. Run it against the §1 gates; list concrete gaps.
4. Refine until every gate passes (test-and-refine loop, not one-shot).
5. Lock with tests (Gate 2), update docs (Gate 7), confirm green baseline again.
6. Commit a clear increment; update PRODUCTION_CHECKLIST status + DEV_LOG.
7. Only then move to the next item.
```

**Non-negotiable per-commit invariants** (carry forward, never violate): full offline
suite green; `mypy` 0 on `src/lighthouse_ai`; `ruff` clean; new paths
offline-deterministic with graceful fallback; live-only paths gated by
`LIGHTHOUSE_REAL_BACKEND=1`; no background process started implicitly; never OOM.

---

## 5. What "done" explicitly is **not**

- ❌ "Tests pass" — that's Gate 2 only; six other gates remain.
- ❌ "It works on my happy-path input" — Gate 1 needs every state handled.
- ❌ "It works but the UI is a bit rough" — Gate 4 is a hard gate, not polish.
- ❌ "We claim it's accurate" — Gate 3 needs a measured number meeting a threshold.
- ❌ "Built but not yet validated with real data" — that is **🟡**, never ✅.
- ❌ "Documented in code comments" — Gate 7 needs the *user* to find and understand it.
- ❌ "Good enough for a demo" — the bar is a skeptical paying user, not a demo.
