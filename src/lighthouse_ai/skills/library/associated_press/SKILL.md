# Associated Press — Research Skill Guide

## What this skill is

The Associated Press (AP) is the world's oldest and largest wire service,
providing fact-based news coverage with a U.S.-centric but internationally
broad reach.  This skill fetches AP RSS feeds and searches ap.org.

**AllSides Media Bias Rating: Center**

## Beat coverage

- U.S. politics and government
- World news
- Business and economics
- Sports
- Science and technology
- Health and medicine
- Entertainment

## Access method

AP provides public RSS feeds at `feeds.apnews.com`.  No API key required.
Topic feeds are available for politics, technology, business, sports,
science, health, entertainment, and world news.

A web-search fallback (`apnews.com/search?q=`) supplements the feed
when topic feeds don't match the query closely enough.

## Tools

### `search_articles(ctx, query, *, max_results=10)`
Fetches topic-relevant feeds and filters by query terms.  Falls back to
web search if feeds yield insufficient results.

### `fetch_article(ctx, url)`
Fetches a single article URL through the broker.

### `list_recent_in_topic(ctx, topic, *, since=None, max_results=10)`
Watchable tool.  Available topics: top, politics, technology, business,
sports, science, health, entertainment, world.

## Bias and limitations

- **Bias rating: Center** (AllSides, 2024).
- AP is known for factual wire-service style with minimal editorialization.
- Stronger U.S. domestic coverage than Reuters; somewhat lighter on
  international financial markets.
- Free RSS feeds provide titles and summaries; full article bodies require
  a separate `fetch_article` call.

## Citation

Cite as: Associated Press, [article title], [date], apnews.com
