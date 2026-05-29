# Wikidata — Planner Guide

## When to use this skill

Wikidata is the right tool for **structured entity lookup and cross-source identifier resolution**.
Its core value proposition is: given an entity name (person, organization, work, place), return all
the machine-readable identifiers that link to external databases — ORCID, VIAF, IMDb, ISNI, GND,
Library of Congress, DOI, PubMed ID, and dozens more — in one API call.

**Use Wikidata for:**
- Resolving a person's ORCID from their name (then query OpenAlex or Semantic Scholar by ORCID).
- Confirming canonical entity identity before cross-referencing sources (e.g., "is this the same
  Albert Einstein in PubMed and in OpenAlex?").
- Retrieving structured properties of an entity: birth/death dates, nationality, occupation,
  affiliated organizations, official website.
- Disambiguating names: searching wikidata returns `description` fields that distinguish entities
  with the same label ("physicist, 1879–1955" vs "German-American chemist").
- Building a cross-reference map: Wikidata entity → VIAF → authority record → associated works.

**Do NOT use Wikidata as the primary citation for:**
- Biographical claims in Investigate or Adjudicate output (use the resolved ORCID profile or
  Wikipedia + primary sources; Wikidata's grade=B means one level above Wikipedia).
- Current/recent data (Wikidata lags; use live source once you have the identifier).
- Prose explanation (Wikidata is triples, not prose; Wikipedia or the primary source is better).

---

## Egress prerequisite

> **IMPORTANT**: wikidata.org is **not** in Lighthouse's default egress allowlist.
> The skill will load and call `run()` without error, but all fetch calls will be
> blocked and the skill will return `[]` with a log warning until the user enables egress:
>
> ```
> lighthouse trust add wikidata.org
> ```
>
> Without this, the skill degrades gracefully — it does not crash the job.

---

## Translating a question into a Wikidata query

1. **Extract the entity name.** "What is Marie Curie's ORCID?" → search `"Marie Curie"`.
2. **Disambiguate upfront.** Check the `description` field of search results. For people,
   descriptions like "physicist and chemist, winner of Nobel Prize" confirm identity.
3. **Use resolve_identifier for cross-source lookups.** This is the skill's highest-value
   tool — it chains search + fetch + extract_identifier_props in one call.
4. **Use get_properties for exhaustive claim inspection.** Returns all claims; useful when
   you need a property the planner didn't anticipate.
5. **Follow Q-ids.** Many claim values are Q-ids referencing other Wikidata entities. Use
   fetch_entity to resolve them if you need the label (e.g., nationality → Q183 → "Germany").

---

## Tool playbook

| Task | Tool | Notes |
|---|---|---|
| Find entities by name | `search_entity` | Returns id, label, description, url |
| Fetch full entity data | `fetch_entity` | Returns raw entity dict with all claims |
| Get parsed claims dict | `get_properties` | Returns {prop_id: value} — use prop IDs like P496 |
| Get cross-source identifiers | `resolve_identifier` | Best tool: name → ORCID/VIAF/IMDb/ISNI/… |

### Typical sequence for identifier resolution

```
1. resolve_identifier(ctx, "Marie Curie")
   # → {"qid": "Q7186", "ORCID": "...", "VIAF": "...", ...}
2. Use the ORCID/VIAF to query OpenAlex/VIAF for works
```

### Typical sequence for entity disambiguation

```
1. search_entity(ctx, "Newton", limit=5)
   # → [{"id": "Q935", "label": "Isaac Newton", "description": "English mathematician..."},
   #     {"id": "Q7297", "label": "Newton (unit)", "description": "SI unit of force"}, ...]
2. fetch_entity(ctx, "Q935")  # confirmed Isaac Newton
3. get_properties(ctx, "Q935")  # all claims
```

### Key property IDs (P-numbers)

| Property | P-number | Notes |
|---|---|---|
| ORCID identifier | P496 | For researchers |
| VIAF identifier | P214 | Virtual International Authority File |
| IMDb identifier | P345 | For film/TV people and works |
| ISNI identifier | P213 | International Standard Name Identifier |
| GND identifier | P227 | Deutsche Nationalbibliothek |
| Library of Congress | P244 | LCCN |
| PubMed identifier | P698 | For biomedical works |
| DOI | P356 | For publications |
| official website | P856 | |
| date of birth | P569 | |
| date of death | P570 | |
| occupation | P106 | Returns Q-id; resolve with fetch_entity |
| country of citizenship | P27 | Returns Q-id |

---

## Known biases and limitations

1. **Coverage is spotty for non-notable entities.** Wikidata has excellent coverage for
   major public figures, works, and places, but small entities (junior researchers, regional
   organizations) may be missing or have few claims.

2. **Identifiers may be absent.** ORCID coverage is best for current active researchers;
   VIAF/GND is better for historical figures. An empty `identifiers` dict is expected for
   some entities.

3. **Values are Q-ids, not labels.** Many claim values are references to other Wikidata
   entities (e.g., nationality P27 returns "Q183" for Germany). Use fetch_entity to resolve
   Q-ids to labels when you need human-readable text.

4. **Property IDs are stable but values can change.** Wikidata is crowd-edited; a property
   value asserted today may be revised. Treat claims as current best-knowledge, not ground
   truth, for time-sensitive research.

5. **Wikidata is graph-shaped, not text-shaped.** The Document produced by run() formats
   claims as text for the RAG pipeline, but it is not a prose document. Cross-source
   identifier values are the highest-confidence output; prose properties should be
   verified against primary sources.

6. **Language availability.** Labels and descriptions default to English (`lang="en"`).
   For entities with sparse English coverage, labels may fall back to another language.

---

## Grade and citation guidance

`default_grade = "B"` — Wikidata is more structured and verifiable than Wikipedia (grade C),
but it is crowd-edited and lacks peer-review. Identifier claims (ORCID, VIAF, IMDb) are
generally reliable because they are checkable against the external source. Biographical
claims (birth date, occupation) should be triangulated with primary sources for load-bearing
assertions. The discipline gate will apply a WEP band reduction on any claim for which
Wikidata is the sole source.
