# Example 2 — Exploratory survey: "What are the main types of renewable energy?"

## Question type
`exploratory_survey`

## Tool sequence

```python
# Step 1: Search for the overview article
hits = search(ctx, "renewable energy", limit=5)

# Step 2: Full extract of the main overview article
doc = fetch_page(ctx, "Renewable energy", full_extract=True)
# → Long plain-text with sections: Solar, Wind, Hydropower, Geothermal, Bioenergy

# Step 3: Category walk to discover related articles
members = walk_category(ctx, "Renewable energy")
# → [{"title": "Solar power", ...}, {"title": "Wind power", ...}, ...]
```

## Expected output shape

Multiple documents:
- One full-extract document from the overview article (covers all types in one text)
- Category member titles that the planner can use to fetch individual articles if needed

## Notes

Wikipedia's categories are rich for established domains like energy. `walk_category` is more
reliable than repeated searches for "list all X" questions in well-maintained topic areas.
