# Example 2 — Watch mode: "Alert me when Tesla files a new 8-K or 10-Q"

## Question type
`event_monitoring`

## Mode
`watch`

## Tool sequence

```python
# Tesla CIK: 0001318605
# Watch for any new filing — cadence: daily for 8-K, weekly for 10-Q

new_docs = run_watchable(
    ctx,
    query="0001318605",          # Tesla's CIK
    since=last_tick_datetime,    # datetime of last successful tick
    max_results=20,
)
# → list of Documents for filings filed after last_tick_datetime
# Each doc.metadata["form_type"] indicates whether it is an 8-K, 10-Q, etc.
```

## Expected document metadata

```json
{
  "source": "sec_edgar",
  "title": "Tesla, Inc — 8-K",
  "url": "https://www.sec.gov/Archives/edgar/data/0001318605/000131860524000010/",
  "grade": "B",
  "published_date": "2024-01-24",
  "form_type": "8-K",
  "entity_name": "Tesla, Inc",
  "skill_id": "sec_edgar",
  "skill_version": "0.1.0",
  "fetch_backend": "tier-a"
}
```

## Notes

Use the bare numeric CIK for company-specific watching.  The `since=` parameter filters
on `file_date` (EDGAR's "YYYY-MM-DD" date field).  For the first tick pass `since=None`
to retrieve the N most recent filings as an initial snapshot.

Tesla files 8-K current reports frequently (earnings, vehicle delivery updates, executive
actions).  Set `max_results=20` and a daily cadence to avoid missing rapid-fire filings.
