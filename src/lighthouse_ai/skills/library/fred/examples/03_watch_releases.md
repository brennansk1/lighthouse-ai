# Example 3 — Watch FRED releases

**Question:** Alert when new employment or GDP data is released.

**Tool sequence:**
```python
docs = run_watchable(ctx, "employment GDP", since=last_checkpoint, max_results=10)
```

**Expected output shape:**
- 0–10 Documents describing FRED releases (Employment Situation, GDP, etc.)
- Each Document has `metadata["release_id"]` and `metadata["press_release"]`

**Notes:**
- The Watch tick deduplicates by document ID; new releases produce new Documents.
- Set `since` to the last Watch checkpoint to avoid re-processing old releases.
- For specific series cadence: Employment Situation releases first Friday of each month; GDP advance estimate releases ~30 days after quarter end.
