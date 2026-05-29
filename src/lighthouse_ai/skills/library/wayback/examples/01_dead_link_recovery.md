# Example 1 — Dead-link recovery

## Question

```
"The source URL https://www.example.gov/press/2022-announcement was cited
in a 2022 report but is now returning 404. Find the archived version."
```

## Tool sequence

```python
doc = lookup_url_at_date(
    ctx,
    "https://www.example.gov/press/2022-announcement",
    "20221231",
    fetch_content=True,
)
```

## Expected output shape

```
Document(
  id="rss:a1b2c3d4",   # wayback:20221215130000:deadbeef
  text="[preserved HTML content of the press release]",
  metadata={
    "skill_id": "wayback",
    "source": "wayback",
    "original_url": "https://www.example.gov/press/2022-announcement",
    "snapshot_timestamp": "20221215130000",
    "snapshot_url": "https://web.archive.org/web/20221215130000id_/https://...",
    "target_date": "20221231",
    "type": "snapshot",
    "grade": "A",
  }
)
```

## Notes

- Report the `snapshot_timestamp` to the user so they can cite "as of Dec 2022".
- If `lookup_url_at_date` returns None the URL was never crawled; report this.
