# regulations.gov — Planner Guide

## When to use this skill

regulations.gov is the right primary source when the research question concerns
**public participation in federal rulemaking**: the administrative record for a
specific rulemaking (the docket), the public comments filed on proposed rules,
and tracking when agencies advance active proceedings.

### U.S. federal government family: which skill?

| Research need | Right skill | Why |
|---|---|---|
| Agency notices, proposed rules, final rules, EOs | **Federal Register** | The official publication of record |
| Public comments on proposed rules | **regulations.gov** | The comment portal — distinct from FR publication |
| Codified law in the CFR or U.S. Code | **GovInfo** | Archived authoritative compilations |
| Current bills, votes, committee activity | **Congress.gov** | Legislative branch |

**Use regulations.gov for:**
- Finding who commented on a proposed rule and what they said (public participation
  record — essential for administrative law research).
- Fetching the complete administrative record (docket) for a rulemaking, including
  supporting analyses, correspondence, and meeting transcripts.
- Tracking when an agency advances a docket (new documents posted) using
  `track_docket_activity` (watchable).
- Identifying what industries, advocacy groups, and individuals submitted comments
  and characterizing the range of public views.
- Researching lobbying and regulatory capture: which entities filed comments,
  and what did they ask for relative to the final rule?

**Do NOT use regulations.gov for:**
- The full text of the published rule — that's in the Federal Register.
- The codified, current regulation — use GovInfo (CFR collection).
- Congressional bills or committee hearings — use Congress.gov.
- Comments are grade B (unverified third-party submissions). Treat them as
  primary evidence of public views, not authoritative statements of fact.

---

## Egress requirement

``api.regulations.gov`` is NOT on the default Lighthouse platform allowlist.
This skill loads and degrades gracefully (returns ``[]`` with a logged note)
until the user explicitly grants trust:

```
lighthouse trust add api.regulations.gov
```

An API key from https://open.gsa.gov/api/regulationsgov/ is also required.

---

## Translating a question into a regulations.gov query

1. **Identify the docket.** Most questions are about a specific rulemaking.
   The docket ID format is ``AGENCY-HQ-OFFICE-YEAR-NNNN`` (e.g.
   ``"EPA-HQ-OAR-2023-0072"``).
2. **Topic search.** If you don't have a docket ID, use `search_dockets(topic)`
   to find dockets by keyword.
3. **Comment listing.** Once you have a docket ID, use `list_comments(docket_id)`
   to retrieve comments.
4. **Docket tracking.** For Watch mode, use `track_docket_activity(docket_id)`
   to monitor when new agency documents are posted.

---

## Tool playbook

| Task | How to use | Notes |
|---|---|---|
| Find dockets on a topic | `run(ctx, "topic keywords")` | Searches docket titles |
| Watch docket for new agency documents | `run_watchable(ctx, "DOCKET-ID", since=checkpoint)` | Tracks agency document posts |
| Fetch a specific docket | Call adapter: `fetch_docket("DOCKET-ID")` | Full docket metadata |
| List public comments | Call adapter: `list_comments("DOCKET-ID")` | Grade B — unverified |

### Regulatory capture / lobbying research

1. Use `search_dockets(agency + " " + topic)` to find the docket.
2. Use `list_comments(docket_id, max_results=50)` to get comments.
3. Characterize commenters by `metadata["title"]` — is the docket dominated
   by one industry? Compare to the final rule in the Federal Register.
4. Note any discrepancy between what major commenters asked for and what the
   final rule provided.

### Adjudicate mode: "did agency X consider public opposition?"

1. Fetch comments opposing the rule via `list_comments`.
2. Fetch the final rule preamble via the Federal Register skill.
3. Search the preamble for how the agency addressed the objections.
4. The administrative record (docket) is the evidence base for APA compliance.

---

## Known biases and limitations

1. **Comments are grade B.** Public comments are unverified. Anyone can file a
   comment. Mass comment campaigns (identical or near-identical text) are common
   and do not represent independent views. Flag mass comments in output.

2. **Docket completeness varies.** Some agencies upload supporting analyses and
   correspondence; others are sparse. The absence of documents in a docket does
   not mean the agency didn't consider them.

3. **API key required.** Without an API key the rate limit is very low
   (1,000/hour unauthenticated). For research at scale, register a key.

4. **Search scope.** `search_dockets` searches docket titles, not full document
   text. For topic-based discovery also check the Federal Register.

5. **Comment text truncation.** Long comments may be truncated in the API
   response; the full text is available via the document URL.

---

## Watch mode notes

`run_watchable` calls `track_docket_activity(query)` treating the query as a
docket ID and filters by `posted_date > since`. This tracks when the **agency**
posts new documents (not public comments). To watch for new comments, use
`list_comments` in a polling pattern.

Typical Watch cadence: daily for active rulemakings with open comment periods,
weekly for dormant dockets.
