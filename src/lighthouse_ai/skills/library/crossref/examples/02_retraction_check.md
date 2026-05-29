# Example 2 — Retraction check: "Is the Wakefield MMR/autism paper retracted?"

## Question type
`factual_lookup`

## Mode
`investigate`

## Tool sequence

```python
# Step 1: Find the paper via Crossref
docs = run(ctx, "Wakefield MMR autism bowel disease 1998 Lancet", max_results=3)

# Step 2: Extract DOI from the result
# doi = "10.1016/s0140-6736(97)11096-0" (from doc.metadata["url"])

# Step 3: Pass to retraction_watch skill for retraction status
# retraction_result = retraction_watch_skill.lookup_doi("10.1016/s0140-6736(97)11096-0")
# → Retracted 2010-02-02 / Reason: "Fraud" (Dr. Wakefield's ethics violations)
```

## Notes

This is the prototypical use of the Crossref + retraction_watch combination. The Wakefield
paper (Lancet, 1998) was retracted in 2010 after investigation by the General Medical Council.
Crossref records the retraction notice; retraction_watch provides the reason code and date.
Any citation of this paper in a survey or investigation should be flagged automatically.
