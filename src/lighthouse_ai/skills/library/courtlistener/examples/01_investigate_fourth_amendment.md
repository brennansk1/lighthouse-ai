# Example 1 — Investigate: "How have federal courts treated warrantless cell phone searches?"

## Question type
`causal_explanation` + `exploratory_survey`

## Mode
`investigate`

## Tool sequence

```python
# Step 1: Broad opinion search
docs = run(ctx, "warrantless cell phone search Fourth Amendment", max_results=10)
# → list of Documents, each with case name + opinion snippet

# Step 2: Planner screens for landmark and circuit-split cases
# (Riley v. California, United States v. Wurie, etc.)

# Step 3: Fetch citation treatment for the key precedent
citing_docs = get_citation_treatment(ctx, "Riley v. California")
# → opinions citing Riley; shows how circuits have applied the ruling

# Step 4 (optional, depth=thorough): fetch full text of top 2–3 opinions
# → hand off to general_web skill using doc.metadata["url"]
```

## Expected document metadata

```json
{
  "source": "courtlistener",
  "title": "Riley v. California",
  "url": "https://www.courtlistener.com/opinion/2812209/riley-v-california/",
  "grade": "B",
  "published_date": "2014-06-25",
  "court": "scotus",
  "skill_id": "courtlistener",
  "skill_version": "0.1.0",
  "fetch_backend": "tier-a"
}
```

## Notes

Riley v. California (2014) is the landmark Supreme Court case establishing the
warrant requirement for cell phone searches.  Use `get_citation_treatment` to
trace how the holding has been applied in the circuits since 2014.  Note the
citation-treatment caveat: state court applications may be under-indexed.
