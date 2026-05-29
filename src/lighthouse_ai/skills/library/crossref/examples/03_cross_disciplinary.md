# Example 3 — Cross-disciplinary search: "What published work exists on algorithmic fairness in credit scoring?"

## Question type
`exploratory_survey`

## Mode
`survey`

## Tool sequence

```python
# Step 1: Cross-disciplinary keyword search
docs = run(ctx, "algorithmic fairness credit scoring machine learning bias", max_results=10)

# Step 2: Planner screens for doc.metadata["grade"] == "A" (peer-reviewed journal articles)
# and filters out Grade B preprints / datasets

# Step 3: Planner notes publisher diversity:
#   - Finance journals (Journal of Finance, Journal of Banking & Finance)
#   - CS/ML venues (FAccT, NeurIPS, ICML proceedings)
#   - Law reviews (no MeSH available; Crossref reaches them)
# → Cross-disciplinary coverage confirms multi-field engagement with this question

# Step 4 (optional): Check high-cited papers for retraction status
```

## Notes

This is where Crossref outperforms PubMed or arXiv for cross-disciplinary questions: it
covers law reviews, economics journals, CS proceedings, and social science venues in one
search. The trade-off is no citation counts (use OpenAlex for that) and no abstract for
~40% of records.
