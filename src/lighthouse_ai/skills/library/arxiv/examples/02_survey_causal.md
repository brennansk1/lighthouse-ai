# Example 2 — Survey: "What are the leading approaches to causal representation learning?"

## Question type
`exploratory_survey` + `causal_explanation`

## Mode
`survey`

## Tool sequence

```python
# Step 1: Broad exploratory fetch — use enumerable output for PRISMA funnel
docs = run(ctx, "causal representation learning", max_results=20)

# Step 2: Planner applies inclusion criteria:
#   - Must address unsupervised or weakly-supervised causal structure
#   - Published 2020 or later (check published_date in metadata)
#   - Abstract mentions identifiability or disentanglement

# Step 3: Extract methodology attributes from screened abstracts
#   (supervision level, identifiability conditions, dataset, benchmark)

# Step 4 (optional): targeted follow-up queries for specific sub-approaches
docs_iVAE = run(ctx, "identifiable variational autoencoder causal", max_results=5)
docs_slots = run(ctx, "slot-based causal representation", max_results=5)
```

## Notes

Survey mode works well with arXiv because `output_shape=enumerable` lets the planner
build a PRISMA-style inclusion/exclusion funnel over the abstract corpus.
Return up to 20 results for a broad survey, then narrow with follow-up queries.
Combine with OpenAlex or Semantic Scholar for citation-count ranking when available.
