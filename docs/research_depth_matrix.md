# Research output by mode × depth tier

How each research mode's artifact scales across the four depth tiers. This is the
spec the depth wiring (#44) and the Research-tab depth selector (#53) build to.

## The invariant (read this first)

**Depth scales *coverage and confidence*, never *trust*.** The grounding
guarantees hold at **every** tier — even Quick:

- every asserted claim is entailed by a real cited source, or it is dropped/flagged;
- zero fabricated citations (a cited chunk id must exist in the corpus);
- low citation/entailment coverage downgrades the confidence (WEP) band rather
  than asserting.

What changes between tiers is **how much** is covered, **how many** angles are
pursued, and **how hard** each claim is stress-tested — not whether the output
can be trusted. A Quick run is a smaller, honestly-scoped answer; a Professional
run is an exhaustively-decomposed one. Neither bluffs.

## Tier shorthand

| Tier | Wall-clock | Rounds / nodes | Sources pulled | Extra passes |
|------|-----------|----------------|----------------|--------------|
| **Quick** | ~1–3 min | ~2 rounds | few (top-k small) | grounding gate |
| **Standard** | ~5–10 min | ~4 rounds | moderate | + sensitivity / dedup / PRISMA |
| **Exhaustive** | ~20–60 min | ~6 rounds | broad | + adversarial refutation + coverage critic + triangulation |
| **Professional** | hours (user budget) | recursive question-tree, budget-bound | exhaustive | all of the above, applied per tree node; checkpointed/resumable |

> Claude & Gemini deep research time-box to ~10–20 min — roughly our *Standard*.
> *Exhaustive* and *Professional* are depth they structurally cannot reach.

---

## Investigate → report  (most depth-sensitive)

| Tier | What the report looks like |
|------|----------------------------|
| **Quick** | 1–2 sections; a direct top-line answer; a handful of citations; single retrieval pass. Good for "give me the gist, grounded." |
| **Standard** | 3–5 sections (what's established / disputed / unknown); per-claim citations; ~4 rounds of gap-filling; contradictions noted; WEP band per section. |
| **Exhaustive** | Above + sub-questions spawned and resolved; **adversarial refutation** pass (weak claims dropped/flagged contested); **coverage critic** fills missing angles; key claims **triangulated** (≥2 independent sources). |
| **Professional** | Full **recursive question tree** — sub-questions decompose into sub-sub-questions until each leaf is grounded or recorded as a known-unknown. Long structured report, per-node coverage, full **provenance manifest**, runs for hours, checkpointed. The depth a human analyst reaches over days. |

## Ask → transcript

| Tier | What the transcript looks like |
|------|--------------------------------|
| **Quick** | One grounded answer turn with the chunks it used; small top-k; one retrieval. |
| **Standard** | Answer + supporting citations + a couple of caveats/considerations; responsive follow-up ready. |
| **Exhaustive** | Answer decomposed into sub-questions, each independently cited; contradictions and caveats surfaced; refutation pass on the main claim. |
| **Professional** | Multi-turn self-interrogation tree — the system asks and answers its own follow-ups to exhaustion, every turn grounded, ending with explicit known-unknowns. |

## Survey → evidence table (PRISMA)

| Tier | What the table looks like |
|------|---------------------------|
| **Quick** | Screens a slice of the corpus; few attributes; PRISMA identified/included counts. |
| **Standard** | Full PRISMA screen with exclusion reasons; defined attribute set; one cell per (doc × attribute) with citation + entailment flag. |
| **Exhaustive** | Broader screening criteria; more attributes; **dual extraction** verification per cell; cross-doc consistency checks. |
| **Professional** | Exhaustive corpus screen to attribute saturation; inter-document **contradiction flags**; complete PRISMA flow with per-decision provenance. |

## Reconstruct → timeline

| Tier | What the timeline looks like |
|------|------------------------------|
| **Quick** | Main events only, ordered, with sources. |
| **Standard** | Deduped events; date-conflict resolution by weighted vote; per-event certainty + sources. |
| **Exhaustive** | Finer-grained events; actor/action extraction; conflicting accounts surfaced rather than collapsed. |
| **Professional** | Exhaustive event extraction across all documents; sub-timeline decomposition for dense periods; full provenance + certainty per event. |

## Decide → matrix (bounded by options × criteria; *reasoning* depth scales)

| Tier | What the matrix looks like |
|------|----------------------------|
| **Quick** | Every cell scored; weighted totals; winner + margin. |
| **Standard** | + sensitivity sweep (is the winner fragile?); named **crux**; runner-up. |
| **Exhaustive** | + per-cell justification backed by evidence; deeper sensitivity (multi-criterion swings). |
| **Professional** | + each criterion researched as its own mini-investigation (evidence-backed scores, not just judgments); crux handed to **Adjudicate** for a structured debate. |

## Adjudicate → verdict

| Tier | What the verdict looks like |
|------|-----------------------------|
| **Quick** | 2–3 perspectives; a verdict. |
| **Standard** | 4 distinct perspectives; judge summary; named crux of disagreement. |
| **Exhaustive** | More perspectives + rebuttals; evidence weighed per position; refutation of the weakest arguments. |
| **Professional** | Full **debate tree** — claims → rebuttals → counter-rebuttals until the crux is irreducible; every position grounded; verdict states what would change it. |

## Watch → digest (depth = breadth of sources / window, not rounds)

| Tier | What the digest looks like |
|------|----------------------------|
| **Quick** | Latest cycle; top salient items; duplicates suppressed. |
| **Standard** | Digest + alerts split; salience scored; categorized. |
| **Exhaustive** | More sources per cycle; deeper salience scoring; cross-item linking. |
| **Professional** | Long-window / continuous monitoring; cross-source correlation; trend synthesis over many cycles. |

---

## How a user picks this (Research tab, #53)

The wizard exposes a depth selector with the plain-English tiers above. The
**Professional** tier additionally exposes a **budget** (max wall-clock —
30 m / 1 h / 2 h / overnight — or max nodes), because it is otherwise unbounded.
The chosen tier (+ budget) is shown on the Review step and recorded in the
artifact's provenance manifest, so every output says exactly how deep it went.
