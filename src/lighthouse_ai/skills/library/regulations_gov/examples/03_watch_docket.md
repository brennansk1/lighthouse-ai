# Example 3 — Watch a docket for new agency activity

**Question:** Alert me when the EPA posts new documents in the particulate matter docket.

**Tool sequence (Watch mode):**
```python
# Initial tick:
docs = run_watchable(ctx, "EPA-HQ-OAR-2022-0873", since=None, max_results=10)

# Subsequent ticks:
from datetime import datetime
since = datetime(2024, 3, 15)
docs = run_watchable(ctx, "EPA-HQ-OAR-2022-0873", since=since, max_results=10)
```

**Expected output shape:**
- New agency documents (not public comments) posted after `since`, each with:
  - `metadata["document_type"]`: `"Proposed Rule"`, `"Rule"`, `"Notice"`, etc.
  - `metadata["posted_date"]`: ISO date
  - `metadata["docket_id"]`: the watched docket

**Notes:**
- `run_watchable` tracks agency documents (not public comments).
- When the agency posts a Final Rule, the docket is essentially closed.
- Pair with Federal Register skill to read the published rule text.
