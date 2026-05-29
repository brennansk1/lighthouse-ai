# Example: Investigate hospital nonprofit finances

## Question
Which large hospital nonprofits have the highest executive compensation relative to charity care?

## Tool sequence
1. `search_data_repo(ctx, "hospital health system", dataset="nonprofits", max_results=20)`
2. `search_articles(ctx, "hospital nonprofit compensation charity care", max_results=10)`
3. For key investigative pieces, `fetch_article(ctx, url)` for full text
4. Synthesize: match financial data to reporting

## Expected shape
- Open data Documents with `type=open_data`, `dataset=nonprofits`
- News Documents with `type=news_article`, `outlet=propublica`
- Rich investigative context with specific organizations named
