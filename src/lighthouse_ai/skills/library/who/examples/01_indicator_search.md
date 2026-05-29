# Example 1 — Search WHO indicators by topic

**Question:** What WHO health indicators are available for maternal mortality?

**Tool sequence:**
```python
docs = run(ctx, "maternal mortality", max_results=5)
```

**Expected output shape:**
- 3–5 Documents, each with:
  - `metadata["indicator_code"]`: e.g. `"MDG_0000000026"`
  - `metadata["title"]`: full indicator name, e.g. "Maternal mortality ratio
    (per 100 000 live births)"
  - `metadata["source"]`: `"who"`
  - `metadata["grade"]`: `"A"`
  - `doc.text`: the indicator name (short text — indicator metadata only)

**Notes:**
- Indicator codes can be used to fetch time-series data for specific countries.
- WHO GHO has ~2000 indicators; the query filters on name keywords, so shorter
  queries return more (possibly less relevant) results.
