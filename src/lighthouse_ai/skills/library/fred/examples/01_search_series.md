# Example 1 — Search for a macro series

**Question:** What FRED series track the U.S. unemployment rate?

**Tool sequence:**
```python
docs = run(ctx, "unemployment rate seasonally adjusted", max_results=5)
```

**Expected output shape:**
- 1–5 Documents, each with:
  - `metadata["series_id"]`: e.g. `"UNRATE"`
  - `metadata["title"]`: full series name
  - `metadata["frequency"]`: `"Monthly"`
  - `metadata["units"]`: `"Percent"`
  - `metadata["seasonal_adjustment"]`: `"Seasonally Adjusted"`
  - `metadata["observation_end"]`: most recent data date

**Notes:**
- `UNRATE` is the canonical civilian unemployment rate series.
- Use `_fred.fetch_series("UNRATE")` to retrieve actual observations.
