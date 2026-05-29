# Example 3 — Cross-reference: "Find this film's IMDb entry"

## Question type
`cross_reference`

## Tool sequence

```python
# Step 1: Search for the film
hits = search_entity(ctx, "Parasite 2019 film", limit=3)
# → [{"id": "Q56943481", "label": "Parasite", "description": "2019 South Korean film by Bong Joon-ho"}]

# Step 2: Get IMDb identifier via resolve_identifier (fastest path)
ids = resolve_identifier(ctx, "Parasite 2019 film")
# → {
#     "qid": "Q56943481",
#     "label": "Parasite",
#     "description": "2019 South Korean film by Bong Joon-ho",
#     "IMDb": "tt6751668",
#     ...
# }
```

## Expected document metadata

```json
{
  "source": "wikidata",
  "qid": "Q56943481",
  "label": "Parasite",
  "identifiers": {"IMDb": "tt6751668"},
  "skill_id": "wikidata",
  "grade": "B"
}
```

## Notes

The IMDb id `tt6751668` can then be used to query the IMDb skill (when built)
or to construct the canonical IMDb URL: `https://www.imdb.com/title/tt6751668/`.
This pattern — Wikidata as an identifier hub → source-specific API — is the
primary use case for this skill.
