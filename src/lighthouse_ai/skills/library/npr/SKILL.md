# NPR — Research Skill Guide

## What this skill is

NPR (National Public Radio) is the U.S. public radio network, known for
in-depth, long-form reporting on politics, science, arts, and culture.  This
skill fetches NPR RSS feeds, searches npr.org, and can retrieve transcripts
from NPR audio segments.

**AllSides Media Bias Rating: Lean Left**

## Beat coverage

- U.S. politics and policy with strong depth
- Science and health (including health policy)
- Arts, culture, books, music
- Education
- World news with a U.S. perspective
- Business and economics

## Access method

NPR provides free public RSS feeds at `feeds.npr.org` (numeric feed IDs).
A web-search fallback uses `npr.org/search`.

Audio transcript extraction uses `sources/transcript.py` — in v1 this is a
stub that returns None; when an ASR provider is registered it will return
full transcript text from NPR show segments.

## Tools

### `search_articles(ctx, query, *, max_results=10)`
Fetches topic-relevant feeds and filters by query terms.  Falls back to
web search when feeds are insufficient.

### `fetch_article(ctx, url)`
Fetches a single NPR article URL through the broker.

### `fetch_audio_transcript(ctx, audio_ref)`
Attempts to retrieve a transcript for an NPR audio URL or segment identifier.
Returns empty list in v1 (ASR stub); non-empty when a provider is registered.

### `list_recent_in_topic(ctx, topic, *, since=None, max_results=10)`
Watchable tool.  Available topics: top, news, us, world, politics, business,
technology, science, health, arts, education, culture.

## Bias and limitations

- **Bias rating: Lean Left** (AllSides, 2024).
- Widely respected for factual accuracy and depth; critics note editorial
  tendency toward progressive framing.
- Stronger arts/culture and science coverage than wire services.
- Audio transcript extraction requires an ASR provider (v1.1+).
- Lighter on financial markets than Reuters or AP.

## Citation

Cite as: NPR, [article title], [date], npr.org
