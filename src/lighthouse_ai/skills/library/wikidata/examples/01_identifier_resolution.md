# Example 1 — Identifier resolution: "What is Marie Curie's ORCID and VIAF?"

## Question type
`identifier_resolution`

## Tool sequence

```python
# Single-call resolution: name → cross-source identifiers
ids = resolve_identifier(ctx, "Marie Curie")
# → {
#     "qid": "Q7186",
#     "label": "Marie Curie",
#     "description": "Polish-French physicist and chemist (1867–1934)",
#     "VIAF": "34517652",
#     "ISNI": "0000 0001 2103 5098",
#     "Library_of_Congress_identifier": "n79060545",
#     "GND_identifier": "118519352",
#     ...
# }
```

## Expected document metadata

```json
{
  "source": "wikidata",
  "qid": "Q7186",
  "label": "Marie Curie",
  "description": "Polish-French physicist and chemist (1867–1934)",
  "url": "https://www.wikidata.org/wiki/Q7186",
  "identifiers": {"VIAF": "34517652", "ISNI": "0000 0001 2103 5098"},
  "skill_id": "wikidata",
  "grade": "B"
}
```

## Notes

Marie Curie predates ORCID, so the ORCID field will be absent. VIAF and GND
have excellent coverage for historical academic figures. Use the VIAF ID to
query the Virtual International Authority File for her authority record and
associated works list.
