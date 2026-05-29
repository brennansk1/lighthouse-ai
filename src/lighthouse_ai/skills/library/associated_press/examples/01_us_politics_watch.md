# Example: Watch AP for U.S. Senate news

## Question
Watch for AP articles about U.S. Senate activity.

## Tool sequence
1. `list_recent_in_topic(ctx, "politics", since=last_tick, max_results=10)`
2. Filter for items mentioning "senate", "congress", "legislation"
3. Return filtered Documents as Watch tick result

## Expected shape
- 2–8 Documents with `outlet=associated_press`, `type=news_article`
- Wire-service style: concise, factual, dateline included
