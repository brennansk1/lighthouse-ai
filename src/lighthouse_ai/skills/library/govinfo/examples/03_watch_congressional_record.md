# Example 3 — Watch the Congressional Record for new proceedings

**Question:** Notify me when new Congressional Record entries are published.

**Tool sequence (Watch mode):**
```python
# First tick:
docs = run_watchable(ctx, "CREC", since=None, max_results=10)

# Subsequent ticks:
from datetime import datetime
since = datetime(2024, 4, 1)
docs = run_watchable(ctx, "CREC", since=since, max_results=10)
```

**Expected output shape:**
- Daily Congressional Record packages published after `since`, each with:
  - `metadata["collection_code"]`: `"CREC"`
  - `metadata["date_issued"]`: publication date
  - `metadata["package_id"]`: unique GovInfo identifier

**Notes:**
- The Congressional Record is published on days Congress is in session.
- Content includes floor speeches, votes, extensions of remarks, and inserted
  material — it is verbatim, not summarized.
- For bill-specific tracking, the Congress.gov skill is more targeted.
