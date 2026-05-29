# Research output by mode × depth tier

How each research mode's artifact scales across the four depth tiers. This is the
spec the depth wiring (#44) and the Research-tab depth selector (#53) build to.

## The invariant (read this first — and put it in the UI)

> **Depth scales coverage and confidence, never trust.**

Show this sentence verbatim in the tier-selector tooltip. The grounding
guarantees hold at **every** tier — even Quick:

- every asserted claim is entailed by a real cited source, or it is dropped/flagged;
- zero fabricated citations (a cited chunk id must exist in the corpus);
- low citation/entailment coverage downgrades the confidence (WEP) band rather
  than asserting.

A Quick run produces *less*, with *humbler* confidence bands — it never lies to
go faster. Depth changes how much is covered, how many angles are pursued, and
how hard each claim is stress-tested — not whether the output can be trusted.

## Tier names

Named to match how researchers actually scope work:

| Tier | Mental model |
|------|--------------|
| **Quick** | "I need an answer in the next minute." |
| **Standard** | "I'm taking a coffee break." |
| **Thorough** | "I'm doing this properly." |
| **Deep** | "This is going overnight; I'll review it tomorrow." |

(`Deep` is the industry term Claude/Gemini have trained users on — we co-opt it
and deliver more than a time-boxed run can. Names are display-layer only.)

## Tier shorthand

| Tier | Wall-clock (T2 reference · 24 GB M4) | Rounds / nodes | Sources | Extra passes |
|------|--------------------------------------|----------------|---------|--------------|
| **Quick** | ~1–3 min | ~2 rounds | few (top-k small) | grounding gate |
| **Standard** | ~5–10 min | ~4 rounds | moderate | + sensitivity / dedup / PRISMA |
| **Thorough** | ~20–60 min | ~6 rounds | broad | + adversarial refutation + coverage critic + triangulation |
| **Deep** | hours (**required** budget) | recursive question-tree, budget-bound | exhaustive | all of the above, per node; checkpointed/resumable |

*Times scale with hardware tier; the `doctor` command reports your machine's
actual measured wall-clock per tier after the first run. The table is a T2
(24 GB M4) reference, not a guarantee on other hardware.*

> Claude & Gemini deep research time-box to ~10–20 min ≈ our **Standard**.
> **Thorough** and **Deep** are depth they structurally can't reach.

### The Deep tier requires a committed budget (hard gate)

Exposing a budget isn't enough — the Governor **refuses to start** a Deep run
without one. The framing step shows an explicit contract:

- *"This will run for up to **X** (30 m / 1 h / 2 h / overnight) or **N** nodes.
  Confirm."*
- Power policy surfaced here too: *"This run pauses if you go off AC power"* (or
  *"continues on battery — confirm"*), enforced by the SchedulerGate.

The committed budget + power policy are written into the artifact's provenance
manifest. This is the contract between user and machine for the one tier that
could otherwise run away (walk away → come back to a melted machine and a
half-finished tree). No budget, no Deep run.

---

## Investigate → report  (most depth-sensitive)

| Tier | What the report looks like |
|------|----------------------------|
| **Quick** | 1–2 sections; a direct top-line answer; a handful of citations; single retrieval pass. "Give me the gist, grounded." |
| **Standard** | 3–5 sections (established / disputed / unknown); per-claim citations; ~4 rounds of gap-filling; contradictions noted; WEP band per section. |
| **Thorough** | Above + sub-questions spawned and resolved; **adversarial refutation** (weak claims dropped/flagged contested); **coverage critic** fills missing angles; key claims **triangulated** (≥2 independent sources). |
| **Deep** | Full **recursive question tree** — sub-questions decompose into sub-sub-questions until each leaf is grounded or recorded as a known-unknown. Long structured report, per-node coverage, full **provenance manifest**, runs for the committed budget, checkpointed. The depth a human analyst reaches over days. |

## Ask → transcript

| Tier | What the transcript looks like |
|------|--------------------------------|
| **Quick** | One grounded answer turn with the chunks it used; small top-k; one retrieval. |
| **Standard** | Answer + supporting citations + a couple of caveats; responsive follow-up ready. |
| **Thorough** | Answer decomposed into sub-questions, each independently cited; contradictions and caveats surfaced; refutation pass on the main claim. |
| **Deep** | Multi-turn self-interrogation tree — the system asks and answers its own follow-ups to exhaustion, every turn grounded, ending with explicit known-unknowns. |

## Survey → evidence table (PRISMA)

The user defines the columns (attributes); the system never silently drops them.

| Tier | What the table looks like |
|------|---------------------------|
| **Quick** | Screens a slice of the corpus; extracts the user's columns but **defers** lower-priority ones (cells marked `deferred — re-run deeper`); PRISMA identified/included counts. The user's columns are never dropped, only deferred-and-flagged. |
| **Standard** | Full PRISMA screen with exclusion reasons; **all** requested attributes extracted; one cell per (doc × attribute) with citation + entailment flag. |
| **Thorough** | Broader screening criteria; **dual extraction** verification per cell; cross-doc consistency checks. |
| **Deep** | Exhaustive corpus screen to attribute saturation; inter-document **contradiction flags**; complete PRISMA flow with per-decision provenance. |

## Reconstruct → timeline

| Tier | What the timeline looks like |
|------|------------------------------|
| **Quick** | Main events only, ordered, with sources. |
| **Standard** | Deduped events; date-conflict resolution by weighted vote; per-event certainty + sources. |
| **Thorough** | Finer-grained events; actor/action extraction; conflicting accounts surfaced rather than collapsed. |
| **Deep** | Exhaustive event extraction across all documents; sub-timeline decomposition for dense periods; full provenance + certainty per event. |

## Decide → matrix  (bounded by options × criteria; *reasoning* depth scales)

| Tier | What the matrix looks like |
|------|----------------------------|
| **Quick** | Every cell scored, but cells may use **heuristic shortcuts** (planner prior knowledge / cached evidence from prior runs), each such cell **flagged** so the basis is visible; weighted totals; winner + margin. |
| **Standard** | Every cell has **fresh retrieval**; sensitivity sweep (is the winner fragile?); named **crux**; runner-up. |
| **Thorough** | + per-cell justification backed by evidence; deeper sensitivity (multi-criterion swings). |
| **Deep** | + each criterion researched as its own mini-investigation (evidence-backed scores, not just judgments); crux handed to **Adjudicate** for a structured debate. |

## Adjudicate → verdict  (minimum tier: Standard)

A two- or three-perspective "debate" produces the *appearance* of considering
both sides without the discipline that makes Adjudicate work (steelman /
devil's-advocate / base-rate / fragility). A perfunctory adjudication is worse
than none — it legitimizes a decision instead of stress-testing it. So
**selecting Adjudicate lifts the minimum tier to Standard** (no Quick Adjudicate).

| Tier | What the verdict looks like |
|------|-----------------------------|
| **Quick** | *(unavailable — auto-promoted to Standard)* |
| **Standard** | 4 distinct perspectives (steelman / devil's-advocate / base-rate / fragility); judge summary; named crux of disagreement. |
| **Thorough** | More perspectives + rebuttals; evidence weighed per position; refutation of the weakest arguments. |
| **Deep** | Full **debate tree** — claims → rebuttals → counter-rebuttals until the crux is irreducible; every position grounded; verdict states what would change it. |

## Watch → digest  (depth = source/window breadth, not rounds)

Watch's tiers operate on a different axis, so the **selector relabels itself**
when Watch is chosen — same four tiers, contextual labels (hide the complexity,
don't footnote it):

| Tier | Selector label when mode = Watch |
|------|----------------------------------|
| **Quick** | "Last cycle, top items" |
| **Standard** | "Full digest (alerts + items, categorized)" |
| **Thorough** | "Wider sources, cross-linking" |
| **Deep** | "Continuous monitoring with trend synthesis" |

---

## Picking the tier (Research tab, #53)

- The selector is **visible** with the plain-English tiers above, and defaults to
  **Auto** (#54): the framing pipeline's question-type classification picks a
  sensible tier so routine work needs no decision —
  `factual_lookup → Quick`, `comparative / decision_support → Standard`,
  `controversy_resolution / methodology_evaluation → Thorough`, explicit
  "overnight" framing → Deep. The user can always override.
- For mode = Watch, the selector shows the contextual labels above.
- For mode = Adjudicate, Quick is disabled (min tier Standard).
- For the **Deep** tier, a budget commitment is **required** before launch.
- Every artifact's Library footer shows its provenance compactly, e.g.
  `Investigate · Standard · 7m22s · qwen3:14b-Q4` — so any reader (the
  researcher, an editor, an IRB reviewer, opposing counsel) can immediately
  calibrate how much weight to give it. The audit story, made visible at the
  artifact level.
