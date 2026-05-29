# SEC EDGAR — Planner Guide

## When to use this skill

SEC EDGAR is the right primary source for **U.S. public company disclosures**: annual reports
(10-K), quarterly reports (10-Q), current event reports (8-K), proxy statements (DEF 14A), and
insider transaction filings (Form 4).  It is a **regulatory archive** — filings are primary-source
documents submitted under penalty of law; they are not independently reviewed for accuracy but
carry significant legal weight.

**Use SEC EDGAR for:**
- Extracting a company's stated risk factors (Item 1A of the 10-K).
- Reading management's discussion of financial results and outlook (Item 7 / MD&A).
- Comparing a company's financial narrative across multiple annual or quarterly periods.
- Identifying material events (8-K): acquisitions, leadership changes, restatements.
- Tracking executive compensation and governance structure (DEF 14A proxy).
- Monitoring insider buying/selling activity (Form 4).
- Watching for new filings from a specific company by CIK (Watch mode).

**Do NOT rely on SEC EDGAR for:**
- Real-time stock prices or market data (use a financial data API).
- Non-U.S. company filings (use local equivalents or news sources).
- Analytical interpretation of financial data (the skill surfaces raw text; the planner
  or researcher must interpret it).
- Private companies — they do not file with the SEC unless they have public debt.

---

## Important: User-Agent requirement

SEC EDGAR's fair-use policy requires every automated request to include a descriptive
`User-Agent` header with a contact e-mail address.  The adapter sets:

```
User-Agent: Lighthouse/0.1 (mailto:research@lighthouse.local)
```

Users running Lighthouse in a professional context should override this in their
configuration with a real contact address to comply with SEC guidance at
https://www.sec.gov/os/accessing-edgar-data.  Requests without a meaningful User-Agent
may be rate-limited or blocked.

---

## Filing types and what they contain

| Form  | Full name | Key content |
|-------|-----------|-------------|
| 10-K  | Annual Report | Business overview, Risk Factors (1A), MD&A (7), audited financials |
| 10-Q  | Quarterly Report | Unaudited quarterly financials, QoQ changes, updated risk discussion |
| 8-K   | Current Report | Material events: M&A, leadership changes, restatements, earn. miss |
| DEF 14A | Proxy Statement | Executive compensation, board composition, governance proposals |
| Form 4 | Insider Transaction | Director/officer buy/sell activity within 2 business days |
| S-1   | IPO Registration | Full company prospectus for new public offerings |
| SC 13G/D | Beneficial Ownership | 5%+ ownership disclosures |

---

## Translating a question into an EDGAR query

EDGAR EFTS full-text search supports:

| Goal | Query form | Example |
|------|-----------|---------|
| Company filing search | Company name | `Apple Inc 10-K` |
| Specific filing type | `form-type:10-K` | `form-type:10-K Microsoft` |
| Risk factor language | keyword phrase | `supply chain disruption risk factors` |
| Material events | `form-type:8-K` + keyword | `form-type:8-K restatement` |
| CIK-based watch | bare CIK number | `0000320193` (Apple) |

---

## Tool playbook

| Task | Entrypoint | Notes |
|------|-----------|-------|
| Search filings by topic | `run(ctx, question)` | Returns up to `max_results` filings (title + snippet) |
| Watch company for new filings | `run_watchable(ctx, cik, since=checkpoint)` | Filters by `file_date > since`; pass bare CIK for CIK-specific watch |
| Extract 10-K Risk Factors | `parse_10k_item_1a(filing_text)` | Pure-Python, offline; pass full 10-K text or HTML exhibit |
| Extract 10-K MD&A | `parse_10k_item_7(filing_text)` | Pure-Python, offline; returns Item 7 text slice |

### Typical sequence for Investigate / Decide

```
1. run(ctx, "Apple 10-K risk factors", max_results=5)
   → list of Documents (title + filing snippet + URL)

2. (planner) identify the most recent 10-K accession URL from doc.metadata["url"]

3. ctx.fetch_and_document(url)
   → full 10-K text as a Document (broker-mediated)

4. parse_10k_item_1a(doc.text)
   → extracted Risk Factors section text

5. parse_10k_item_7(doc.text)
   → extracted MD&A section text

6. (planner) synthesize findings into the research output
```

### Typical sequence for Watch mode

```
# Watch Apple (CIK 0000320193) for new filings weekly
run_watchable(ctx, "0000320193", since=last_tick_datetime, max_results=20)
→ filings filed after last_tick_datetime
```

---

## The Item-section parsers

`parse_10k_item_1a` and `parse_10k_item_7` are deterministic text-segmenters
(no network, no ML).  They:

1. Strip HTML tags (EDGAR HTML exhibits are auto-handled).
2. Locate the target Item header via regex (`ITEM 1A`, `Item 1A.`, etc.).
3. Find the first subsequent sibling Item header to determine the boundary.
4. Return the text slice between them.

**Limitations:**
- Returns empty string if the target Item header is not found (some smaller
  filers use non-standard heading formats).
- For multi-exhibit 10-Ks the caller may need to pass the correct exhibit file
  text rather than the index page.
- Very large 10-K filings (100+ pages) can produce long outputs; callers should
  chunk the result for downstream LLM processing.

---

## Watch mode notes

`run_watchable` is designed for the `list_recent_for_cik` use case: pass a
bare CIK number to watch a specific company.  The adapter searches EDGAR's EFTS
endpoint and filters client-side on `file_date`.

Recommended cadence: **daily** for active coverage of a company (8-K filings can
arrive any business day), **weekly** for 10-Q monitoring.

The `since=` parameter must be a `datetime` object.  The EDGAR filing date is
stored as "YYYY-MM-DD"; comparisons strip the time component.

---

## Known biases and limitations

1. **U.S. public companies only.** EDGAR covers SEC-registered entities (public
   companies, mutual funds, foreign private issuers on U.S. exchanges).  Private
   companies are absent unless they file public debt disclosures.

2. **Full-text search coverage.** EDGAR's EFTS engine indexes most filings from
   1996+.  Older filings (pre-1996 SGML submissions) may be partially indexed.

3. **Exhibit separation.** A 10-K's main filing record often links to multiple
   exhibits; the search result may point to the filing index page.  The planner
   should retrieve individual exhibit URLs for section-level parsing.

4. **No structured financials.** The skill returns textual content, not parsed
   XBRL financial statements.  For structured financial data (income statement
   line items, balance sheet, ratios) use a financial data API or the SEC's
   inline XBRL viewer.

5. **Politeness.** SEC requests a minimum 10-second spacing between API calls
   (`rate_limit_per_sec = 0.1`).  The runner enforces this; do not call in a
   tight loop.

6. **Grade "B".** Documents are graded "B" — they are primary-source corporate
   disclosures, not peer-reviewed, and contain management-framed language that
   may omit or soften material risks.  Always note "SEC filing (management
   representation)" for load-bearing claims.
