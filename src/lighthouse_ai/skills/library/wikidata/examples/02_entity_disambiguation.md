# Example 2 — Entity disambiguation: "Tell me about Newton"

## Question type
`entity_disambiguation`

## Tool sequence

```python
# Step 1: Search — multiple entities with the same name
hits = search_entity(ctx, "Newton", limit=5)
# → [
#     {"id": "Q935",  "label": "Isaac Newton", "description": "English mathematician and physicist (1643–1727)"},
#     {"id": "Q7297", "label": "newton",       "description": "SI derived unit of force"},
#     {"id": "Q484048","label": "Newton",      "description": "city in Massachusetts, United States"},
#     ...
# ]

# Step 2: Confirm the intended entity by description
# Planner picks Q935 (Isaac Newton the person)
entity = fetch_entity(ctx, "Q935")

# Step 3: Get all properties
props = get_properties(ctx, "Q935")
# → {"P31": "Q5", "P569": "1643-01-04", "P570": "1727-03-31", "P214": "22146457", ...}
```

## Expected document metadata

```json
{
  "source": "wikidata",
  "qid": "Q935",
  "label": "Isaac Newton",
  "description": "English mathematician and physicist (1643–1727)",
  "url": "https://www.wikidata.org/wiki/Q935",
  "skill_id": "wikidata",
  "grade": "B"
}
```

## Notes

The description field is the key disambiguation signal. Showing it in the
planner's entity selection UI lets the user confirm the right Q-id before
fetching properties. For scientific figures, also check P21 (sex/gender),
P569 (birth), P570 (death), and P19 (place of birth) for context.
