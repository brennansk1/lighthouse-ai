# Example 1 — Fetch GDP growth rate from NIPA

**Question:** What has been U.S. real GDP growth (quarterly, annualized) over the past 3 years?

**Tool sequence:**
```python
# Find the GDP percent change table
tables = _bea.list_nipa_tables()

# Fetch Table 1.1.1 — Percent Change From Preceding Period in Real GDP
docs = _bea.fetch_table("T10101", frequency="Q", year="2022,2023,2024")
```

**Expected output shape:**
- 1–5 Documents with line-level data:
  - `metadata["table_name"]`: `"T10101"`
  - `metadata["line_description"]`: `"Gross domestic product"`, `"Personal consumption expenditures"`, etc.
  - `doc.text`: includes time periods and percent-change values

**Notes:**
- Table T10101 shows percent changes (not levels). For levels use T10105.
- Quarterly data is seasonally adjusted annual rate (SAAR) by default.
