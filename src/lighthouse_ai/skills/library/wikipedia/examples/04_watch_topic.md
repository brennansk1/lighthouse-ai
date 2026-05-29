# Example 4 — Watch: monitor recent Wikipedia edits on "Large Language Models"

## Pattern
Pattern-2 (continuous coverage via `run_watchable`)

## Usage

```python
from datetime import datetime, timezone, timedelta

# On first tick (no checkpoint yet)
docs = run_watchable(ctx, "large language model", since=None, max_results=10)

# On subsequent ticks (since = last tick timestamp)
last_tick = datetime(2024, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
docs = run_watchable(ctx, "large language model", since=last_tick, max_results=10)
```

## Expected document shape

```json
{
  "source": "wikipedia",
  "title": "Large language model",
  "type": "revision",
  "revision_id": 1234567,
  "timestamp": "2024-05-01T13:22:00Z",
  "editor": "ExampleUser",
  "skill_id": "wikipedia"
}
```

## Notes

`recent_revisions` filters by keyword match on article titles, not full-text search. For narrow
topics, use the exact Wikipedia article title as the `query` string. The result is time-ordered
(most recent first) so dedup against `last_tick` is straightforward.
