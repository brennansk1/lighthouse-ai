# Example: Watch all outlets for breaking news

## Question
Watch for any new coverage of the AI regulation bill since the last check.

## Tool sequence
1. `run_watchable(ctx, "AI regulation bill", since=last_tick_timestamp, max_results=5)`
2. Returned Documents filtered to items published after `since`
3. Each Document tagged with `outlet` + `allsides_rating` for provenance

## Expected shape
- Variable number of Documents (0–30 depending on activity)
- Only items with `published_at > since`
- Suitable for Watch-mode continuous polling across the full outlet set
