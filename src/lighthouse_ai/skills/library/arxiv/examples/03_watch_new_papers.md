# Example 3 — Watch: "Monitor for new papers on large language model alignment"

## Mode
`watch` (Pattern-2, continuous coverage)

## Tool sequence

```python
from datetime import datetime, timezone

# On each Watch tick the runner calls run_watchable with since=last_tick_at
docs = run_watchable(
    ctx,
    query="cat:cs.AI large language model alignment safety",
    since=datetime(2024, 6, 1, tzinfo=timezone.utc),
    max_results=10,
)
# → only papers submitted after 2024-06-01 are returned
# → each doc tagged with skill_id="arxiv", grade="A"
```

## Expected behaviour

- Papers with `published_date <= since` are filtered out client-side.
- An empty list is returned if no new papers match since the last tick.
- The Watch worker deduplicates by `doc.id` across ticks.

## Recommended cadence

Daily for active topics like LLM alignment; weekly for slower subfields.
Use `cat:cs.AI` or `cat:cs.LG` to reduce noise from tangentially-related fields.

## Notes

The arXiv API does not support server-side date filtering on the public query endpoint,
so filtering happens client-side. Pass a generous `max_results` (10–20) for daily
cadences so newly-submitted papers are not silently missed.
