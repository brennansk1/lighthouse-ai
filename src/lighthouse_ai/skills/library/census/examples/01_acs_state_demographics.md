# Example 1 — Fetch state-level demographics from ACS

**Question:** What is the median household income and poverty rate for all U.S. states?

**Tool sequence:**
```python
# Get geographic codes (optional: already know state geographies)
geo_docs = _census.query_geographic("state")

# Fetch ACS 5-year data for all states
docs = _census.fetch_acs_table(
    variables=["B19013_001E", "B17001_002E", "B01003_001E"],
    year=2022,
    geography="state",
    geo_id="*",
    max_results=10,
)
```

**Expected output shape:**
- Up to 10 Documents (one per state in the response), each with:
  - `metadata["geo_label"]`: state name (from NAME field)
  - `metadata["B19013_001E"]`: median household income value
  - `metadata["B17001_002E"]`: population below poverty level
  - `metadata["B01003_001E"]`: total population
  - `doc.text`: formatted summary string

**Notes:**
- ACS 5-year 2022 estimates cover 2018–2022 data collection period.
- Values of `-666666666` indicate suppressed data; values of `null` indicate not available.
- For more recent data use 2023 if available; check `search_dataset` for available vintages.
