# Example 2 — Independence audit: "Are there independent replications of the social media / teen depression link?"

## Question type
`causal_explanation`

## Mode
`adjudicate`

## Tool sequence

```python
# Step 1: Fetch papers on both sides
docs = run(ctx, "social media adolescent depression mental health longitudinal", max_results=15)

# Step 2: Planner groups papers by institution (affiliation signal)
# Example output from planner analysis:
#   - 4 papers from Oxford Internet Institute (same lab → correlated)
#   - 2 papers from Australian National University (different geography)
#   - 3 papers from NIH-funded US groups (different institution)

# Step 3: Planner notes independence cluster
# "Papers 1-4 are from the same group and should be counted as one independent evidence point"
# "Papers 5-9 represent 4 independent labs across 3 countries"

# Step 4: Cross-check retraction status
# → hand off to retraction_watch skill with DOIs from doc.metadata["url"]
```

## Expected document metadata

```json
{
  "source": "openalex",
  "title": "Association Between Social Media Use and Depression Among Adolescents",
  "url": "https://openalex.org/W3118643042",
  "grade": "A",
  "published_date": "2021-03-10",
  "cited_by": 847,
  "skill_id": "openalex",
  "skill_version": "0.1.0",
  "fetch_backend": "tier-a"
}
```

## Notes

The affiliation check is critical here. Several controversial research areas have clusters of
papers from a small number of labs. OpenAlex's affiliation metadata makes it possible to
distinguish "5 replications from 5 independent labs" from "5 papers from one lab's pipeline."
