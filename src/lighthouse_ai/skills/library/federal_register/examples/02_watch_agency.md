# Example 2 — Watch an agency for new publications

**Question:** Alert me when the FDA publishes anything new in the Federal Register.

**Tool sequence (Watch mode):**
```python
# First tick (no prior checkpoint):
docs = run_watchable(ctx, "food-and-drug-administration", since=None, max_results=10)

# Subsequent ticks use the publication_date of the last document seen:
from datetime import datetime
since = datetime(2024, 3, 1)
docs = run_watchable(ctx, "food-and-drug-administration", since=since, max_results=10)
```

**Expected output shape:**
- N Documents published after `since`, each with:
  - `metadata["document_type"]`: e.g. `"Notice"`, `"Rule"`, `"Proposed Rule"`
  - `metadata["publication_date"]`: ISO date string
  - `metadata["agency_names"]`: `["Food and Drug Administration"]`

**Notes:**
- The `query` parameter to `run_watchable` is the agency slug. Common slugs:
  - EPA: `"environmental-protection-agency"`
  - FDA: `"food-and-drug-administration"`
  - DOJ: `"justice-department"`
  - FTC: `"federal-trade-commission"`
- If unsure of the slug, use `run(ctx, "agency name")` first to find documents
  and inspect `metadata["agency_names"]`.
