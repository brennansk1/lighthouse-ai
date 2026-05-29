# Example: Search news across all outlets

## Question
What are major news outlets reporting about the Federal Reserve interest rate decision?

## Tool sequence
1. `search_news(ctx, "Federal Reserve interest rate", max_results=5)`
2. Group returned Documents by `doc.metadata["outlet"]`
3. Surface bias spread via `doc.metadata["allsides_rating"]`

## Expected shape
- Up to 30 Documents (5 per outlet × 6 outlets)
- Each Document: `outlet`, `allsides_rating`, `title`, `url`, `published_at`
- Wire services (Reuters, AP) likely have the most items; Guardian may have
  editorial commentary; ProPublica may have accountability angle
