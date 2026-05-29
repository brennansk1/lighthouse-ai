# Example 1 — Fetch unemployment rate series

**Question:** What is the current U.S. unemployment rate and its recent trend?

**Tool sequence:**
```python
# Find the canonical series
docs = run(ctx, "unemployment rate seasonally adjusted", max_results=3)

# Fetch actual observations for the official series
obs_docs = _bls.fetch_series(["LNS14000000"], start_year="2022", end_year="2025")
```

**Expected output shape:**
- `run`: 1–3 Documents with series metadata (ID, title, URL)
- `fetch_series`: 1 Document with observations like `"2024-M12: 4.1; 2024-M11: 4.2; ..."`

**Notes:**
- `LNS14000000` is the BLS native series ID for the civilian unemployment rate (seasonally adjusted).
- The data is monthly; periods appear as `2024-M12` format.
- For the U-6 broader measure of unemployment, use series `LNS13327709`.
