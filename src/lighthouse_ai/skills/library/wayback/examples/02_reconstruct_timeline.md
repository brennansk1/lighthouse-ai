# Example 2 — Reconstruct how a corporate page changed over time

## Question

```
"How did Acme Corp's 'About Us' page (https://www.acme.com/about) change
between 2015 and 2023?"
```

## Tool sequence

```python
# Step 1 — get the chronology
snapshots = list_snapshots(
    ctx,
    "https://www.acme.com/about",
    from_date="20150101",
    to_date="20231231",
    limit=50,
    collapse_daily=True,   # one per day
)

# Step 2 — fetch key snapshots (e.g. first, middle, last)
key_timestamps = [snapshots[0]["timestamp"], snapshots[len(snapshots)//2]["timestamp"],
                  snapshots[-1]["timestamp"]]
docs = [fetch_snapshot(ctx, ts, "https://www.acme.com/about") for ts in key_timestamps]
```

## Expected output shape

```
snapshots = [
  {"timestamp": "20150312000000", "original": "https://www.acme.com/about",
   "statuscode": "200", "mimetype": "text/html"},
  ...
]

docs = [Document(...snapshot content at 3 timestamps...)]
```

## Notes

- Compare `doc.text` across timestamps to identify changes in mission, leadership,
  or product claims.
- In Reconstruct mode the mode engine drives this loop; the planner does not need
  to specify exact timestamps.
