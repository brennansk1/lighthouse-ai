# Example 2 — Fetch series and compare

**Question:** Compare real GDP growth and unemployment over the past 5 years.

**Tool sequence:**
```python
# Get series metadata for comparison
docs = _fred.compare_series(["GDPC1", "UNRATE"])

# Fetch actual observations
gdp_docs = _fred.fetch_series("GDPC1")
unemp_docs = _fred.fetch_series("UNRATE")
```

**Expected output shape:**
- `compare_series`: 2 Documents with metadata (units, frequency, observation_end)
- `fetch_series`: 1 Document per series with last 10 observations in text

**Notes:**
- GDPC1 = Real Gross Domestic Product (seasonally adjusted annual rate, billions of chained 2017 dollars)
- UNRATE = Unemployment Rate (seasonally adjusted, percent)
- These series have different frequencies (quarterly vs. monthly); document this in output.
