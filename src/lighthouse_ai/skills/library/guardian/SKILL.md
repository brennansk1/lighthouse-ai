# The Guardian — Research Skill Guide

## What this skill is

The Guardian is a major UK daily newspaper known for investigative journalism,
environmental coverage, and progressive politics.  This skill uses the Guardian
Open Platform API for structured article retrieval with rich metadata.

**AllSides Media Bias Rating: Left**

## Beat coverage

- UK and international politics (especially progressive/Labour angle)
- Environment and climate change (exceptional depth)
- Investigative journalism (Snowden documents, Panama Papers, etc.)
- Technology and digital rights
- Culture, arts, and books
- Science and health
- World news

## Access method

The Guardian Open Platform API (`content.guardianapis.com`) is free to use
with the `test` API key (50 req/day limit).  Registering a free developer
key increases this to 12 calls/second.

The `get_tags` tool exposes granular Guardian topic tags, enabling precise
retrieval of articles on specific subjects (e.g. `environment/climate-change`).

## Tools

### `search_articles(ctx, query, *, max_results=10)`
Searches the Guardian API for articles matching ``query``.  Returns rich
metadata including trail text (article summary).

### `fetch_article(ctx, url)`
Fetches a full Guardian article URL through the broker.

### `get_tags(ctx, tag, *, max_results=10)`
Fetches Guardian articles for a specific tag slug (e.g.
``environment/climate-change``, ``politics/conservatives``).

### `list_recent_in_topic(ctx, topic, *, since=None, max_results=10)`
Watchable tool.  Available topics: world, uk, politics, technology, science,
environment, business, culture, sport, health/society, education.

## Bias and limitations

- **Bias rating: Left** (AllSides, 2024).
- Consistently progressive framing; strongest bias of the 6 seed outlets.
- Exceptional for environmental and human rights coverage.
- Free API key limits: 50 req/day (test) or 12 req/s (registered).
- Full article text requires `fetch_article`; API provides summary only.

## Citation

Cite as: The Guardian, [article title], [date], theguardian.com
