# Example: Watch BBC Science for climate news

## Question
Watch for BBC Science & Environment articles about climate change.

## Tool sequence
1. `list_recent_in_topic(ctx, "science", since=last_tick, max_results=10)`
2. Filter for items mentioning "climate", "environment", "emissions"
3. Return Documents for Watch tick

## Expected shape
- 2–6 Documents with `outlet=bbc_news`, `type=news_article`
- Strong UK/European perspective on environmental policy
