# Example 3 — Reconstruct timeline: "Key events in the development of CRISPR"

## Question type
`causal_explanation` / timeline

## Tool sequence

```python
# Step 1: Search for the CRISPR overview
hits = search(ctx, "CRISPR gene editing history", limit=3)

# Step 2: Full extract to get the History section
doc = fetch_page(ctx, "CRISPR", full_extract=True)
# → Plain text includes "History" section with dated events

# Step 3: Infobox (if the article has one — concept articles often don't)
fields = extract_infobox(ctx, "CRISPR")
# → May be empty {} for abstract concept articles

# Step 4: Supplement with individual discovery articles
doc2 = fetch_page(ctx, "Jennifer Doudna", full_extract=False)
doc3 = fetch_page(ctx, "Emmanuelle Charpentier", full_extract=False)
```

## Notes

For timeline reconstruction, the "History" section of the overview article is usually the best
starting point. Wikipedia is reasonable for orientation but dates and authorship claims should be
triangulated with primary sources (e.g. PubMed or OpenAlex for the original papers).
