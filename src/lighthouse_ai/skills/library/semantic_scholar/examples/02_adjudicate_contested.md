# Example 2 — Adjudicate: "Is the 'ego depletion' effect real? Find supporting and challenging papers."

## Question type
`causal_explanation` (contested)

## Mode
`adjudicate`

## Tool sequence

```python
# Step 1: Find papers on both sides
docs = run(ctx, "ego depletion willpower self-control resource model replication", max_results=10)

# Step 2: Planner uses citation counts to assess community weight
# Expected: original Baumeister et al. (1998) → high citations but many contrasting
# Hagger et al. (2016) meta-analysis supporting → moderate citations
# Inzlicht & Friese (2019) critical review → growing contrasting citations

# Step 3: Planner notes the "replication" papers specifically
# Papers with "replication" or "failed to replicate" in title = contrasting evidence

# Step 4: Planner cross-references with OpenAlex for affiliation independence
# (Are the supportive papers all from Baumeister's network?)
```

## Notes

This is the prototypical citation-velocity adjudication case. Ego depletion has a large
original-paper citation count but the *direction* of citations has shifted toward contrasting
over time. Semantic Scholar's citation_count provides the raw signal; the planner needs to
interpret trends. For citation-intent breakdown by direction, use the S2 paper URL from
metadata to fetch the paper's citation page.
