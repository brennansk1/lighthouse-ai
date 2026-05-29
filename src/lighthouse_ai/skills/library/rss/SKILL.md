# RSS / Atom Feeds — Planner Guide

## When to use this skill

RSS is the right tool when the user has **registered specific feed URLs** they
want to monitor or when a question explicitly references a feed URL. It is the
primary Watch-mode channel skill — the researcher points Lighthouse at any
syndication feed and gets time-ordered documents back on every tick.

**Use RSS for:**
- Monitoring news outlets, blogs, government agencies, and academic preprint
  servers that publish RSS or Atom feeds.
- Continuous Watch coverage: `run_watchable` with `since=last_tick` returns only
  new items, so the tick engine doesn't re-deliver old stories.
- Batch sampling: pass multiple feed URLs in one call to get a cross-source
  snapshot of a topic's latest coverage.
- Bridging the gap before a specialist skill exists — almost every website that
  publishes structured content has an RSS feed.

**Do NOT rely on RSS for:**
- Deep page content: items contain only the title and the feed's summary/description
  field, not the full article body. Follow up with `general_web` or a specialist
  skill to retrieve the full text of interesting items.
- Historical coverage: RSS feeds typically only expose the most recent 10–50 items.
  Use the Wayback skill for historical retrieval.
- Source independence: if all registered feeds come from the same publisher, the
  corpus is not independent. Add feeds from diverse outlets before an Adjudicate run.

---

## Translating a question into an RSS query

The skill scans the question string for http(s) URLs. The question may:

1. **Contain the feed URL directly** — `"latest from https://feeds.bbci.co.uk/news/rss.xml"`
2. **Be a pipe-separated list of URLs** — `"https://example.com/feed|https://other.com/rss"`
3. **Contain a natural question with an embedded URL** — the regex extracts all URLs automatically.

If no URL is found, `run()` returns an empty list. The Watch engine should store
registered feed URLs in the watch config and always pass them in `query`.

---

## Tool playbook

| Task | Tool | Notes |
|---|---|---|
| Fetch current feed items | `run(ctx, question_with_url)` | Returns up to max_results items |
| Monitor for new items | `run_watchable(ctx, query_with_url, since=last_tick)` | Returns only newer-than-since items |
| Parse raw feed bytes | `parse_feed_bytes(payload)` | From `lighthouse_ai.sources.rss`; returns MonitorItems |

### Typical sequence for Watch

```
1. User registers feed URL in Watch config
2. On each tick: run_watchable(ctx, "<url>", since=last_tick_at)
3. New items come back as Documents tagged type="feed_item"
4. For items of interest: run general_web fetch on item.url for full text
```

---

## Per-feed grade and bias

Grade and bias are set **per feed at registration** — the default_grade in the
manifest (`B`) is the fallback when no per-feed override is configured.

| Feed type | Recommended grade | Notes |
|---|---|---|
| Major wire service (AP, Reuters) | A | Editorial standards, corrections culture |
| Public broadcaster (BBC, NPR) | A | Editorial standards, public accountability |
| Newspaper / magazine | B | Varies by outlet; check AllSides/Ad Fontes |
| Blog / independent | C | No editorial layer; triangulate |
| Government agency | A–B | Official but may be self-serving; check for omissions |
| Academic preprint server | B | Not peer-reviewed; use arXiv skill for full metadata |

The `grade` metadata field on each Document reflects whatever was configured
at registration. In the absence of a per-feed setting the manifest default (`B`)
applies and a WEP downgrade will fire if the document is the sole citation for
a load-bearing claim.

---

## Known biases and limitations

1. **Shallow content.** RSS items contain only the title and summary, not the
   full article. The `body` field comes from the feed's `<description>` /
   `<content>` / `<summary>` tag — quality varies enormously.

2. **Recency window.** Most feeds expose only the last 10–50 items. There is no
   paging mechanism; historical coverage requires the Wayback skill.

3. **No search.** RSS is a pull-everything protocol — the skill fetches all
   current items and filters by timestamp. It cannot search a feed for a topic.
   Keyword-filter the returned Documents in the mode engine after fetching.

4. **Timestamp reliability.** Some feeds omit `<pubDate>` / `<updated>` or use
   non-standard formats. Items without a parseable timestamp are included on the
   first tick and excluded on incremental ticks to avoid re-delivery.

5. **Feed discovery not included.** This skill does not auto-discover a site's
   feed URL from a homepage (`<link rel="alternate" type="application/rss+xml">`).
   The user or the planner must supply the direct feed URL.

---

## Watch mode notes

`run_watchable` uses a naive datetime comparison (timezone-stripped UTC) against
the item's published timestamp. Feeds that backdate items or re-publish old items
with updated timestamps may cause false positives. A de-duplication step on URL
in the Watch engine is recommended.

Recommended Watch cadence: every 15–60 minutes for news feeds, every 1–6 hours
for low-volume academic or government feeds.
