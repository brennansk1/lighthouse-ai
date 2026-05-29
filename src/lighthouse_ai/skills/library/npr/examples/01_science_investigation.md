# Example: Investigate NPR coverage of vaccine hesitancy

## Question
What has NPR reported about vaccine hesitancy causes and public health messaging?

## Tool sequence
1. `search_articles(ctx, "vaccine hesitancy public health", max_results=10)`
2. For each article URL, `fetch_article(ctx, url)` for full text
3. Synthesize findings across articles

## Expected shape
- 4–8 Documents with `outlet=npr`, `type=news_article`
- In-depth reporting with expert sources; health policy angle prominent
