# Example 2 — Watch: Track an active antitrust docket for new filings

## Question type
`factual_lookup` (incremental)

## Mode
`watch`

## Tool sequence

```python
# Tick 1 (first run): no checkpoint yet
docs = run_watchable(ctx, "docket_number:1:20-cv-03010 DOJ Google antitrust", since=None)
# → all matching opinions available so far

# Tick 2+ (subsequent runs): use last_seen as checkpoint
from datetime import datetime
checkpoint = datetime(2024, 6, 1)
docs = run_watchable(ctx, "docket_number:1:20-cv-03010 DOJ Google antitrust", since=checkpoint)
# → only opinions filed after 2024-06-01
```

## Expected document metadata

```json
{
  "source": "courtlistener",
  "title": "United States v. Google LLC",
  "url": "https://www.courtlistener.com/docket/17131544/united-states-v-google-llc/",
  "grade": "B",
  "published_date": "2024-08-05",
  "court": "dcd",
  "watchable_tool": "track_docket",
  "skill_id": "courtlistener",
  "skill_version": "0.1.0",
  "fetch_backend": "tier-a"
}
```

## Notes

Use the exact `docket_number:` prefix for reliable docket-level tracking.
Without the docket number, keyword queries may match unrelated cases.
Recommended cadence: daily for active trial litigation.
