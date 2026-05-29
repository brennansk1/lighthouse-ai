# Example 1 — Compare labour productivity across OECD countries

**Question:** How does labour productivity compare between the US, Germany, Japan, and France?

**Tool sequence:**
```python
# Find relevant dataset
docs = run(ctx, "labour productivity unit labour cost", max_results=3)

# Fetch dataset with country filter
comparison_docs = _oecd.compare_countries(
    "OECD.SDD.NAD,DSD_NAMAIN1@DF_TABLE14A,1.0",
    ["USA", "DEU", "JPN", "FRA"],
    max_results=4,
)
```

**Expected output shape:**
- `run`: 1–3 Documents with dataset metadata (ID, title)
- `compare_countries`: up to 4 Documents with per-country time series

**Notes:**
- Labour productivity is measured as real GDP per hour worked.
- OECD data is typically annual; most recent year may lag 1–2 years.
- For unit labour costs (a competitiveness measure), the same dataset includes ULC series.
