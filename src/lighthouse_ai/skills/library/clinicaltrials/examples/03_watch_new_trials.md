# Example 3 — Watch for new trial registrations (Pattern-2)

**Question:** Notify me when new trials are registered for Alzheimer's disease.

**Tool sequence (Watch tick):**
```python
# On first tick: since=None returns all matching trials
docs = run_watchable(ctx, "Alzheimer's disease", since=None, max_results=10)

# On subsequent ticks: since=last_checkpoint filters to new registrations
from datetime import datetime
checkpoint = datetime(2026, 5, 1)
new_docs = run_watchable(ctx, "Alzheimer's disease", since=checkpoint, max_results=10)
```

**Expected output shape:**
- Each new trial as a Document with `metadata["start_date"]` after `since`.
- Empty list `[]` if no new trials have been registered since the checkpoint.

**Notes:**
- The filter uses `start_date` from the protocol record. For precise
  "registration date" filtering, inspect `firstSubmitDate` from the full record.
- Typical Watch cadence: weekly for ongoing monitoring.
