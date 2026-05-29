# Example 2 — Outcome-switching detection

**Question:** Did the LEADER trial (NCT01179048) report the same primary
endpoint in the published paper as in the pre-registered protocol?

**Tool sequence:**
```python
# 1. Fetch the registered protocol record
docs = run(ctx, "NCT01179048", max_results=1)

# 2. Check metadata for registered endpoints
doc = docs[0]
# doc.text contains title + brief summary
# For detailed endpoint comparison, the full record is at:
#   https://clinicaltrials.gov/study/NCT01179048

# 3. Cross-reference with PubMed for the published paper's primary endpoint
# (use the PubMed skill for the paper side)
```

**Expected output shape:**
- 1 Document with:
  - `metadata["nct_id"]`: `"NCT01179048"`
  - `metadata["title"]`: "Liraglutide Effect and Action in Diabetes: Evaluation of Cardiovascular Outcome Results"
  - `metadata["overall_status"]`: `"Completed"`

**Notes:**
- The v2 API includes `protocolSection.outcomesModule.primaryOutcomes` with
  the registered endpoint measure and time frame.
- Outcome-switching is a high-stakes claim; document both the registered and
  reported endpoints explicitly, with NCT ID and PMID.
