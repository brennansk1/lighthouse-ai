# Example 2 — Batch-fetch multiple feeds in one run() call

## Question

```
"Latest AI news from https://feeds.feedburner.com/TheHackersNews and
https://www.theverge.com/rss/index.xml"
```

## Tool sequence

```python
docs = run(
    ctx,
    "Latest AI news from https://feeds.feedburner.com/TheHackersNews and "
    "https://www.theverge.com/rss/index.xml",
    max_results=10,
)
```

## Expected output shape

Up to 10 Documents drawn from both feeds in fetch order (5 from each feed at
most, interleaved as slots fill up).

```
[
  Document(id="rss:...", metadata={"feed_url": "https://feeds.feedburner.com/...", ...}),
  Document(id="rss:...", metadata={"feed_url": "https://www.theverge.com/rss/...", ...}),
  ...
]
```

## Notes

- The skill does not keyword-filter feed items by the question text — it returns
  all current items up to max_results.  Keyword filtering is the mode engine's job.
- Grade defaults to `B` unless the feed was registered with a per-feed override.
