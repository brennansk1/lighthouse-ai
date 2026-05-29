# Example 2 — Get the legislative history of a specific bill

**Question:** What actions were taken on H.R. 5376 (the Inflation Reduction Act) in the 117th Congress?

**Tool sequence:**
```python
from lighthouse_ai.sources.congress_gov import get_vote_record, fetch_bill

# Fetch bill summary:
bill_docs = fetch_bill(117, "hr", "5376")

# Fetch full action history:
action_docs = get_vote_record(117, "hr", "5376")
```

**Expected output shape:**
- `fetch_bill` → 1 Document with bill metadata
- `get_vote_record` → N Documents (actions), each with:
  - `metadata["action_date"]`: ISO date
  - `metadata["action_text"]`: description of the action
  - `metadata["action_type"]`: type code

**Notes:**
- Actions are ordered with the most recent first from the API.
- Sort by `action_date` ascending to reconstruct the legislative timeline.
