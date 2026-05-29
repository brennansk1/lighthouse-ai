# Example 1 — Watch a news feed for new articles

## Question / Watch config

```
Watch: "https://feeds.bbci.co.uk/news/rss.xml"
Since: 2026-05-28T12:00:00Z
```

## Tool sequence

```python
# On each Watch tick
docs = run_watchable(
    ctx,
    "https://feeds.bbci.co.uk/news/rss.xml",
    since=datetime(2026, 5, 28, 12, 0, 0),
    max_results=10,
)
```

## Expected output shape

```
[
  Document(
    id="rss:a1b2c3d4",
    text="BBC headline\n\nLead paragraph from feed summary.",
    metadata={
      "skill_id": "rss",
      "source": "BBC News",
      "url": "https://www.bbc.co.uk/news/article-xxx",
      "title": "BBC headline",
      "published_at": "Wed, 29 May 2026 09:00:00 +0000",
      "feed_url": "https://feeds.bbci.co.uk/news/rss.xml",
      "type": "feed_item",
      "grade": "B",
    }
  ),
  ...
]
```

## Notes

- Only items with `published_at > since` are returned.
- Items without a timestamp are skipped on incremental ticks.
- Follow up interesting items with `ctx.fetch_and_document(doc.metadata["url"])`
  to retrieve the full article text.
