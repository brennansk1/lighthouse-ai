# Example 1 — Investigate risk factors: "What are Apple's key supply-chain risks?"

## Question type
`risk_assessment` / `factual_lookup`

## Mode
`investigate`

## Tool sequence

```python
# Step 1: Search for Apple's most recent 10-K
docs = run(ctx, "Apple Inc form-type:10-K", max_results=3)
# → list of Documents, each with title + snippet + URL pointing to filing index

# Step 2: Planner picks the most recent filing URL from doc.metadata["url"]
filing_index_url = docs[0].metadata["url"]

# Step 3: Fetch the 10-K exhibit (the full annual report text)
full_doc = ctx.fetch_and_document(filing_index_url)

# Step 4: Extract Item 1A — Risk Factors
from lighthouse_ai.skills.library.sec_edgar.parsers import parse_10k_item_1a
risk_text = parse_10k_item_1a(full_doc.text)

# Step 5: Planner synthesizes risk factors relevant to supply-chain
```

## Expected document metadata

```json
{
  "source": "sec_edgar",
  "title": "Apple Inc — 10-K",
  "url": "https://www.sec.gov/Archives/edgar/data/0000320193/000032019323000106/",
  "grade": "B",
  "published_date": "2023-11-03",
  "form_type": "10-K",
  "entity_name": "Apple Inc",
  "skill_id": "sec_edgar",
  "skill_version": "0.1.0",
  "fetch_backend": "tier-a"
}
```

## Notes

Apple's CIK is 0000320193.  The Item 1A section typically runs 5–15 pages in Apple's 10-K.
Use `parse_10k_item_1a` to extract just the Risk Factors; the full 10-K text is very large.
Grade "B" reflects that risk disclosures are management-authored — they may be strategically
worded.  Cross-reference 8-K filings and news coverage for corroboration.
