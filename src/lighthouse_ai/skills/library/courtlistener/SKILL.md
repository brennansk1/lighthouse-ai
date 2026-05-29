# CourtListener / RECAP — Planner Guide

## When to use this skill

CourtListener is the right primary source for **U.S. court opinions, PACER docket
activity, oral arguments, and citation relationships**.  It is operated by the
**Free Law Project** — a 501(c)(3) nonprofit — and indexes the largest free
collection of U.S. legal materials.

**Use CourtListener for:**
- Finding federal circuit and district court opinions on a legal question.
- Researching the history of a party across federal courts.
- Identifying how a landmark case has been cited or interpreted since its decision.
- Tracking new filings in an ongoing case (Watch mode via `track_docket`).
- Retrieving oral argument audio for federal appeals.
- Investigative journalism on federal litigation patterns.
- Policy analysis of how federal courts have ruled on a regulatory area.

**Do NOT rely on CourtListener for:**
- **State court opinions** — coverage varies significantly by state.  Many states
  are partially indexed; some are not indexed at all.  For state case law, use
  the state court's own public access portal.
- **Westlaw/Lexis-grade citation treatment** — `get_citation_treatment` is
  approximate. It will miss citations from unpublished opinions, lightly-indexed
  state courts, and very recent filings.  Do not use it as the sole basis for
  "this case is still good law" determinations.
- **Full docket sheets with all filing text** — CourtListener's RECAP collection
  covers documents that have been uploaded by PACER users.  Not every filing
  in a docket is in RECAP.
- **Supreme Court oral arguments with transcripts** — SCOTUS publishes its own
  transcripts; CourtListener links to audio but the shared transcript pipeline
  returns ``None`` for most audio references in v1.

---

## Federal vs. state coverage

| Court tier | Coverage |
|---|---|
| U.S. Supreme Court | Comprehensive (all opinions from founding) |
| U.S. Circuit Courts of Appeal | Strong (12 circuits, nearly complete) |
| U.S. District Courts | Good; gaps in older and sealed filings |
| Bankruptcy Courts | Partial; RECAP-sourced |
| State Supreme Courts | Varies widely by state |
| State Appellate Courts | Thin or absent for many states |
| State Trial Courts | Rarely indexed |

Always caveat results for state courts with "coverage may be incomplete."

---

## Citation treatment caveat

`get_citation_treatment` performs approximate Shepardizing using CourtListener's
citation graph.  **This is NOT a substitute for Westlaw KeyCite or Lexis
Shepard's Citations.**  The citation graph is built from the documents in
CourtListener's index; gaps exist for:
- Opinions not yet in CourtListener's database.
- Unpublished opinions (though many are now indexed via RECAP).
- Recent filings from the past few weeks (processing lag).
- State court opinions outside CourtListener's current coverage.

For load-bearing legal determinations (e.g. "Is this precedent still good law?")
always corroborate with a paid citation service or the court's own records.

---

## Translating a question into a CourtListener query

The CourtListener API supports Boolean operators and phrase search:

| Goal | Query form | Example |
|---|---|---|
| Keyword / concept | `keyword` | `Fourth Amendment unreasonable search` |
| Phrase search | `"phrase in quotes"` | `"qualified immunity" police` |
| Boolean AND | `term1 AND term2` | `ADA AND disability AND employment` |
| Boolean OR | `term1 OR term2` | `Chevron OR "major questions doctrine"` |
| Docket number | `docket_number:...` | `docket_number:1:23-cv-04567` |
| Party name | `party_name` | `Google LLC` |
| Citation lookup | `cites:"citation"` | `cites:"410 U.S. 113"` |

Use the `list_dockets_for_party` tool for party-centric research rather than
embedding party names in the opinion search directly — the tool is optimized for
this use case.

---

## Tool playbook

| Task | Tool | Notes |
|---|---|---|
| Search opinions by keyword | `run(ctx, question)` | Returns up to `max_results` opinions (case name + snippet) |
| Fetch a specific opinion | `fetch_opinion(ctx, cluster_id_or_url)` | Searches by cluster ID; returns one Document |
| Find a party's cases | `list_dockets_for_party(ctx, party_name)` | Party-name search across dockets |
| Citation treatment | `get_citation_treatment(ctx, citing_case)` | Approximate only — see caveat above |
| Oral argument audio | `get_oral_argument_audio(ctx, case_query)` | Returns audio metadata; transcript is ``None`` in v1 |
| Watch for new filings | `run_watchable(ctx, query, since=checkpoint)` | Filters client-side by `date_filed > since` |

### Typical sequence for Investigate / Reconstruct

```
1. run(ctx, question, max_results=10)         # broad opinion search
2. (planner) screen case names and snippets for relevance
3. fetch_opinion(ctx, cluster_id)             # full text of top hit(s)
4. get_citation_treatment(ctx, case_name)     # downstream citing opinions
5. (optional) get_oral_argument_audio(ctx, case_name)  # audio metadata
```

For Reconstruct mode, use `temporal_tools=true` — opinions carry `date_filed`
which enables a timeline of how doctrine evolved across cases.

### Typical sequence for Watch / Track

```
1. run_watchable(ctx, docket_query, since=last_check)
   # e.g. docket_query = "docket_number:1:23-cv-04567 Google"
2. (planner) alert on new filings
```

Recommended cadence: daily for active litigation, weekly for slower matters.
Use `docket_number:` prefix for precise docket tracking when the number is known.

---

## Watch mode notes

`run_watchable` fetches opinions matching `query` and filters client-side by
`date_filed > since`.  Because CourtListener's free-text search endpoint does
not expose a server-side date filter, filings older than the checkpoint are
discarded post-fetch.  The `since=` parameter must be a `datetime` object
(timezone-naive UTC or aware).

---

## Oral argument audio and transcripts

CourtListener stores oral argument audio for many federal circuit courts.
The `get_oral_argument_audio` tool returns a Document per hit; it calls the
shared `sources/transcript.py` pipeline (`transcribe_or_fetch_captions`) to
attempt transcript retrieval.

**In v1, transcripts are unavailable for most CourtListener audio** — the ASR
pipeline is a documented stub (returns ``None``).  The Document falls back to
the case metadata and opinion snippet.  A Whisper-based ASR backend, when added
in v1.1, will plug into `sources/transcript.py` via `register_provider` and
retroactively enable transcripts without changing this skill.

---

## Known biases and limitations

1. **Federal-strong / state-varies.** CourtListener's federal coverage is
   comprehensive; state coverage is uneven.  See the coverage table above.

2. **Citation treatment is approximate.** Not Westlaw/Lexis-grade.  See the
   citation caveat section above.

3. **Snippet-only by default.** The `run` entrypoint returns case name +
   snippet, not the full opinion text.  For full text, use `fetch_and_document`
   with the opinion URL from `doc.metadata["url"]` (via the general_web skill or
   a direct `ctx.fetch_and_document` call).

4. **RECAP coverage gaps.** PACER documents in RECAP are user-contributed.
   Not every filing exists in RECAP; critical filings in active cases may be
   absent.

5. **Processing lag.** Newly-filed opinions and documents may not appear for
   hours or days depending on CourtListener's indexing pipeline.

6. **No transcript in v1.** Oral argument transcripts return ``None`` until an
   ASR backend is registered.  Documents carry metadata only.

7. **API rate limits.** Unauthenticated requests have lower rate limits.
   Register a free API key at https://www.courtlistener.com/sign-in/ and set
   ``COURTLISTENER_API_KEY`` in your Lighthouse configuration for production use.
