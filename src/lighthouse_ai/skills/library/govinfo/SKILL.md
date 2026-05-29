# GovInfo — Planner Guide

## When to use this skill

GovInfo is the right primary source when the research question concerns
**archived, authoritative U.S. government publications**: the codified
regulations in the Code of Federal Regulations (CFR), the statutory text of the
United States Code (USC), the Congressional Record, GAO reports, public laws,
and other GPO-published compilations.

### U.S. federal government family: which skill?

| Research need | Right skill | Why |
|---|---|---|
| Agency notices, proposed rules, final rules, EOs | **Federal Register** | The raw daily publication of record |
| Public comments on proposed rules | **regulations.gov** | The comment portal |
| Codified law in the CFR or U.S. Code | **GovInfo** | Authoritative compiled versions — the "what the law says today" source |
| Current bills, votes, committee activity | **Congress.gov** | Legislative (not executive/agency) branch — current activity |

**GovInfo vs Federal Register — the critical distinction:**
- The Federal Register publishes rules as they are promulgated (raw, with
  preambles, effective dates, docket numbers). It is the *publication of record*.
- GovInfo's CFR collection is the *codified version* — the regulations as
  compiled into the Code of Federal Regulations, showing current text without
  the preamble history. Use GovInfo when you need "what does 40 CFR 50 say
  today?" Use Federal Register when you need "what did the EPA propose in
  2024 and why?"

**Use GovInfo for:**
- Retrieving the current text of a CFR section (`get_cfr_section`).
- Retrieving the current text of a U.S. Code section (`get_uscode_section`).
- Searching across all GPO collections (CFR + USC + CREC + GAOREPORTS + PLAW).
- Reading GAO audit and performance reports on federal agencies.
- Reconstructing what the law said at a specific point in time (older CFR
  editions are archived).
- Watching the Congressional Record for floor proceedings (`list_recent_in_collection`).

**Do NOT use GovInfo for:**
- The original rulemaking publications with preamble — use Federal Register.
- Public comments — use regulations.gov.
- Current legislative activity (bills being debated now) — use Congress.gov.
- State law — GovInfo covers federal publications only.

---

## Egress requirement

``api.govinfo.gov`` is NOT on the default Lighthouse platform allowlist.
This skill loads and degrades gracefully (returns ``[]`` with a logged note)
until the user explicitly grants trust:

```
lighthouse trust add api.govinfo.gov
```

A free API key from https://api.govinfo.gov/docs/ is also required.

---

## Key collection codes

| Code | Content |
|---|---|
| `CFR` | Code of Federal Regulations |
| `USCODE` | United States Code |
| `CREC` | Congressional Record |
| `GAOREPORTS` | GAO Reports |
| `PLAW` | Public Laws |
| `BILLS` | Congressional Bills (enrolled) |
| `STATUTE` | Statutes at Large |
| `FR` | Federal Register (also on federalregister.gov) |

---

## Translating a question into a GovInfo query

1. **CFR citation.** "40 CFR 50" → `get_cfr_section(40, "50")`.
2. **U.S. Code citation.** "42 USC 7401" → `get_uscode_section(42, "7401")`.
3. **GAO report.** `search_collection("agency name topic", collection="GAOREPORTS")`.
4. **Congressional Record.** `list_recent_in_collection("CREC")` for Watch.
5. **General keyword.** `run(ctx, "keyword")` searches all collections.

---

## Tool playbook

| Task | How to use | Notes |
|---|---|---|
| Search all collections | `run(ctx, "keyword")` | Cross-collection full-text search |
| Watch a collection for new documents | `run_watchable(ctx, "CREC", since=checkpoint)` | Use collection code as query |
| Look up CFR section | Call adapter: `get_cfr_section(title, part)` | Returns matching CFR packages |
| Look up U.S. Code section | Call adapter: `get_uscode_section(title, section)` | Returns matching USC packages |
| Find GAO reports | `search_collection("topic", collection="GAOREPORTS")` | Grade A — authoritative audits |

### Reconstruct mode: statutory history

1. Use `search_collection(law_name, collection="PLAW")` to find the public law.
2. Use `get_uscode_section(title, section)` for the current codified version.
3. Use `get_cfr_section(cfr_title, part)` for implementing regulations.
4. Cross-reference with Federal Register to find the implementing rulemakings.

---

## Known biases and limitations

1. **CFR editions are annual.** The CFR is republished annually. Between annual
   editions, amendments appear in the Federal Register but are not immediately
   reflected in the CFR compilation. For very recent amendments, check the FR.

2. **Full-text availability varies by collection.** Some older documents may be
   available as image PDFs only (not full-text searchable). Check `doc_class`
   in the metadata.

3. **Collection codes are exact.** The API requires exact collection codes. If
   a search with a collection code returns empty, verify the code is correct.

4. **Congressional Record is verbatim.** The CREC includes all floor
   proceedings, extensions of remarks, and inserted material. It is not a
   curated summary of debate.

5. **GAO reports are retrospective.** GAO reports evaluate completed programs
   or past performance. They are authoritative audits, not current policy
   assessments.

---

## Watch mode notes

`run_watchable` calls `list_recent_in_collection(query)` treating the query as
a collection code and filters by `date_issued > since`. Most useful for:
- `CREC`: daily Congressional Record (tracks floor proceedings)
- `GAOREPORTS`: new GAO audit reports
- `CFR`: new annual CFR editions

Typical Watch cadence: daily for CREC (Congress in session), monthly for CFR,
weekly for GAOREPORTS.
