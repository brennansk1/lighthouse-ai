# Example 3 — Watch for WHO outbreak indicators (Pattern-2)

**Question:** Alert me when WHO reports new outbreak-related health data.

**Tool sequence (Watch tick):**
```python
# On first tick: since=None returns all matching indicators
docs = run_watchable(ctx, "outbreak disease epidemic", since=None, max_results=10)

# On subsequent ticks: since is accepted for interface compatibility
# but GHO does not time-filter server-side — the dispatcher deduplicates by ID
from datetime import datetime
checkpoint = datetime(2026, 5, 1)
new_docs = run_watchable(ctx, "outbreak", since=checkpoint, max_results=10)
```

**Expected output shape:**
- Documents for outbreak/epidemic-related GHO indicators.
- The dispatcher compares document IDs against the previous tick's IDs to
  surface genuinely new entries.

**Notes:**
- For real-time outbreak alerts, WHO Disease Outbreak News
  (``who.int/csr/don``) is more timely than GHO data — this path is a
  documented v1.1 addition to this skill.
- Typical Watch cadence for this skill: weekly.
