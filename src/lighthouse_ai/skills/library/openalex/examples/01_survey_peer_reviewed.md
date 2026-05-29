# Example 1 — Survey: "What is the peer-reviewed evidence on intermittent fasting and metabolic health?"

## Question type
`exploratory_survey`

## Mode
`survey`

## Tool sequence

```python
# Step 1: Broad sweep — enumerable output feeds the PRISMA funnel
docs = run(ctx, "intermittent fasting metabolic health randomized controlled trial", max_results=20)

# Step 2: Planner applies inclusion criteria:
#   - Must be a clinical study (RCT or cohort) — check abstract for study design
#   - Published 2015 or later (check published_date in metadata)
#   - Sample size > 20 (mentioned in abstract)

# Step 3: Check affiliations for independence clusters
# (e.g. if 5 of 8 supporting papers share one institution, flag this)

# Step 4 (optional): fetch full text for the top 3 papers via general_web
```

## Expected document metadata

```json
{
  "source": "openalex",
  "title": "Effects of Intermittent Fasting on Body Composition and Clinical Health Markers",
  "url": "https://openalex.org/W2963748456",
  "grade": "A",
  "published_date": "2020-06-15",
  "cited_by": 312,
  "skill_id": "openalex",
  "skill_version": "0.1.0",
  "fetch_backend": "tier-a"
}
```

## Notes

OpenAlex is the right first-stop for a clinical Survey because it surfaces peer-reviewed work
across all publishers. Check the ``cited_by`` count — papers with >100 citations have received
substantial peer scrutiny. Then cross-reference with PubMed for MeSH-controlled precision if
this sweep is too broad.
