# ClinicalTrials.gov — Planner Guide

## When to use this skill

ClinicalTrials.gov is the right primary source when the research question
concerns **registered clinical trials**: whether a trial exists, what endpoints
it pre-registered, how its design changed over time, and which trials are
actively enrolling for a given condition or drug.

### Clinical wedge: PubMed vs ClinicalTrials.gov vs WHO

| Unit of research | Right skill | Why |
|---|---|---|
| Published biomedical papers | **PubMed** | Peer-reviewed results, abstracts, MeSH-indexed |
| Registered clinical trials | **ClinicalTrials.gov** | Protocol records, endpoints, amendments, enrollment status |
| Cross-country health indicators | **WHO** | Population-level surveillance, ICD codes, outbreak data |

**Use ClinicalTrials.gov for:**
- Finding whether a specific drug, device, or intervention has been tested in a
  registered trial, and if so, the NCT ID (authoritative identifier).
- Extracting **pre-registered primary and secondary endpoints** — comparing
  these to what a published paper reports is the primary method for detecting
  outcome-switching.
- Tracing the **amendment history** of a trial (sponsor, design, eligibility
  changes) — critical for Reconstruct mode on contested trials.
- Listing all active or completed trials for a condition (`list_trials_by_condition`)
  — watchable so new registrations can be tracked.
- Identifying the **trial phase** (I/II/III/IV), **enrollment count**, and
  **sponsor** before diving into PubMed for the results papers.

**Do NOT use ClinicalTrials.gov for:**
- Full results or statistical analyses — those live in the published papers
  (PubMed, OpenAlex). ClinicalTrials.gov contains brief results summaries but
  not full statistical tables.
- Population-level disease burden or prevalence data (use WHO or PubMed).
- Historical epidemiology before the registry era (pre-2000 for most conditions).

---

## Egress requirement

``clinicaltrials.gov`` is NOT on the default Lighthouse platform allowlist.
This skill loads and degrades gracefully (returns ``[]`` with a logged note)
until the user explicitly grants trust:

```
lighthouse trust add clinicaltrials.gov
```

---

## Translating a question into a ClinicalTrials.gov query

1. **Identify the entity.** Is it a condition (e.g. "type 2 diabetes"), a drug
   (e.g. "semaglutide"), an NCT ID (e.g. "NCT04668625"), or a sponsor?
2. **Use the entity directly as `query`.** The v2 API ``query.term`` is a
   full-text search across all structured fields.
3. **NCT ID lookup.** If you have an NCT ID, pass it as the query — the API
   returns the exact record.
4. **Condition + phase.** Combine: "type 2 diabetes phase 3" to narrow results
   to the most clinically relevant trials.

---

## Tool playbook

| Task | How to use | Notes |
|---|---|---|
| Find trials for a condition | `run(ctx, "condition name phase 3")` | Returns up to `max_results` trials |
| Look up a specific trial | `run(ctx, "NCT04668625")` | NCT ID in query returns that record |
| Watch for new trial registrations | `run_watchable(ctx, "condition", since=checkpoint)` | Filters by `start_date` |

### Outcome-switching detection

When a PubMed paper for a trial reports different outcomes from those in the
ClinicalTrials.gov record:

1. Use `run(ctx, nct_id)` to fetch the protocol record (check `primary_outcome`
   and `secondary_outcome` in the raw JSON).
2. Compare the pre-registered endpoints to the published paper's primary
   outcome.
3. Divergences require explicit documentation in your output; this is a
   high-stakes claim requiring clear sourcing from both records.

### Amendment chronology (Reconstruct)

ClinicalTrials.gov v2 records include a `protocolSection.statusModule.lastUpdateSubmitDate`
and archived versions in some cases. For deep amendment tracking the v2 history
endpoint provides the full modification log. Use this for Reconstruct-mode
investigations of trial conduct.

---

## Known biases and limitations

1. **U.S.-heavy but international.** Most trials registered under
   ``ClinicalTrials.gov`` are U.S.-sponsored, but international registration is
   common. For non-U.S. trials, also check EU Clinical Trials Register (EUDRACT,
   not a v1 skill) and the WHO ICTRP.

2. **Results summaries are incomplete.** The "results" fields in ClinicalTrials.gov
   records are brief and often missing. Always pair with PubMed for published
   results.

3. **Terminated trials may have sparse records.** Trials that were stopped early
   often have incomplete endpoint reporting. Document this in output.

4. **Query relevance.** The v2 ``query.term`` is full-text but has no semantic
   expansion. Use MeSH terms from PubMed as hints for precision queries.

5. **Grade A, but verify amendments.** The protocol record is authoritative for
   what was *registered*; it does not guarantee that the trial was conducted as
   registered. Cross-reference with the paper for discrepancies.

---

## Watch mode notes

`run_watchable` uses `start_date` as the temporal filter — new registrations
will have a start date after the Watch checkpoint. This is an approximation;
actual registration date (``firstSubmitDate``) is available in the raw record
and may be preferable for strict "newly registered since X" semantics.

Typical Watch cadence: weekly for active conditions, daily for fast-moving
trials (e.g. emergency use authorization reviews).
