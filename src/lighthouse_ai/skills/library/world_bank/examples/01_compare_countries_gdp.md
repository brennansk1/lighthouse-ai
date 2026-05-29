# Example 1 — Compare GDP per capita across countries

**Question:** How does GDP per capita compare between the US, China, India, and Germany?

**Tool sequence:**
```python
# Find the GDP per capita indicator
docs = run(ctx, "GDP per capita current US dollars", max_results=3)

# Fetch comparison across countries
comparison_docs = _world_bank.compare_countries(
    "NY.GDP.PCAP.CD",
    ["USA", "CHN", "IND", "DEU"],
    max_results=4,
)
```

**Expected output shape:**
- `run`: 1–3 Documents with indicator metadata (ID `NY.GDP.PCAP.CD`, source note)
- `compare_countries`: up to 4 Documents, one per country with recent values

**Notes:**
- `NY.GDP.PCAP.CD` = GDP per capita in current U.S. dollars (not PPP-adjusted).
- For PPP-adjusted comparison use `NY.GDP.PCAP.PP.CD`.
- World Bank data typically lags 1–2 years; latest available year may be 2022 or 2023.
