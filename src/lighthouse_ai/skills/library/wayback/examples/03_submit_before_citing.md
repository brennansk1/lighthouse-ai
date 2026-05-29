# Example 3 — Archive a live URL before citing it

## Question

```
"I want to cite https://www.agency.gov/new-regulation as of today.
Archive it so the citation is stable."
```

## Tool sequence

```python
doc = submit_for_archiving(ctx, "https://www.agency.gov/new-regulation")
```

## Expected output shape

```
Document(
  id="wayback:save:deadbeef",
  text=(
    "Submitted https://www.agency.gov/new-regulation for archiving.\n"
    "Status: 200\n"
    "Snapshot URL: https://web.archive.org/web/20260529120000/https://..."
  ),
  metadata={
    "skill_id": "wayback",
    "source": "wayback",
    "original_url": "https://www.agency.gov/new-regulation",
    "snapshot_url": "https://web.archive.org/web/20260529120000/https://...",
    "http_status": 200,
    "type": "save_submission",
    "grade": "A",
  }
)
```

## Notes

- The snapshot URL in the Document is the stable citation link to include in
  research output.
- SPN2 may take several seconds to minutes; if the returned snapshot URL does
  not yet exist, wait and then call `lookup_url_at_date` with today's date.
- Save Page Now has rate limits; do not submit the same URL repeatedly.
