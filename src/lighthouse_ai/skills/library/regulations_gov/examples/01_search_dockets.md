# Example 1 — Search for dockets on a regulatory topic

**Question:** What rulemaking dockets exist for net neutrality?

**Tool sequence:**
```python
docs = run(ctx, "net neutrality broadband internet", max_results=5)
```

**Expected output shape:**
- 3–5 Documents, each with:
  - `metadata["docket_id"]`: e.g. `"FCC-2023-0056"`
  - `metadata["title"]`: docket title
  - `metadata["docket_type"]`: `"Rulemaking"` or `"Nonrulemaking"`
  - `metadata["agency_id"]`: `"FCC"`
  - `metadata["last_modified"]`: ISO date string
