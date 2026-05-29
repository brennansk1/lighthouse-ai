# Federal Register — Planner Guide

## When to use this skill

The Federal Register is the right primary source when the research question
concerns **published federal rulemaking activity**: notices of proposed
rulemaking (NPRMs), final rules, executive orders, proclamations, and other
official agency actions as they appeared in the daily federal journal.

### U.S. federal government family: which skill?

| Research need | Right skill | Why |
|---|---|---|
| Agency notices, proposed rules, final rules, EOs | **Federal Register** | The official publication of record — rule text as published |
| Public comments on proposed rules | **regulations.gov** | The comment portal; distinct from FR publication |
| Codified law in the CFR or U.S. Code | **GovInfo** | Archived authoritative compilations; FR is the raw publication |
| Current bills, votes, committee activity | **Congress.gov** | Legislative (not executive/agency) branch |

**Use Federal Register for:**
- Finding what rules or notices a specific agency has published recently.
- Locating the full text of a proposed rule (NPRM) to read its preamble and
  regulatory text.
- Tracking the rulemaking lifecycle: NPRM → comment period → final rule
  (`track_rulemaking`).
- Retrieving executive orders (``get_executive_orders``) and presidential
  proclamations by date.
- Watching for new publications from a specific agency (``list_recent_in_agency``
  is watchable).
- Reconstructing a regulatory timeline: what did the agency propose and when,
  how did the final rule differ from the NPRM?

**Do NOT use Federal Register for:**
- The codified, current version of a regulation — that lives in the CFR (use
  GovInfo). The Federal Register contains the raw chronological publications;
  CFR compiles them into the current code.
- Public comments filed on proposed rules — those are on regulations.gov.
- Congressional bills, floor votes, or committee reports — use Congress.gov.
- Historical pre-1994 full-text search (the API covers FR since 1994).

---

## Egress requirement

``federalregister.gov`` is NOT on the default Lighthouse platform allowlist.
This skill loads and degrades gracefully (returns ``[]`` with a logged note)
until the user explicitly grants trust:

```
lighthouse trust add federalregister.gov
```

---

## Translating a question into a Federal Register query

1. **Identify the entity.** Is it an agency (e.g. "EPA"), a rule topic
   (e.g. "clean air"), a document type (e.g. "executive order"), or a specific
   document number (e.g. "2024-05678")?
2. **For agency watch.** Use ``list_recent_in_agency(agency_slug)`` with the
   agency's slug (e.g. ``"environmental-protection-agency"``, ``"fda"``).
3. **For topic search.** Use ``search_rules(query)`` with descriptive terms.
4. **For EO retrieval.** Use ``get_executive_orders()`` — no query needed.
5. **For NPRM→final tracking.** Use ``track_rulemaking(topic)`` to see both
   proposed and final rule publications for a topic.

---

## Tool playbook

| Task | How to use | Notes |
|---|---|---|
| Find rules on a topic | `run(ctx, "topic keywords")` | Full-text search across all document types |
| Watch agency for new publications | `run_watchable(ctx, "agency-slug", since=checkpoint)` | Agency slug (e.g. "epa", "fda") |
| Get recent executive orders | Call adapter directly: `get_executive_orders()` | Returns presidential documents |
| Track NPRM→final | Call adapter directly: `track_rulemaking("topic")` | Returns both PRORULE and RULE types |
| Fetch a specific document | Call adapter directly: `fetch_rule("2024-05678")` | Use document number from FR |

### Rulemaking timeline reconstruction (Reconstruct mode)

1. Use `track_rulemaking(topic)` to get both proposed and final rule documents.
2. Order by `publication_date` (ascending) to reconstruct the sequence.
3. Compare the NPRM preamble to the final rule preamble for material changes.
4. Cross-reference with regulations.gov for public comments filed between
   the NPRM and the final rule to understand what drove changes.

---

## Known biases and limitations

1. **Full-text coverage starts 1994.** Earlier Federal Register issues are
   available in scanned form but not full-text searchable via the API.

2. **Publication date ≠ effective date.** Rules are published before they
   take effect (often 30–60 days). The `publication_date` field is the
   *publication* date; check the rule text for the effective date.

3. **Codification lag.** A final rule in the Federal Register is not
   immediately reflected in the CFR. For the current codified version, use
   GovInfo (CFR collection). For the raw publication text and the preamble
   (which the CFR omits), use the Federal Register.

4. **Agency slug format.** The API uses slugs like ``"environmental-protection-agency"``
   for `list_recent_in_agency`. If unsure of the slug, use `search_rules` with
   the agency name in the query to find documents and note the `agency_names`
   field.

5. **No internal cross-linking.** The FR API does not link NPRMs to their
   corresponding final rules. `track_rulemaking` is a heuristic keyword search —
   review manually to confirm the documents are part of the same rulemaking.

---

## Watch mode notes

`run_watchable` calls `list_recent_in_agency(query)` treating the query as an
agency slug and filters client-side by `publication_date > since`. For broad
topic watching (not agency-specific), use `run` in a polling pattern instead.

Typical Watch cadence: daily for active regulatory proceedings, weekly for
general agency monitoring.
