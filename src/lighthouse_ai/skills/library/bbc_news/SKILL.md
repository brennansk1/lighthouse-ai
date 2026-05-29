# BBC News — Research Skill Guide

## What this skill is

BBC News is the international public-service broadcaster of the United Kingdom,
providing comprehensive coverage of UK and world affairs.  Publicly funded and
editorially independent of government.

**AllSides Media Bias Rating: Lean Left**

## Beat coverage

- World news with strong UK and European focus
- UK politics and government
- Technology and internet policy
- Science and environment
- Business and economics
- Health and medicine

## Access method

BBC provides free public RSS feeds at `feeds.bbci.co.uk`.  No API key required.
This skill uses RSS-only access — no JavaScript rendering needed.

Available topic feeds: world, uk, technology, science, business, health, politics, top.

## Tools

### `search_articles(ctx, query, *, max_results=10)`
Fetches topic-relevant feeds and filters items by query terms.

### `fetch_article(ctx, url)`
Fetches a BBC article URL through the broker and returns it as a Document.

### `list_recent_in_topic(ctx, topic, *, since=None, max_results=10)`
Watchable tool.  Returns latest items from a topic feed, filtered by ``since``.

## Bias and limitations

- **Bias rating: Lean Left** (AllSides, 2024).
- Widely respected for factual accuracy; some critics note institutional
  tendency to frame issues from a liberal/progressive perspective.
- Very strong UK and European coverage; U.S. coverage less granular than AP.
- RSS feeds provide brief summaries; full article text requires `fetch_article`.
- Sports coverage is extensive for UK/European audiences.

## Citation

Cite as: BBC News, [article title], [date], bbc.com
