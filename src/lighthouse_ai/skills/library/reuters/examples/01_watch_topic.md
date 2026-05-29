# Example: Watch Reuters for AI regulation news

## Question
Watch for Reuters articles about AI regulation published in the last 24 hours.

## Tool sequence
1. `list_recent_in_topic(ctx, "technology", since=yesterday, max_results=10)`
2. Filter returned Documents for those mentioning "regulation", "AI", or "artificial intelligence"
3. Return filtered Documents as the Watch tick result

## Expected shape
- 3–8 Documents with `outlet=reuters`, `type=news_article`
- Each Document: title, URL, brief description, published_at timestamp
- Metadata: `allsides:center`, `source=reuters`
