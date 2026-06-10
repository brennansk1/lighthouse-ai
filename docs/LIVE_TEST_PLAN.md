# Lighthouse — Live Test Plan (the release validation matrix)

> Everything offline-buildable is built, green, and pushed (3,140+ tests, mypy 0,
> ruff clean). This document is the **complete list of tests that can only run
> live** — on real hardware, real models, real source APIs, a real browser —
> with the **standard each result must meet**. Run top to bottom; later phases
> assume earlier ones passed. Record every measured number in
> `docs/PRODUCTION_CHECKLIST.md` (acceptance tables) and append a dated results
> section to `docs/dev/DEV_LOG.md`.
>
> Companions: `docs/RELEASE.md` (R5–R8 runbook: soak, cross-platform, signing,
> live calibration), `docs/dev/LIVE_TESTING_HANDOFF.md` (cold-start operator
> guide and safety directives — read its Prime Directives first),
> `docs/DEFINITION_OF_DONE.md` (the gates these standards come from).

**Operator safety (non-negotiable):** local-first — nothing leaves the machine;
start with the smallest model that fits and watch RAM; no uncontrolled parallel
model loads; foreground, bounded commands only.

---

## Phase 0 — Environment baseline

| # | Test | How | Standard |
|---|------|-----|----------|
| 0.1 | Clean install | `uv sync --all-extras` on a fresh clone | Completes without error on macOS and Linux |
| 0.2 | Offline gates on this hardware | `make check` | Full suite green, ruff clean, mypy 0 — identical to CI |
| 0.3 | Models present | `ollama pull bge-m3` + the doctor-recommended chat model | `lighthouse doctor` exits 0; every role shows "fits" (or "pages SSD" with the note, never silent) |
| 0.4 | Doctor honesty | `lighthouse doctor` with: keyring absent, <5 GB disk (simulated), `secrets.toml` chmod 644 | Each degradation is reported in plain language; loose secrets perms exit non-zero |
| 0.5 | First-run path | `lighthouse init` → follow the printed 3-step card exactly, nothing else | A first research run completes using only what the card says; dashboard reachable at the printed URL |

## Phase 1 — Retrieval & grounding quality (real `bge-m3` + reranker)

| # | Test | How | Standard |
|---|------|-----|----------|
| 1.1 | Hybrid retrieval | `lighthouse eval` golden set, real embedder | recall@5 ≥ **0.95**, MRR ≥ **0.95** (2026-05-29 live baseline was 1.000/1.000 — regression means investigate) |
| 1.2 | Reranker lift | golden set with FlagReranker installed vs without | MRR lift ≥ **5%** over hybrid baseline, or documented as neutral-on-this-set |
| 1.3 | Contextual retrieval lift | recall vs no-preamble baseline | ≥ **10%** recall lift (Anthropic pattern) or measured + recorded if lower |
| 1.4 | Entailment gate (real MiniCheck/HHEM) | 20-pair golden set with `faithfulness` extra | mean faithfulness ≥ **0.80** (live baseline 1.000); no entailing pair below threshold |
| 1.5 | **Zero fabricated citations** (the hard invariant) | 10 real runs across modes/tiers; for every `[N]` in every artifact, resolve it against the run's evidence | **0** citations that resolve to nothing, at every tier including Quick. Any violation is a release blocker |

## Phase 2 — Deep research: breadth, depth, and the frontier comparison

The claim under test: *Lighthouse compensates for a weaker model with tools,
strategy, scaffolding, and time.* These tests measure that directly.

| # | Test | How | Standard |
|---|------|-----|----------|
| 2.1 | Iterative acquisition fires | Standard-tier Investigate on a question the upfront corpus can't fully answer; watch the run trace | ≥ 1 "+N documents" `sources` step after round 1; the documents appear in the artifact's source count and provenance |
| 2.2 | Breadth scales with tier | Same question at Quick / Standard / Thorough / Deep; record distinct documents consulted (job meta + audit log) | Monotonically increasing; Thorough reaches **≥ 30** distinct documents on a research-rich topic; Deep **≥ 75**. Caps (60/150/400) never exceeded |
| 2.3 | Per-sub-question source selection | Deep run on a question spanning domains (e.g. "FDA approval timeline + market reaction to drug X") | The trace shows different skills fetched for different sub-questions (e.g. regulations_gov for the FDA branch, sec_edgar for the market branch) |
| 2.4 | Link chasing (Deep) | Deep run; inspect audit log for `via: link_follow` fetches | ≥ 1 followed link on a link-rich topic; all followed hosts within the egress allowlist; budget (5/node) respected |
| 2.5 | Politeness under fan-out | During 2.2, monitor per-domain request timing (egress audit) | No domain hit faster than its crawl-delay/rate budget; zero robots.txt violations |
| 2.6 | Stuck-but-open recovery | A question where round-1 sources are thin | The run acquires instead of stopping early; rounds_used grows; final report has fewer open questions than the pre-acquisition draft |
| 2.7 | **Frontier comparison** | 5 benchmark questions (pick from docs/research_prompts/) run on Lighthouse Thorough+Deep AND on Claude / Gemini deep research; blind-grade the three outputs per question on: source count, claim accuracy, citation verifiability, contradiction honesty, open-question honesty | Lighthouse **wins or ties on citation verifiability and honesty columns on ≥ 4/5 questions** (its structural edge); is within reach on breadth (≥ 60% of frontier source count at Deep); narrative quality gap is recorded honestly, not spun |
| 2.8 | Deep wall-clock budgets | 30m / 1h / overnight budgets | Each run finishes within budget +10%, checkpoints visibly, and survives a mid-run `kill -9` + restart with resume (no re-fetch storm, audit chain intact) |

## Phase 3 — Per-mode live acceptance (real model, real sources)

For each mode: run it from the **web wizard** exactly as a user would, watch the
trace, review the artifact, export it. Shared standards for every mode: the run
completes without error; the trace shows live steps; confidence band displayed;
zero fabricated citations; export (Markdown + JSON, plus CSV where typed) opens
and matches the artifact.

| Mode | Live scenario | Mode-specific standard |
|------|--------------|------------------------|
| Investigate | "What does recent literature say about GLP-1 cardiovascular outcomes?" (Standard) | Report has ≥ 3 sections with citations; contradictions/open questions listed when present; synthesis streams live in the trace |
| Investigate-Deep | Same question, 1h budget | Exploration tree visible with grounded ●/open ○ badges; woven synthesis reads as a coherent narrative, not stitched fragments |
| Ask | A focused factual question over an ingested corpus | Answer cites real chunks; transcript artifact renders as conversation; skills used recorded per turn |
| Survey | 10+ real papers, columns "sample size" + "methodology" | Table has the user's columns; ≥ 80% of cells filled where the info exists; conflicting values carry ⚠ with the right documents named |
| Reconstruct | An event with contested dates across sources | Timeline ordered correctly; the contested event shows the source split and alternates; certainty matches the actual agreement ratio |
| Decide | 3 options × 4 criteria incl. one "lower = good" | Direction respected in totals; the decisive criterion marked; "What would change this" names a real, checkable factor |
| Adjudicate | A genuinely contested claim + a pasted draft | All four perspectives engage the draft (not the bare claim); agree/dispute split rendered; the verdict's turning point is specific |
| Watch (topic) | A live news topic, 2 polls ≥ 1h apart | Second poll suppresses items from the first (exact + near-duplicate); alerts vs digest split is sensible |
| Watch (website) | A real page with a keyword trigger; then pause it | Verdict ✓/◐/✗ honest for the page; alert fires on a real change, appears in the panel AND landing strip; paused monitor performs zero fetches (verify in egress audit) |
| Digest | After the Watch runs | Rollup readable; items link back to sources |

## Phase 4 — Privacy & security (the falsifiable claims)

| # | Test | How | Standard |
|---|------|-----|----------|
| 4.1 | Airgap kill switch | `LIGHTHOUSE_AIRGAP=1`, run research + notifications + a watch tick while capturing traffic (`tcpdump`/`lsof -i` on the process) | **Zero** outbound packets from Lighthouse processes (localhost Ollama/Qdrant exempt); every refused call appears in the egress audit |
| 4.2 | Egress audit completeness | Normal online run; compare `tcpdump` host list vs `lighthouse audit-egress` | Every external host in the capture appears in the audit log — no unlogged egress. `--summary` names the same hosts in plain English |
| 4.3 | Allowlist enforcement | Add a skill result URL on a non-allowlisted host | Fetch refused before socket open; snippet fallback used; refusal audited |
| 4.4 | Sandbox red-team | `lighthouse sandbox redteam` + a real EICAR file + a JS-laden PDF via the dashboard upload | 100% of hostile fixtures quarantined/rejected, 0 false positives on clean files |
| 4.5 | Injection gauntlet | Ingest documents carrying known prompt-injection strings (incl. unicode homoglyph variants); run research over them | Injected chunks blocked at ingest (counted + surfaced); no injected instruction reflected in any artifact |
| 4.6 | Audit chain tamper | Edit one `audit_events` row by hand; run `lighthouse audit verify` and `doctor` | Verification fails loudly at the edited seq; dashboard History shows the break |
| 4.7 | Secrets handling | Add an API key via Settings on a machine with a keychain; grep all logs/DBs for it | Key in keychain only; never in logs, audit payloads, or exports |

## Phase 5 — Web app UX (the simple-UX standard, live)

Run `scripts/browser_ux_sweep.py` first: **all 9 tabs, zero console errors, no
white screens.** Then a human pass:

| # | Test | Standard |
|---|------|----------|
| 5.1 | Cold-start walkthrough by a non-technical tester | They start a run, find the result, read it, and export it **without help**; every term they stumble on gets logged → Guide/glossary fix |
| 5.2 | Live trace during a Standard run | Steps stream within 2s of occurring; "Writing synthesis…" visibly types; "+N documents" steps appear during acquisition |
| 5.3 | Review → approve flow | Typed artifact view (not flat HTML) on the Review tab; approve/reject round-trips; rejected drafts show the reason |
| 5.4 | Landing strip | With a fired watch alert + an unresolved prediction queued: both appear on the home page without navigation |
| 5.5 | Dark mode + narrow window (≤ 900px) | No unreadable contrast, no layout break, per DoD §3.9 |
| 5.6 | Guide accuracy | Every claim in the Guide tab is demonstrably true in the running app (spot-check all "you'll see…" statements) |

## Phase 6 — Endurance & operations (run last; see docs/RELEASE.md for full runbook)

| # | Test | How | Standard |
|---|------|-----|----------|
| 6.1 | 24h soak | `uv run python scripts/soak.py --hours 24 --load` | No loop death; no monotonic RSS/fd/thread growth; clean shutdown (R5) |
| 6.2 | Disaster recovery | `kill -9` mid-write → restart → `lighthouse integrity` | In-flight jobs marked interrupted, requeued; audit chain verifies; no corrupt DB (R5) |
| 6.3 | Cross-platform service | systemd (Linux) + launchd (macOS) install → reboot | Supervisor auto-starts, serves, survives reboot (R6) |
| 6.4 | Live calibration loop | ≥ 20 predictions resolved over ≥ 1 week of real use | Auto-resolver settles the machine-checkable ones from fresh evidence; "Needs your call" queue works end-to-end; reliability table populates with honest intervals (R8) |
| 6.5 | RAM guardrails | Concurrent research + watch tick on the minimum-spec machine | No OOM, no swap death; admission queue serializes model loads; Pause halts everything within one tick |

---

## Recording the verdict

A phase passes when **every row meets its standard or has a written, justified
exception**. When all six phases pass: update `CAPABILITIES.md` (replace
"validation phase" language with the measured numbers), tick the R-gates in
`docs/PRODUCTION_CHECKLIST.md`, and cut the release per `docs/RELEASE.md`.
Anything that fails goes back through the normal loop — fix, pin with a test,
re-run the phase. **Numbers are recorded as measured, never rounded up.**
