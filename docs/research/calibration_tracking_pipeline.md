# Calibration & Prediction-Tracking Pipeline ("Track")

> **Purpose of this document.** This is a self-contained design brief for an
> external research agent. The task is to evaluate whether Lighthouse's
> prediction-tracking / self-calibration approach is sound and best-in-class, and
> to propose improvements. It assumes **no access to the codebase** — all context
> needed to assess the design is included here. The open research questions are in
> §9. File paths are given for traceability but are not required to follow the
> argument.

---

## 1. What Lighthouse is (context)

Lighthouse is a **local-first AI research instrument**. A user asks a question; it
picks a research mode and sources, runs grounded research entirely on the user's
own hardware (a local LLM via Ollama + a retrieval stack — no cloud, nothing
leaves the machine), and produces a **cited artifact** (report / evidence table /
timeline / decision matrix / verdict). Its core value proposition is **trust**:
honest, cited, *calibrated* research from a small local model, beating frontier
cloud tools on trustworthiness rather than raw capability.

"Calibrated" is the feature this document is about. The **Track** tab is where the
system grades its own past predictions against reality so the user can judge how
much to trust its stated confidence.

## 2. The problem being solved

Every Lighthouse answer carries a confidence (shown as a "Weight of Evidence"
band — *remote / unlikely / even chance / likely / almost certain*). A confidence
number is only meaningful if it is **calibrated**: when the system says "70%
likely," that class of claim should come true ~70% of the time. Most AI tools
state confidence and never verify it. Lighthouse's bet is that a tool which
**records falsifiable predictions, later checks them, and publishes its own
calibration error** earns trust that frontier chatbots can't.

So the design question this doc poses: **is the chosen mechanism for recording,
resolving, and scoring predictions the right one — statistically, and for a
local-first/offline setting?**

## 3. The data model — a "prediction" (internally a "position")

Stored in a SQLite table `positions` (DB file `positions.db`). One row per
prediction (source: `src/lighthouse_ai/verification/positions.py`):

| Field | Type | Meaning |
|---|---|---|
| `id` | int | primary key |
| `claim` | text | a specific, checkable statement extracted from a research run |
| `wep_band` | text | the confidence band (see §4) |
| `confidence` | float [0,1] | the stated probability the claim is true |
| `resolve_by` | ISO datetime | deadline by which the outcome should be knowable (default = recorded + **90 days**) |
| `resolution_criterion` | text \| null | optional machine-checkable description of what makes the claim TRUE/FALSE |
| `outcome` | bool \| null | set when resolved; `null` = still open |
| `resolved_at` | datetime \| null | when it was decided |
| `brier` | float \| null | the per-prediction calibration error (see §6), set on resolution |

## 4. Confidence → band mapping ("WEP" bands)

`band_for_probability(p)` buckets a probability into one of five bands
(`src/lighthouse_ai/verification/wep.py`):

| Band | Probability range | UI phrase |
|---|---|---|
| remote | 0.00 – 0.10 | "remote" |
| unlikely | 0.10 – 0.40 | "unlikely" |
| even | 0.40 – 0.60 | "even chance" |
| likely | 0.60 – 0.90 | "likely" |
| almost_certain | 0.90 – 1.00 | "almost certain" |

These bands are also what drives the red→green confidence bar shown on every
artifact.

## 5. Where predictions come from (auto-recorded)

Predictions are **not** entered by the user; research runs emit them when they
make a substantive claim. Current emitters:

- **Investigate** (`pipeline.py:_record_positions`): each extracted claim from the
  report becomes a position. **The probability is currently a fixed heuristic:
  `0.75` if the claim is sourced (has citations), `0.5` if unsourced.** No
  `resolution_criterion` is set, so the 90-day default deadline applies.
- **Decide** (`modes/decide.py`): the chosen option's win-probability becomes a
  position.
- **Survey** (`modes/survey.py`): the headline claim, at a fixed `probability=0.7`.

## 6. Resolution & scoring

### Lifecycle
1. **Recorded → Open.** A run inserts a row with claim + probability + resolve_by
   (+ optional criterion). It shows under the Track tab's **Open** list.
2. **Resolution attempt.** A background **resolver loop** runs in the supervisor
   (`_start_resolver_loop`, cadence **once per hour / 3600 s**; only active when a
   real LLM backend is available). For each position **past its `resolve_by`
   deadline** it calls `attempt_auto_resolve`.
3. **Decided.** If resolved, `outcome` (true/false), `resolved_at`, and `brier`
   are written; it moves to the **Decided** list.

### How `attempt_auto_resolve` works (`src/lighthouse_ai/verification/resolver.py`)
- `classify_resolution_kind(claim)` labels the claim **"machine"** (a yes/no claim
  with a measurable outcome) or **"human"** (subjective/undecidable). Human-only
  claims, or any claim when no gateway is available, are **deferred** (left open
  for a person to decide).
- For machine-resolvable claims it asks the **local LLM** (the small `aux_context`
  role) a fixed prompt: *"Based on current knowledge, has this claim turned out to
  be TRUE or FALSE? Respond TRUE/FALSE/UNCERTAIN: <confidence 0–1> — <rationale>."*
- The response is parsed to `(outcome, confidence, rationale)`. If `outcome` is
  UNCERTAIN **or** the LLM's resolution-confidence is below a threshold, it is
  **deferred** (stays open). Otherwise the outcome is accepted.

### Scoring — the Brier score (`src/lighthouse_ai/verification/brier.py`)
On resolution, the per-prediction error is:

```
brier = (probability − outcome)²      # outcome ∈ {0,1}
```

Lower is better; range [0,1]. A pure 50/50 hedge always scores 0.25. The Track
tab's headline "accuracy score" is the **mean Brier across decided predictions**
(lower = better-calibrated). The UI also derives an **outcome-rate-per-band**
("of the claims it called ~70% likely, how many came true?") — the empirical
calibration curve.

## 7. Infrastructure / integration points

- **Storage:** `positions.db` (SQLite), columns added idempotently at first use
  (race-safe ALTERs).
- **Resolver loop:** a daemon thread in the supervisor, hourly, honoring the
  global Pause and only acting when a real backend is present (offline =
  everything stays Open).
- **API/UI:** `GET /api/positions` feeds the **Track** tab (Open / Decided lists +
  a calibration-over-time chart). Predictions are recorded automatically by
  research runs; the user does not create them.
- **Determinism:** `datetime.now()` is only called inside function bodies (never
  at import) and is injectable, so deadlines/resolution are testable.

## 8. Known limitations & design tensions (be skeptical of these)

1. **Self-resolution is circular.** The same family of local LLM that *made* the
   claim also *resolves* it, "based on current knowledge" — i.e. from the model's
   own parametric memory, with **no independent ground truth, no fresh retrieval,
   no external data**. A model confidently wrong at claim time may be confidently
   wrong at resolve time, inflating apparent calibration. (Note: the resolver was
   intended to "re-research" the claim; today it only asks the model.)
2. **Probabilities are fixed heuristics, not model-derived.** Investigate uses
   0.75 (sourced) / 0.5 (unsourced); Survey uses 0.7. The "confidence" being
   calibrated is therefore mostly a constant, which makes the calibration exercise
   close to vacuous — there is little probability variation to calibrate.
3. **Resolution criteria are usually empty.** Without a machine-checkable
   `resolution_criterion`, "has this turned out true?" is left to the LLM's
   judgement, which is exactly the circularity in (1).
4. **Long, fixed horizon.** A 90-day default means almost everything is Open for
   months; calibration statistics are sparse for a long time, and a single user
   may never accumulate enough resolved predictions for a stable Brier estimate.
5. **Brier alone is a limited calibration measure.** It conflates calibration and
   resolution (discrimination); it does not by itself produce a reliability
   diagram, and the small-sample, low-variance probabilities make it noisy.
6. **Binary outcomes only.** Many research claims are not cleanly true/false.
7. **No human-in-the-loop workflow** for the "human"-classified predictions beyond
   leaving them Open.

## 9. Research questions for the evaluating agent

Please assess the design above against the literature and best practice, and
recommend concrete improvements that fit the constraints in §10. Specifically:

1. **Is LLM self-resolution defensible?** What is the prior art on using an LLM to
   grade its own (or another model's) past predictions? How do you obtain
   *independent* ground truth in a local-first setting (re-retrieval, web sources,
   user confirmation, deferred external checks)? What does the forecasting/AI-eval
   literature (Brier, Tetlock/GJP, Metaculus, PredictionBook, calibration of LLMs,
   reliability diagrams, proper scoring rules) say about doing this well?
2. **How should the probability be derived** instead of fixed 0.75/0.5? (e.g.
   evidence-strength → probability, model-elicited probabilities with known
   over/under-confidence corrections, ensembling, conformal methods.) What makes a
   *meaningful* probability to calibrate?
3. **Best scoring/representation:** Brier vs. logarithmic score vs. calibration
   curves / reliability diagrams / ECE; how to present calibration honestly with
   few samples (confidence intervals, Bayesian shrinkage, pooling across users
   without leaving the machine?).
4. **Resolution mechanism:** how to make `resolution_criterion` reliably
   machine-checkable; when to defer to a human; how to schedule horizons (not a
   fixed 90 days); how to re-research at resolution time using real sources rather
   than parametric memory.
5. **Is "tracking your own predictions" even the right trust primitive** for a
   local research tool, or is there a better-grounded way to convey and verify
   confidence (e.g. evidence-based confidence with provenance, adversarial
   verification, calibration on held-out labeled benchmarks rather than
   open-world claims)? Compare alternatives.
6. **Cold-start:** how to give the user a credible calibration signal early, before
   many predictions have resolved (e.g. backtest on a labeled benchmark set,
   per-mode priors, transfer from public calibration data).

Deliver: an assessment of whether the current approach is sound, the strongest
specific risks, and a prioritized set of concrete changes (with prior-art
citations) that would make Lighthouse's self-calibration genuinely trustworthy.

## 10. Hard constraints any proposal must respect

- **Local-first / offline-capable.** Nothing leaves the user's machine by default;
  no required cloud calls, no sending the corpus or predictions to a server. A
  proposal may *optionally* use the internet for resolution (the tool already
  fetches public sources), but must degrade gracefully offline.
- **Small local model.** Reasoning runs on a quantized local LLM (e.g. an 8–14B via
  Ollama), RAM-budgeted — not a frontier model. Resolution must be cheap.
- **Deterministic + testable.** No nondeterminism at import; time is injectable.
- **Single-user, single-machine** by default (no shared prediction market), though
  privacy-preserving pooling ideas are welcome as options.
- **Additive, graceful.** Must fit the existing architecture (SQLite `positions`
  table, hourly resolver loop, `/api/positions` + the Track tab) and never block or
  crash a research run if calibration fails.

---

## 11. Scoping decisions (answers to the evaluator's questions)

1. **Primary deliverable = a prioritized improvement memo**, *not* a full redesign
   spec. Lead with an assessment ("is this sound?") and a ranked list of concrete
   changes with citations. **However**, give **implementer-ready depth on the top
   ~3 recommendations**: proposed schema deltas + algorithm/pseudocode for those,
   enough to hand straight to an engineer. Don't spec a full redesign of
   everything up front — go deep only where the ranking says it matters most.

2. **Weighting: academic-led (~60%), practitioner/rationalist (~40%), both
   required.** Use peer-reviewed CS/stats as the authoritative backbone for the
   methodological core — proper scoring rules, LLM calibration & overconfidence,
   conformal prediction, reliability diagrams / ECE, isotonic & Platt
   recalibration. Use the forecasting-practitioner / rationalist corpus
   (Metaculus, PredictionBook, GJP/Tetlock applied threads, scoring-rule debates)
   for the **operational, UX, cold-start, and motivation** layer — how
   prediction-tracking is actually made usable and honest in practice. When the
   two conflict: **academic wins on methodology, practitioner wins on usability.**
   Tetlock/Good-Judgment work is in scope on both sides and should be used.

3. **The binary-outcome constraint (§8.6) is OPEN to revision.** Evaluate moving to
   **numeric / distributional / multi-outcome** forecasts (continuous-quantity
   questions with a predicted distribution, multi-class resolution), since most
   research claims are matters of degree, not true/false. Binary was an
   implementation simplification, not a principle. **Constraints on any richer
   scheme:** keep **binary true/false as a first-class, cheap simple case**;
   propose a **staged path** to richer outcomes; and it must stay cheap for a small
   local model and degrade gracefully offline (§10). Do not force every claim into
   a full distribution.

---

*Source-of-truth files (for an implementer, not the evaluator):*
`verification/positions.py` (data model + record), `verification/wep.py` (bands),
`verification/brier.py` (score), `verification/resolver.py` (auto-resolution),
`pipeline.py:_record_positions` + `modes/{decide,survey}.py` (emitters),
`supervisor.py:_start_resolver_loop` (cadence), `web/api.py` `/api/positions` +
`web/static/app-pages-redesign.jsx` TrackPage (UI).
