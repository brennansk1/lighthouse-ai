# Example 3 — Watch a committee for new bill referrals

**Question:** Alert me when new bills are referred to the House Energy and Commerce Committee.

**Tool sequence (Watch mode):**
```python
# First tick:
docs = run_watchable(ctx, "hsif00", since=None, max_results=10)

# Subsequent ticks:
from datetime import datetime
since = datetime(2024, 3, 1)
docs = run_watchable(ctx, "hsif00", since=since, max_results=10)
```

**Common committee system codes:**
- `hsju00` — House Judiciary
- `hsif00` — House Energy and Commerce
- `sseg00` — Senate Energy and Natural Resources
- `ssju00` — Senate Judiciary
- `ssfi00` — Senate Finance
- `hswm00` — House Ways and Means

**Expected output shape:**
- Bills with `latest_action_date` after `since`, each with:
  - `metadata["bill_type"]`, `metadata["bill_number"]`, `metadata["congress"]`
  - `metadata["latest_action_text"]`: e.g. `"Referred to the House Committee on Energy and Commerce"`

**Notes:**
- If unsure of a committee system code, use `search_bills(committee_name)` first
  to find bills and inspect the committee metadata.
