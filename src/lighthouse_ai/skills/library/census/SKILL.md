# U.S. Census Bureau — Planner Guide

## When to use this skill

Census is the right primary source when the research question requires **U.S. demographic data**: population counts, income, housing, education attainment, poverty, race/ethnicity composition, or geographic-level statistics down to tract or block group. The ACS 5-year estimates provide the most granular sub-national demographic picture available.

### Economic-data source matrix

| Data type | Right skill | Why |
|---|---|---|
| U.S. macro time series | **FRED** | Faster; aggregate-level |
| U.S. national accounts | **BEA** | GDP methodology |
| U.S. labor/prices | **BLS** | Employment statistics |
| International development | **World Bank** | 200+ economies |
| Cross-country OECD comparisons | **OECD** | Member-country harmonized |
| U.S. demographics / ACS | **Census** | Block-level; demographic breakdown |

**Use Census for:**
- Population by state, county, tract, or block group
- Median household income (ACS table B19013)
- Poverty rate by geography (ACS table B17001)
- Housing tenure (owner vs. renter: ACS table B25003)
- Educational attainment (ACS table B15003)
- Unemployment by geography (ACS table B23025)
- Racial/ethnic composition (ACS tables B02001, B03003)
- Decennial census population counts (most recent: 2020)

**Do NOT use Census for:**
- National-level macro aggregates (use FRED or BEA — faster access)
- Business surveys (Economic Census is annual, not ACS)
- International data (use World Bank or OECD)
- Real-time monthly data (ACS is annual; for monthly use BLS)

---

## Egress requirement

``api.census.gov`` is NOT on the default Lighthouse platform allowlist.
Run ``lighthouse trust add api.census.gov`` to enable live fetches.

An API key is optional but recommended (removes IP-based rate limits).
Register at: https://api.census.gov/data/key_signup.html

---

## Translating a question into a Census query

1. **Identify the dataset and year.** ACS 5-year (most stable, available for small geographies) vs. ACS 1-year (more current, only areas 65k+) vs. Decennial (2020).
2. **Identify the variables.** Census variable IDs like `B01003_001E` (total population) must be known or looked up. Use `search_dataset` to discover available datasets, then the Census API variables endpoint for specific variables.
3. **Identify the geography.** Use `query_geographic` to find FIPS codes for states/counties.
4. **Fetch.** Use `fetch_acs_table` with variables and FIPS codes.

---

## Tool playbook

| Task | How to use | Notes |
|---|---|---|
| Search available datasets | `run(ctx, "American Community Survey demographics")` | Returns dataset catalog entries |
| Fetch ACS data | `_census.fetch_acs_table(["B01003_001E", "B19013_001E"], geography="state")` | Returns all states |
| Get decennial data | `_census.fetch_decennial(["P1_001N"], year=2020, geography="state")` | 2020 Census |
| Look up geography | `_census.query_geographic("California")` | Returns FIPS codes |

---

## Known biases and limitations

1. **ACS is sample-based.** ACS estimates have margins of error; 5-year estimates have smaller MOEs than 1-year. For small geographies, always check the MOE in the raw data.
2. **5-year vs. 1-year.** ACS 5-year covers all geographies including tracts; ACS 1-year is only available for areas with 65,000+ population.
3. **Decennial and ACS don't always agree.** They measure different things at different points in time. The 2020 Census used a new Differential Privacy algorithm that affects small-area counts.
4. **Variable naming.** Census variable IDs (e.g., `B19013_001E`) are not self-documenting. Use the Census API variables endpoint or the data.census.gov explorer.
5. **Geographic boundary changes.** FIPS codes and tract boundaries can change between census years. For longitudinal analysis, note the vintage year.
