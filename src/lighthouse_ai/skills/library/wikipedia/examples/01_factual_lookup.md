# Example 1 — Factual lookup: "When was the Eiffel Tower built?"

## Question type
`factual_lookup`

## Tool sequence

```python
# Step 1: Search
hits = search(ctx, "Eiffel Tower", limit=3)
# → [{"title": "Eiffel Tower", "url": "...", "snippet": "..."}]

# Step 2: Fetch the infobox for structured facts
fields = extract_infobox(ctx, "Eiffel Tower")
# → {"built": "1887–1889", "height": "330 m", "architect": "Gustave Eiffel", ...}

# Step 3 (optional): Full extract if the infobox lacks detail
doc = fetch_page(ctx, "Eiffel Tower", full_extract=False)
```

## Expected document metadata

```json
{
  "source": "wikipedia",
  "title": "Eiffel Tower",
  "url": "https://en.wikipedia.org/wiki/Eiffel_Tower",
  "skill_id": "wikipedia",
  "grade": "C"
}
```

## Notes

The infobox contains `built = 1887–1889` directly. No need to fetch the full extract for a simple
date question. The REST summary (full_extract=False) is sufficient as a supporting document.
