# Example 3 — Survey MD&A: "Compare how three semiconductor companies described revenue trends in their most recent 10-K"

## Question type
`comparative` / `exploratory_survey`

## Mode
`survey`

## Tool sequence

```python
# Step 1: Search for recent 10-Ks from each company
companies = ["NVIDIA form-type:10-K", "Intel form-type:10-K", "AMD form-type:10-K"]
all_filings = []
for q in companies:
    all_filings.extend(run(ctx, q, max_results=2))

# Step 2: Fetch and parse Item 7 (MD&A) for each filing
from lighthouse_ai.skills.library.sec_edgar.parsers import parse_10k_item_7

mda_sections = {}
for doc in all_filings:
    full = ctx.fetch_and_document(doc.metadata["url"])
    if full:
        mda_sections[doc.metadata["entity_name"]] = parse_10k_item_7(full.text)

# Step 3: Planner compares revenue trend language across the three MD&A sections
```

## Expected output shape

Three text slices (one per company), each beginning with the Item 7 header and covering
revenue discussion, operating results, and forward-looking statements.

## Notes

MD&A (Item 7) is the richest narrative section in the 10-K for understanding how management
frames financial performance.  The `parse_10k_item_7` parser extracts the section deterministically.
For semiconductor companies this section typically runs 15–30 pages; chunking for LLM synthesis
may be needed.  Grade "B" applies — management controls the narrative framing.
