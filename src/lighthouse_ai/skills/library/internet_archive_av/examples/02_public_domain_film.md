# Example 2 — Prelinger Archives: Public-Domain Educational Film

**Question**: Find 1950s educational films about atomic energy.

## Tool sequence

```python
# 1. Search the Prelinger Archives collection
hits = search_av(ctx, "atomic energy nuclear education 1950s", collection="prelinger", max_results=5)
# → [{"identifier": "AtomicEnergy1951", "title": "The Atom and You", ...}, ...]

# 2. run() wraps metadata + description into a Document
docs = run(ctx, "1950s atomic energy educational film prelinger", max_results=5)
```

## Expected output shape

```
Document(
  id="ia_av:AtomicEnergy1951",
  text="The Atom and You. A 1951 educational film produced by the AEC...",
  metadata={
    "source": "internet_archive_av",
    "identifier": "AtomicEnergy1951",
    "url": "https://archive.org/details/AtomicEnergy1951",
    "mediatype": "movies",
    "date": "1951",
    "collection": "prelinger",
    "text_type": "description",
    "skill_id": "internet_archive_av",
    ...
  }
)
```

## Notes

- Public-domain films rarely have caption files; `text_type` will be `"description"`.
- The Prelinger Archives (`prelinger`) is the primary IA collection for U.S.
  industrial and educational films from the 20th century.
- License is public domain; no rights restrictions on reuse.
