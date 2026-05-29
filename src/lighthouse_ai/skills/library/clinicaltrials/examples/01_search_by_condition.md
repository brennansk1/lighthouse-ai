# Example 1 — Search trials by condition

**Question:** What phase 3 trials are registered for semaglutide in type 2 diabetes?

**Tool sequence:**
```python
docs = run(ctx, "semaglutide type 2 diabetes phase 3", max_results=5)
```

**Expected output shape:**
- 3–5 Documents, each with:
  - `metadata["nct_id"]`: e.g. `"NCT03989998"`
  - `metadata["title"]`: official trial title
  - `metadata["conditions"]`: `["Type 2 Diabetes Mellitus"]`
  - `metadata["overall_status"]`: `"Completed"` or `"Active, not recruiting"`
  - `metadata["start_date"]`: `"2019-07-01"`
  - `doc.text`: title + brief summary

**Notes:**
- If more detail is needed, use the NCT ID to fetch the full record via a
  separate query: `run(ctx, "NCT03989998", max_results=1)`.
- For endpoint comparison with a published paper, inspect
  `protocolSection.outcomesModule` in the raw ClinicalTrials.gov record.
