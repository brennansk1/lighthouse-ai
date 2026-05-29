# Example 3 — Collection Listing: Old Time Radio

**Question**: What old-time radio programs are available in the Internet Archive?

## Tool sequence

```python
# 1. List the old-time radio collection
items = get_collection_listing(ctx, "oldtimeradio", max_results=10)
# → [{"identifier": "Jack_Benny_Program", ...}, {"identifier": "Fibber_McGee_Molly", ...}, ...]

# 2. Drill into a specific item
meta = fetch_metadata(ctx, "Jack_Benny_Program")
# → full metadata with files list

# 3. Attempt transcript (returns None — no captions for old radio)
transcript = fetch_transcript(ctx, "Jack_Benny_Program", metadata=meta)
# → None (no caption files; no ASR provider registered in v1)
```

## Notes

- Most audio-only items do not have caption files; `fetch_transcript` returns `None`.
- The skill gracefully falls back to description text in `run()`.
- Use `get_collection_listing` to explore a collection before running targeted searches.
