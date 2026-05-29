# BEA (Bureau of Economic Analysis) — Planner Guide

## When to use this skill

BEA is the right primary source when the research question requires **national accounts detail**: GDP methodology, NIPA table breakdowns (consumption, investment, government, net exports), personal income and outlays, international trade accounts, or industry-level value-added. BEA is the *originator* of these statistics — FRED redistributes them, but BEA has the authoritative vintages and table structure.

### Economic-data source matrix

| Data type | Right skill | Why |
|---|---|---|
| U.S. macro time series (quick fetch) | **FRED** | Single access point; FRED redistributes BEA series |
| National accounts / GDP detail | **BEA** | Authoritative NIPA tables; BEA controls GDP methodology |
| Employment, CPI, wages (detailed) | **BLS** | Authoritative source for labor statistics |
| International development indicators | **World Bank** | 200+ economies; development focus |
| Cross-country OECD comparisons | **OECD** | Member-country harmonized statistics |
| U.S. demographics / ACS | **Census** | Block-level geography; demographic breakdown |

**Use BEA for:**
- Detailed NIPA table data: Table 1.1.1 (GDP growth rates), Table 2.1 (PCE), Table 3.1 (Federal/State/Local), etc.
- Regional accounts: GDP by state and metro area
- Industry accounts: GDP by industry, input-output tables
- International accounts: trade in goods and services, balance of payments
- Historical vintage comparison: what did BEA report in real-time vs. after revisions (use `fetch_table` with specific year)

**Do NOT use BEA for:**
- Quick series lookup by keyword (use FRED's `search_series`)
- Labor market data (use BLS)
- International development indicators (use World Bank or OECD)
- Demographic data (use Census)

---

## Egress requirement

``apps.bea.gov`` is NOT on the default Lighthouse platform allowlist.
Run ``lighthouse trust add apps.bea.gov`` to enable live fetches.

A free BEA API key is also required. Register at:
https://apps.bea.gov/API/signup/

---

## Translating a question into a BEA query

1. **Identify the dataset.** Is it national accounts (NIPA), regional (Regional), or industry (GDPbyIndustry)?
2. **Find the table name.** NIPA table names follow a pattern: `T10101` (Table 1.1.1 — GDP percent change), `T20306` (Table 2.3.6 — PCE by type). Use `list_nipa_tables` to discover.
3. **Choose frequency.** Annual (`A`), quarterly (`Q`), or monthly (`M`). Not all tables support all frequencies.
4. **Specify year.** `ALL` for full history; `2020,2021,2022,2023` for recent years.

---

## Tool playbook

| Task | How to use | Notes |
|---|---|---|
| Discover datasets | `run(ctx, "GDP national accounts")` | Returns dataset names matching query |
| List NIPA tables | `_bea.list_nipa_tables()` | Returns table catalog |
| Fetch a NIPA table | `_bea.fetch_table("T10101", frequency="Q", year="2020,2021,2022,2023")` | Returns line-level data |
| Industry GDP | `_bea.get_industry_account("ALL")` | GDP by industry, all sectors |

---

## Known biases and limitations

1. **API key required.** Without a key, BEA returns 400 errors. The skill degrades gracefully.
2. **Table name conventions.** NIPA table names are not self-documenting. Use `list_nipa_tables` to map between friendly names and API codes.
3. **Revisions are significant.** BEA revises GDP substantially (especially the annual comprehensive revision every July). For Reconstruct mode, note which vintage you are citing.
4. **Regional data lags.** State and metro GDP data typically lags national by 6–12 months.
5. **Industry classification.** BEA uses its own industry classification, not NAICS directly. Cross-reference with BLS if comparing to employment data.
