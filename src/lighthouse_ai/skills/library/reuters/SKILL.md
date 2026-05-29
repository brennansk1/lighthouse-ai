# Reuters — Research Skill Guide

## What this skill is

Reuters is the world's largest wire news service, providing breaking news and
analysis across politics, finance, business, technology, science, and world
affairs.  This skill fetches Reuters RSS feeds and returns articles as Documents.

**AllSides Media Bias Rating: Center**

## Beat coverage

- World news and geopolitics
- Financial markets and business
- Technology and science
- Politics (U.S. and international)
- Health and environment

## Access method

Reuters provides public RSS feeds at `feeds.reuters.com`.  No API key required.
The skill maps topic keywords to the appropriate feed URL automatically.

Available topic feeds:
- `world` — top global news
- `business` — corporate and economic news
- `technology` — tech industry news
- `science` — research and science news
- `markets` — financial markets
- `politics` — political news
- `health` — health and medicine

## Tools

### `search_articles(ctx, query, *, max_results=10)`
Fetches topic-relevant feeds and filters items whose title/body matches
query terms.  Best for: "What is Reuters reporting on topic X?"

### `fetch_article(ctx, url)`
Fetches a single article URL via the broker and returns it as a Document.

### `list_recent_in_topic(ctx, topic, *, since=None, max_results=10)`
The watchable tool.  Returns the latest items from a topic feed, optionally
filtered by a ``since`` timestamp for Watch-mode continuous coverage.

## Bias and limitations

- **Bias rating: Center** (AllSides, 2024).
- Reuters copy is typically wire-service style — brief, factual, less
  editorialized than newspaper sources.
- Free RSS feeds provide titles and brief descriptions; full article body
  requires a separate `fetch_article` call.
- Market/financial news is prominent; less cultural/arts coverage.

## Citation

Cite as: Reuters, [article title], [date], reuters.com
