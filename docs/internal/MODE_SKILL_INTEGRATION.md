# Lighthouse — Mode ↔ Skill Integration Specification

> **Purpose.** Define exactly how the seven research modes use the skill framework + source
> recommender + source picker, end to end. This document is the contract between the engine (which
> knows about TTD-DR loops, framing pipelines, discipline gates) and the skill library (which knows
> how to research a particular source well). Every integration decision lives here so that no mode
> reinvents skill consumption, and no future skill needs to be aware of mode internals.
>
> **Companion to:** `SKILL_FRAMEWORK.md` (what a skill is), `MODE_PROCESSES.md` / the seven modes and
> dashboard layout, and the audit roadmap (the tiered fetch policy, faithfulness gate, calibration
> auto-resolver).

---

## 0. The governing principle

**Skills are a property of the corpus, not a property of the mode.**

A mode says *what shape of research to do* (synthesize a report, build a timeline, compare options,
adjudicate a claim). Skills say *where the evidence comes from*. The two compose orthogonally
through one shared interface: the corpus of broker-admitted `Document` objects with skill provenance
in their metadata. If those are kept orthogonal, integration stays simple as the library grows and
new modes are added. If they entangle — if Survey has its own "special" way of using skills that
Investigate doesn't — the surface area multiplies and the architecture collapses.

Three corollaries fall out of this principle and are non-negotiable across the rest of this doc:

1. **One recommender, parameterized by mode.** There is exactly one `recommend(framed_question,
   mode, depth) -> ranked[(skill, score, reason)]` function. Different modes change its scoring
   weights, never its codepath.
2. **One tool runner, one broker, one audit chain.** Whether a skill is invoked from Investigate, Watch,
   or Ask, it executes through the same capability-restricted runner, the same sandbox broker, and
   logs to the same HMAC chain with the same `skill_id` + `skill_version` propagating to every chunk.
3. **The user can always override.** Recommender suggestions are pre-selections, not commitments.
   Mode behavior is the same whether the corpus came from a recommender pick or a manual override.

---

## 1. The three usage patterns

The seven modes don't relate to skills the same way. They cluster into three structurally different
patterns, each with its own integration shape.

### Pattern 1 — Multi-source synthesis
**Modes:** Investigate · Survey · Reconstruct · Decide · Adjudicate

The user picks N skills up front; the dispatcher runs each; the mode synthesizes from the aggregated
corpus. Skill selection happens once per job, before the run begins.

### Pattern 2 — Continuous coverage
**Modes:** Watch

Skills define what's being monitored. The user picks skills as part of a topic configuration; the
Watch worker invokes them on a schedule with `since=last_tick`; results feed dedup → hotness →
reflection/escalation pipeline. Skill selection persists with the topic.

### Pattern 3 — Conversational on-demand
**Modes:** Ask

Skills are available but not pre-committed. The planner decides per-turn which skill (if any) to
call. The user can explicitly pin skills for a session, but it's not required.

These three patterns are the *only* shapes mode-skill integration ever takes. Every new mode added in
the future should fit one of the three; if a proposed mode doesn't, that's a signal to re-examine
either the mode or the framework.

---

## 2. Pattern 1 — Multi-source synthesis

### 2.1 End-to-end flow

```
User submits question on Research tab
    │  ▼
framing/pipeline.py:run_framing(question)  → FramedQuestion(type, frames, sub_questions, load_bearing)
    │  ▼
skills/recommender.py:recommend(framed, mode, depth)  → ranked: list[(skill_id, score, reason, role)]
    │  ▼
UI source picker (Research tab): recommended pre-checked, per-skill tooltip with `reason`,
  user adds/removes, "save as profile" affordance
    │  ▼ user clicks "Approve & Run"
POST /api/jobs { mode, framed_question, depth_tier, selected_skills: [...] }
    │  ▼
dispatcher.py: for skill_id in job.selected_skills: runner.run(load(skill_id), framed, ctx)
  → Documents tagged metadata.skill_id/.skill_version/.fetch_backend  → aggregate into job_corpus
    │  ▼
mode engine (Investigate/Survey/Reconstruct/Decide/Adjudicate) consumes job_corpus, unchanged
    │  ▼
verification/discipline.py:check(artifact, evidence=job_corpus): citation coverage · source
  independence (skill_id+author+domain) · faithfulness (MiniCheck/HHEM) · WEP downgrade (Tier-C,
  community-skill, single-skill claims)
    │  ▼
artifact staged in Library, calibration positions in Track, audit in Activity
```

The mode engine itself never reads `selected_skills`. It only consumes the corpus. This is what
keeps the orthogonality real and what allows the seven modes to share one dispatcher integration
point.

### 2.2 Per-mode affinities (recommender scoring)

Modes don't pick skills, but the recommender knows some skills fit some modes better. This is encoded
as **scoring weights** in the recommender, not branching in the modes. Each skill manifest declares:

```toml
supported_question_types = ["factual_lookup", "comparative", "causal_explanation"]
modes_natural_fit = ["investigate", "survey", "reconstruct"]
modes_weak_fit = ["decide", "adjudicate"]
output_shape = "enumerable"          # lookup | enumerable | graph | stream
temporal_tools = true                # exposes time-ordered queries
perspective_lens = "primary"         # primary | regulatory | reproducibility | popular | ...
grade = "A"                          # academic A / authoritative B / general C
authority = "peer_reviewed"          # independence + Adjudicate diversity
```

Per-mode scoring rules (concrete defaults; tune from telemetry):

- **Investigate** — prefer `grade=A` and `authority=peer_reviewed`. Bonus for primary-source skills
  (arXiv, OpenAlex, PubMed, SEC EDGAR, CourtListener). Penalty for Wikipedia/general-web on
  *load-bearing* sub-questions (acceptable for orientation; weak for citation). Community skills
  excluded entirely when `depth_tier ∈ {thorough, deep}`.
- **Survey** — strongly require `output_shape="enumerable"`. Heavy bonus for `list_*`/`search_*`
  tools returning paginated result sets. Heavy penalty for `lookup` (no corpus to screen).
- **Reconstruct** — strongly require `temporal_tools=true`. Bonus for explicit time-ordered tools.
- **Decide** — *not job-level*. The recommender runs once *per option*, selecting skills relevant to
  evaluating that option; option-level sets are merged with dedup into the job's `selected_skills`.
- **Adjudicate** — *diversity-required*. The recommender picks skills spanning distinct
  `perspective_lens` values so each adversarial perspective has its own evidence base. This is the
  *only* mode where the objective is *diversity* rather than *fit*.

```python
def recommend(framed, mode, depth) -> list[Recommendation]:
    weights = MODE_WEIGHTS[mode]
    candidates = registry.list_skills(allow_community=depth.allows_community)
    if mode == "decide":     return _recommend_per_option(framed, weights)
    if mode == "adjudicate": return _recommend_for_diversity(framed, weights)
    return _recommend_for_fit(framed, candidates, weights)
```

### 2.3 Editable plan before run

The framing pipeline's editable plan now incorporates skill choices. The user sees framing (question
type, frames, sub-questions with load-bearing flags), the recommended/selected sources (checkboxes),
and the depth tier — and can edit framing AND skills in the same step, then approve. This combined
edit is one transaction.

### 2.4 Skill profiles

Saved per-domain preferences (Settings tab): `(domain_pattern, mode, baseline_skills, boosted_skills,
excluded_skills)`. When the recommender runs, matching profiles overlay its output: `baseline` always
pre-selected, `boosted` get a score bonus, `excluded` filtered out. *"For oncology questions, always
include PubMed + ClinicalTrials.gov, boost Cochrane, exclude Wikipedia."*

---

## 3. Pattern 2 — Continuous coverage (Watch)

### 3.1 Flow
Topic form (name, query, cadence, skills filtered to watchable) → `recommend(framed, mode="watch",
depth=quick)` filtered to `watchable=true` skills with ≥1 `@watchable` tool → topic stored
`{topic_id, name, query, cadence, selected_skills, last_tick_at}` → on each tick:
`SchedulerGate.wait_for_capacity()` → for each skill `runner.run_watchable(skill, query,
since=last_tick_at)` → exact+semantic dedup → hotness `ln(mentions+1) + 0.5·distinct_sources +
recency_decay + 2.0·query_hits` → reflections (≤5/tick) vs escalations → Watch tab / Track tab / daily
digest in Library.

### 3.2 Watchable tools
`manifest.toml`: `watchable = true`, `watchable_tools = ["search_recent", "list_filings_since",
"recent_revisions"]`. A `@watchable` tool MUST accept `since: datetime` and return enumerable,
time-ordered results. Lookup-only tools are not watchable. Skills with no watchable tools are filtered
out of Watch's recommendation entirely.

### 3.3 Reusable, not reimplemented
Watch reuses the same library, runner, broker, audit chain. It just *selects* by a different criterion
(watchable) and *invokes* with a different cadence (scheduled, incremental). Adding Watch on top of the
skill machinery requires no parallel codepath — the test of whether the framework is right.

### 3.4 Investigate → Watch lift
If the user runs Investigate ≥4 times in one domain over 30 days, offer to lift it into a standing
Watch, preserving framing, selected skills (filtered to watchable), depth (downshifted to Quick), and
a cadence default. One click.

---

## 4. Pattern 3 — Conversational on-demand (Ask)

### 4.1 Why Ask is different
The user is in a conversation, not at a form (a source picker between question and answer is lethal
friction for a 30-second clarification); and the right skill changes per turn. So Ask uses **implicit
selection by default, explicit pin available**.

### 4.2 Flow
User asks (≥4 words, existing retrieve gate) → background non-blocking `recommend(framed, mode="ask",
depth=quick)` → planner receives ReSum-compacted history + top-3 skills as JSON-schema tools + any
pinned skills → planner decides per turn (skip retrieval / one skill / several sequential) → each
skill call → runner → broker → ingest, scoped to the turn → answer with inline citations + skill
provenance → UI shows a quiet "researched arXiv + PubMed (2.1s)".

### 4.3 Explicit override affordances
- **`/sources`** — slash command; shows ranking, lets the user check/uncheck; *sticky* for the session,
  persisted to the session record.
- **`@<skill>`** — inline directive forcing the next turn to use that skill, even if unrecommended.

### 4.4 ReSum compacts skill history too
Long-session compaction preserves a "research history" (which skills were called, which queries, what
they returned) so the planner doesn't re-call the same skill with the same query.

---

## 5. General Web — the everywhere skill

`skills/library/general_web/` is **always available**, the **universal fallback**, and the **only skill
that searches across the open web** (SearXNG self-hosted by default + trafilatura + politeness + Tier-B
Crawl4AI/Playwright + broker).

### 5.1 Toolkit (each composes platform primitives — no raw `httpx.get()`)
`search_web` · `fetch_url` (Tier-A static) · `fetch_url_js` (Tier-B, opt-in, scheduler-gated) ·
`search_news` · `search_scholar` · `search_images` (URLs+alt-text only) · `search_videos` (hands to
youtube skill) · `expand_query` · `follow_chain`.

### 5.2 Six roles (tracked on `Recommendation.role`)
`primary` · `fallback` · `gap_filler` (CRAG mid-loop fetch for empty sub-questions) · `breadth` ·
`recency` (news; cannot be the sole citation for a load-bearing claim) · `cross_check` (Adjudicate
"popular" lens) · `disambiguator`. The role drives how the discipline gate weights its evidence and
how the UI badges the chunk.

### 5.3 Per-mode use
Investigate (primary when no specialty fits / gap_filler mid-run / breadth) — high-stakes claims
sourced solely from General Web drop one WEP band; Survey (rare primary; targeted gap-filler);
Reconstruct (heavy — news/blog timelines with explicit dates); Decide (per-option popular reception);
Adjudicate (popular lens, role=cross_check); Watch (watchable via `search_news`/`search_web` since=);
Ask (implicit top-3, often disambiguator).

### 5.4 Downgrade rules
(1) single-source General-Web claim → −1 WEP band; (2) Tier-B `fetch_backend="js"` single-source →
additional −1 band; (3) General Web **+** specialty triangulation → **not** downgraded; (4)
`role=recency` → "recency-only" badge, never the sole citation for a load-bearing claim.

### 5.5 Trust controls (Settings)
SearXNG backend (self-hosted default; cloud opt-in audit-tagged); domain allow/blocklist overlay;
Tier-B trigger threshold (default: trafilatura extracts <200 tokens); Tier-C never auto-escalates —
only via `lighthouse trust add <domain> --reason "..."`, `#anti-bot-bypass`-tagged + WEP-downgraded.

---

## 6. Contradiction handling across modes

Multi-source research surfaces contradictions inevitably — that's part of the value.

### 6.1 Three detection layers
1. **Chunk-level** (cheap, always) — discipline gate's `detect_contradictions` heuristic (overlapping
   subject tokens + opposing polarity). Precision-biased.
2. **Claim-level** (medium, Thorough+) — faithfulness model (HHEM-2.1/MiniCheck) flags claims with
   conflicting entailment as *contested*, not asserted true. NLI-grade.
3. **Cross-skill** (deepest, Thorough+ and always in Survey/Reconstruct) — same claim, different
   `skill_id`, opposing scores. Elevated above intra-skill contradiction (independent sources
   disagreeing is a stronger signal).

### 6.2 Per-mode handling
- **Investigate** — `[CONTRADICTION]` markers in the denoised draft; name it with citations to both
  sides; adjudicate within the report when evidence weight is clearly asymmetric; escalate to
  auto-Adjudicate when load-bearing ∧ balanced ∧ Thorough+; leave explicit as a known-unknown at
  Quick/Standard.
- **Survey** — `⚠` cell badges marking contested attributes; PRISMA gains a "discordant findings"
  annotation. Survey surfaces, never arbitrates.
- **Reconstruct** — date conflicts resolved by source-grade-weighted vote; winning date + certainty
  (`winning/total`), losing dates on hover, "disputed date" badge when certainty<0.6; factual
  contradictions split into two cross-referenced entries.
- **Decide** — evidence disagreement feeds *uncertainty bands* into the sensitivity sweep; a robust
  winner survives both weight perturbation AND evidence-disagreement perturbation; crux upgraded.
- **Adjudicate** — contradictions are the *input*; four perspectives built around the contradiction;
  judge names the crux; verdict states what evidence would resolve it.
- **Watch** — cross-source contradictions fire as **escalations**, not reflections.
- **Ask** — stated plainly in the answer; user can `/adjudicate` to escalate the disputed claim.

### 6.3 The contradiction artifact
Every detected contradiction is a first-class object in the audit chain:

```python
@dataclass
class Contradiction:
    contradiction_id: str
    claim: str
    supporting_chunks: list[ChunkRef]       # with skill_id, entailment_score per chunk
    opposing_chunks: list[ChunkRef]
    detection_layer: Literal["chunk", "claim", "cross_skill"]
    severity: Literal["low", "medium", "high"]     # evidence balance + load-bearing status
    detected_at: datetime
    detected_in_job: str
    resolution_status: Literal["unresolved", "weighted", "adjudicated", "deferred"]
    resolution_ref: str | None              # job_id of an Adjudicate run, or "weighted"+breakdown
```

The Track tab gains a *Contradictions* section listing unresolved ones by severity; patterns become
visible across jobs.

### 6.4 Auto-Adjudicate trigger (and only these)
1. `detection_layer="cross_skill"`; 2. claim is `load_bearing=true`; 3. `severity="high"` (balanced
evidence); 4. depth tier Thorough or Deep; 5. user has not disabled auto-Adjudicate. The auto-triggered
run is a sub-job; its crux feeds back into the parent's denoise as a new/reframed sub-question; the
user sees one artifact (verdict embedded as an appendix linking to the full debate trace in Activity).

### 6.5 The single principle
**Surface, don't silently smooth.** Every mode may *resolve* contradictions on principled grounds
(evidence weight, source quality, recency); no mode may *hide* them. "Where did this answer disagree
internally?" must always be answerable with a complete list.

---

## 7. Cross-cutting invariants

1. **Skill provenance flows through everything** — `skill_id`/`skill_version` on every Document →
   chunk → claim audit → artifact provenance manifest.
2. **Skill identity participates in source independence** — the two-source rule now also requires
   distinct skill identity AND distinct first-author/institution where available.
3. **One recommender, mode-parameterized** — no mode implements its own ranking.
4. **One tool runner, one broker, one audit chain.**
5. **The user can always override** — recommendations are pre-selection; profiles overlay; pins
   persist.
6. **Tier escalation is mediated by skills, never bypassed** — only via a skill's declared escalation,
   per-domain trust, `#anti-bot-bypass`-tagged, WEP-downgraded.
7. **Contradictions are surfaced, never silently smoothed** — first-class audit objects.
8. **Watch is the integration canary** — a skill correct under scheduled/incremental/dedup/persistent
   use is almost certainly correct everywhere.

---

## 8. Where the modes' UIs change

| Tab | Change |
|-----|--------|
| **Research** | Source-picker step between framing edit and commit (same component every mode; recommender output differs). Editable plan combines framing + skill edit in one transaction. |
| **Library** | Filter by skill; per-artifact skill badges; per-claim skill provenance on citation hover. |
| **Watch** | Topic form gains a skill selector (watchable-filtered); reflection cards show detecting skill. |
| **Track** | Per-skill calibration (Brier by skill); *Contradictions* section. |
| **Activity** | Skill call graph for a running job; per-skill rate-limit status. |
| **Health** | Per-skill health (budget, last fetch, error rate, robots freshness); Tier-C trust viewer. |
| **Settings** | Skill profiles; community enablement; Tier-C trust editor; General Web backend; auto-Adjudicate per depth tier. |

No tab is added — skills slot into the existing structure. That's the test of whether the integration
is right.

---

## 9. Open work (dependency order)

1. Recommender mode-aware scoring (hand-coded defaults + telemetry instrumentation).
2. General Web skill (the nine tools; each composes platform primitives).
3. Skill profiles (Settings UI + persistence + overlay logic).
4. Contradiction artifact (first-class audit object + lifecycle).
5. Per-mode contradiction handling (denoise markers / cell badges / date reconciliation / sensitivity
   variance / Watch escalation).
6. Auto-Adjudicate trigger (the five conditions wired into the dispatcher).
7. Investigate→Watch lift.
8. Editable plan with skills (Research-tab UI).

1 unblocks 2 and 3; 4 unblocks 5 and 6; the rest are independent. None require restructuring existing
modes — they bolt onto the seams already specified.

*End of mode ↔ skill integration specification.*
