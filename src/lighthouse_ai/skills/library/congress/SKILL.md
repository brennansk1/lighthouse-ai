# Congress.gov — Planner Guide

## When to use this skill

Congress.gov is the right primary source when the research question concerns
**current and recent U.S. legislative activity**: bills moving through Congress,
floor votes, committee referrals, and the status of specific legislation.

### U.S. federal government family: which skill?

| Research need | Right skill | Why |
|---|---|---|
| Agency notices, proposed rules, final rules, EOs | **Federal Register** | Executive/agency branch rulemaking |
| Public comments on proposed rules | **regulations.gov** | Comment portal |
| Codified law in the CFR or U.S. Code | **GovInfo** | Archived authoritative compilations |
| Current bills, votes, committee activity | **Congress.gov** | Current legislative activity — this skill |

**Congress.gov vs GovInfo — the critical distinction:**
- Congress.gov covers *current legislative activity*: bills being introduced,
  debated, and voted on right now. It tracks the legislative process in real time.
- GovInfo covers *archived authoritative publications*: enacted laws in the
  Statutes at Large, the U.S. Code as codified, the Congressional Record.
  Use Congress.gov when the question is "what is Congress doing now?" Use
  GovInfo when the question is "what does the law currently say?"

**Use Congress.gov for:**
- Finding whether a bill on a specific topic has been introduced, passed, or
  signed into law.
- Retrieving the full legislative history (actions) of a bill: introduction,
  committee referral, floor votes, Presidential action.
- Tracking which committee has jurisdiction over a topic and what bills it is
  considering (`track_committee`, watchable).
- Identifying the bill number (HR or S) for a piece of legislation to look up
  in GovInfo for the enrolled bill text.
- Monitoring active legislative sessions for new bill introductions on a topic.

**Do NOT use Congress.gov for:**
- The enacted statutory text — use GovInfo (USCODE or PLAW).
- Agency regulations implementing a law — use Federal Register or GovInfo (CFR).
- Public comments on regulations — use regulations.gov.
- Historical Congresses before the API's coverage — the API covers recent
  Congresses well; older records may be incomplete.

---

## Egress requirement

``api.congress.gov`` is NOT on the default Lighthouse platform allowlist.
This skill loads and degrades gracefully (returns ``[]`` with a logged note)
until the user explicitly grants trust:

```
lighthouse trust add api.congress.gov
```

A free API key from https://api.congress.gov/sign-up/ is also required.

---

## Key bill types and identifiers

| Type code | Meaning |
|---|---|
| `hr` | House of Representatives bill |
| `s` | Senate bill |
| `hjres` | House Joint Resolution |
| `sjres` | Senate Joint Resolution |
| `hconres` | House Concurrent Resolution |
| `sconres` | Senate Concurrent Resolution |
| `hres` | House Simple Resolution |
| `sres` | Senate Simple Resolution |

Bills are identified by: `{congress}-{type}-{number}` (e.g. `118-hr-1` = H.R. 1 of the 118th Congress).

---

## Translating a question into a Congress.gov query

1. **Topic search.** `search_bills("topic keywords")` — searches bill titles.
2. **Known bill.** `fetch_bill(118, "hr", "1234")` for a specific bill.
3. **Vote record.** `get_vote_record(118, "hr", "1234")` for the actions list.
4. **Committee watch.** `track_committee("hsju00")` for House Judiciary.

---

## Tool playbook

| Task | How to use | Notes |
|---|---|---|
| Find bills on a topic | `run(ctx, "topic keywords")` | Searches bill titles + recent action |
| Watch committee for new referrals | `run_watchable(ctx, "hsju00", since=checkpoint)` | Committee system code as query |
| Fetch a specific bill | Call adapter: `fetch_bill(118, "hr", "1234")` | Returns bill with latest action |
| Get vote/action history | Call adapter: `get_vote_record(118, "hr", "1234")` | Full action list for bill |

### Reconstruct mode: legislative history of a law

1. Use `search_bills(law_topic)` to find the bill.
2. Use `get_vote_record(congress, type, number)` to get the full action timeline.
3. Cross-reference with GovInfo (PLAW) for the enrolled text as signed.
4. Cross-reference with Federal Register for agency rulemakings implementing it.
5. Note key dates: introduction, committee markup, floor passage, Presidential
   action.

### Adjudicate mode: "does the bill address X?"

1. Use `search_bills(topic)` to find candidate bills.
2. Use `fetch_bill` for each candidate to get the full title and latest action.
3. Compare bill scope and status (enacted vs. died in committee).

---

## Known biases and limitations

1. **Title-based search only.** The API searches bill titles, not full bill
   text. For full-text legislative search, use congress.gov's web interface
   or GovInfo (BILLS collection for enrolled text).

2. **Coverage is recent Congresses.** Detailed structured data is best for
   the 93rd Congress (1973) onward; earlier records are less complete.

3. **Actions ≠ votes.** The actions list includes all parliamentary actions
   (committee referrals, amendments offered, final votes). Actual roll-call
   vote tallies live at clerk.house.gov and senate.gov (not in this API).

4. **Bills die in committee.** Most introduced bills never advance. A bill
   appearing in search results does not mean it became law. Check
   `latest_action_text` for status.

5. **Committee code format.** The committee system code (e.g. ``"hsju00"``)
   is not the committee's public name. Use `search_bills(committee_name)` to
   find bills and inspect the metadata to discover the system code.

---

## Watch mode notes

`run_watchable` calls `track_committee(query)` treating the query as a
committee system code and filters by `latest_action_date > since`. Use this to
monitor when new bills are referred to a committee of interest.

Typical Watch cadence: daily when Congress is in session, weekly during recesses.
