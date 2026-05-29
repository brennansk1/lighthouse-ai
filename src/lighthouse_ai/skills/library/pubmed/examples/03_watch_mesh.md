# Example 3 — Watch: "Alert me to new RCTs on GLP-1 receptor agonists published this month"

## Question type
`exploratory_survey`

## Mode
`watch`

## Tool sequence

```python
from datetime import datetime

# Monthly watch tick with server-side date pre-filter
docs = run_watchable(
    ctx,
    "glucagon-like peptide-1 receptor agonists[mh] AND randomized controlled trial[pt] AND 2024/05/01:3000[dp]",
    since=datetime(2024, 5, 1),
    max_results=20,
)

# Planner: filter to published_date > since (client-side backup)
# Planner: surface trials with >= 100 participants to notification queue
```

## Notes

Combining the MeSH ``[dp]`` date filter (server-side) with the ``since=`` watchable filter
(client-side) gives two independent guards against stale results. The server-side ``[dp]``
pre-filters PubMed's result set before retrieval; the ``since=`` filter catches any edge cases
where the date metadata is in a different format. For high-volume therapeutic areas (GLP-1
drugs have had 100+ trials/month in 2024), this combination is essential to keep the watch
result set manageable.
