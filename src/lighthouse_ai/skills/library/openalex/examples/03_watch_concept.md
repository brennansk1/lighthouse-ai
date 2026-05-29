# Example 3 — Watch: "Alert me to new peer-reviewed work on large language model alignment"

## Question type
`exploratory_survey`

## Mode
`watch`

## Tool sequence

```python
from datetime import datetime

# Weekly watch tick — fetch recent works on the topic
docs = run_watchable(
    ctx,
    "large language model alignment safety",
    since=datetime(2024, 5, 1),  # last tick checkpoint
    max_results=20,
)

# Planner: filter to works with published_date > since
# Planner: rank by cited_by (early citation velocity signals impact)
# Planner: surface top 3 new papers to the user's notification queue
```

## Notes

Watch mode for OpenAlex is best used for **established research areas** where the peer-review
cycle produces a steady stream of papers. For bleeding-edge topics (< 6 months old), arXiv's
watchable is better since preprints precede journal publication.

Use concept-qualified queries (2-4 terms) to reduce noise. OpenAlex sorts by relevance
rather than date, so use a generous ``max_results`` (20+) to catch newly-published work
that may rank lower than highly-cited older papers.
