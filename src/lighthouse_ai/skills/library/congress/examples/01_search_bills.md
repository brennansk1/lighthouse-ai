# Example 1 — Search bills on a topic

**Question:** What bills on clean energy tax credits were introduced in the 118th Congress?

**Tool sequence:**
```python
docs = run(ctx, "clean energy tax credits investment", max_results=5)
```

**Expected output shape:**
- 3–5 Documents, each with:
  - `metadata["bill_type"]`: `"HR"` or `"S"`
  - `metadata["bill_number"]`: e.g. `"5376"`
  - `metadata["congress"]`: `"118"`
  - `metadata["origin_chamber"]`: `"House"` or `"Senate"`
  - `metadata["latest_action_date"]`: ISO date
  - `metadata["latest_action_text"]`: e.g. `"Became Public Law No: 117-169"`

**Notes:**
- A bill showing "Became Public Law" was enacted. Most bills die in committee.
- To get the full bill text, use the GovInfo skill (PLAW or BILLS collection).
