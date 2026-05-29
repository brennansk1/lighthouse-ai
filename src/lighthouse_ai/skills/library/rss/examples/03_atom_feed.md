# Example 3 — Monitoring an Atom feed (arXiv new submissions)

## Question / Watch config

```
Watch: "https://export.arxiv.org/rss/cs.AI"
Since: 2026-05-28T00:00:00Z
```

## Tool sequence

```python
docs = run_watchable(
    ctx,
    "https://export.arxiv.org/rss/cs.AI",
    since=datetime(2026, 5, 28, 0, 0, 0),
    max_results=20,
)
```

## Expected output shape

Each Document contains the arXiv abstract title and summary from the RSS item.

```
Document(
  id="rss:feedhash",
  text="Efficient Transformers via ...\n\nAbstract: We present a method ...",
  metadata={
    "skill_id": "rss",
    "source": "cs.AI updates on arXiv.org",
    "url": "https://arxiv.org/abs/2506.NNNNN",
    "title": "Efficient Transformers via ...",
    "published_at": "Thu, 29 May 2026 00:00:00 -0400",
    "feed_url": "https://export.arxiv.org/rss/cs.AI",
    "type": "feed_item",
    "grade": "B",
  }
)
```

## Notes

- The RSS summary contains the arXiv abstract text, making this a lightweight
  way to monitor new CS/AI submissions without needing the arXiv skill.
- For deeper metadata (author affiliations, citation graph) use the arXiv skill
  directly after identifying items of interest.
- arXiv export.arxiv.org is on the platform egress allowlist.
