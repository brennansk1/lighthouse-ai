# Example 1 — Search EPA rules on clean air

**Question:** What rules has the EPA proposed or finalized for air quality standards recently?

**Tool sequence:**
```python
docs = run(ctx, "EPA clean air standard 2024", max_results=5)
```

**Expected output shape:**
- 3–5 Documents, each with:
  - `metadata["document_number"]`: e.g. `"2024-05678"`
  - `metadata["title"]`: e.g. `"National Ambient Air Quality Standards for Particulate Matter"`
  - `metadata["document_type"]`: `"Rule"` or `"Proposed Rule"`
  - `metadata["agency_names"]`: `["Environmental Protection Agency"]`
  - `metadata["publication_date"]`: `"2024-02-07"`
  - `doc.text`: title + abstract

**Notes:**
- To track the NPRM→final lifecycle, use `track_rulemaking("particulate matter NAAQS")`.
- For comments filed on the rule, switch to the `regulations_gov` skill with the
  docket ID found in the FR document (look for "Docket No." in the abstract).
