# Example: Investigate Guardian coverage of fossil fuel subsidies

## Question
What has The Guardian reported on fossil fuel subsidies and government policy?

## Tool sequence
1. `search_articles(ctx, "fossil fuel subsidies government policy", max_results=10)`
2. `get_tags(ctx, "environment/fossil-fuels", max_results=5)`
3. Combine and deduplicate results
4. For key articles, `fetch_article(ctx, url)` for full text

## Expected shape
- 6–12 Documents with `outlet=guardian`, `audit_tags=["allsides:left"]`
- Strong environmental angle; policy critique prominent
