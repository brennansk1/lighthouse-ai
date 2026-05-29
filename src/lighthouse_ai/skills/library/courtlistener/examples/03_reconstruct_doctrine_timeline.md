# Example 3 — Reconstruct: "How did Chevron deference evolve from 1984 to its overruling?"

## Question type
`timeline_reconstruction`

## Mode
`reconstruct`

## Tool sequence

```python
# Step 1: Search for all Chevron-related opinions across the period
docs = run(ctx, "Chevron deference administrative law", max_results=20)
# → list of Documents with date_filed, allowing chronological ordering

# Step 2: Get citation treatment for Chevron U.S.A. v. Natural Resources Defense Council
citing_docs = get_citation_treatment(ctx, "Chevron U.S.A. v. Natural Resources Defense Council")
# → cases applying, limiting, or distinguishing Chevron over four decades

# Step 3: Search for the overruling
overruling_docs = run(ctx, "Loper Bright Enterprises v. Raimondo Chevron overruled", max_results=5)
# → 2024 SCOTUS opinion overruling Chevron

# Step 4 (planner): Sort all docs by published_date to build the timeline
# Reconstruct mode consumes the temporal signal from date_filed metadata
```

## Expected output shape

A chronological list of Documents spanning 1984–2024, each with `date_filed`
and `court` metadata, enabling the planner to reconstruct the doctrinal arc from
Chevron's adoption through its circuit elaboration to its eventual overruling.

## Notes

This is a textbook Reconstruct use case: `temporal_tools=true` and `output_shape=enumerable`
together give the mode engine a date-ordered corpus to work with.  Note that
`get_citation_treatment` will be most complete for the Supreme Court precedents;
lower-court applications from the 1980s–1990s may have gaps in CourtListener's index.
