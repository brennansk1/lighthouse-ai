# Example 1 — Television News Archive: 9/11 Coverage

**Question**: What did NBC Nightly News report on September 11, 2001?

## Tool sequence

```python
# 1. Search the Television News Archive collection
hits = search_av(ctx, "NBC 2001-09-11 evening news", collection="tvarchive", max_results=5)
# → [{"identifier": "NBC20010911", "title": "NBC Nightly News 9/11", ...}, ...]

# 2. Fetch full metadata + files list
meta = fetch_metadata(ctx, "NBC20010911")
# → {"metadata": {"title": "NBC Nightly News ...", "date": "2001-09-11", ...},
#    "files": [..., {"name": "NBC20010911.cc5.txt", "format": "Closed Caption Text"}, ...]}

# 3. Retrieve the closed-caption transcript
transcript = fetch_transcript(ctx, "NBC20010911", metadata=meta)
# → "BRIAN WILLIAMS: Good evening. We begin tonight with ..."

# 4. run() wraps this automatically
docs = run(ctx, "NBC Nightly News September 11 2001", max_results=3)
```

## Expected output shape

```
Document(
  id="ia_av:NBC20010911",
  text="NBC Nightly News 9/11. BRIAN WILLIAMS: Good evening. ...",
  metadata={
    "source": "internet_archive_av",
    "identifier": "NBC20010911",
    "url": "https://archive.org/details/NBC20010911",
    "mediatype": "movies",
    "date": "2001-09-11",
    "collection": "tvarchive",
    "text_type": "transcript",
    "skill_id": "internet_archive_av",
    ...
  }
)
```

## Notes

- Television News Archive items typically have `format = "Closed Caption Text"` files.
- The `tvarchive` collection covers major U.S. television news networks from ~2000 onward.
- For foreign language coverage, try collections like `BBCArchive` or search without a collection filter.
