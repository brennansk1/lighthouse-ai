# BLS (Bureau of Labor Statistics) — Planner Guide

## When to use this skill

BLS is the right primary source when the research question involves **U.S. labor market data** (employment, unemployment, job openings, layoffs), **price indexes** (CPI, PPI, PCE price deflators), **productivity**, **wages**, or **occupational statistics**. BLS is the originator of these statistics — FRED redistributes them, but BLS has the authoritative granularity.

### Economic-data source matrix

| Data type | Right skill | Why |
|---|---|---|
| U.S. macro time series (quick fetch) | **FRED** | Single access point; redistributes BLS series |
| Employment, CPI, wages (detail) | **BLS** | Authoritative source; more granular; occupation data |
| National accounts / GDP | **BEA** | Authoritative for GDP methodology |
| International development indicators | **World Bank** | 200+ economies |
| Cross-country OECD comparisons | **OECD** | Harmonized member-country stats |
| U.S. demographics / ACS | **Census** | Block-level; demographic breakdown |

**Use BLS for:**
- Current Employment Statistics (CES): nonfarm payrolls by industry, hours, earnings
- Labor Force Statistics (CPS): unemployment rate (U-3), underemployment (U-6), labor force participation
- Consumer Price Index (CPI-U, CPI-W, chained CPI): headline and core inflation
- Producer Price Index (PPI): upstream price pressures
- Productivity (nonfarm business, manufacturing): output per hour, unit labor costs
- Occupational Employment and Wage Statistics (OES): median wages by occupation
- Job Openings and Labor Turnover Survey (JOLTS): openings, hires, quits, layoffs
- American Time Use Survey (ATUS)

**Do NOT use BLS for:**
- GDP and national accounts (use BEA)
- International comparisons (use OECD for labor, World Bank for development)
- U.S. demographic cross-sections (use Census)

---

## Egress requirement

``api.bls.gov`` is NOT on the default Lighthouse platform allowlist.
Run ``lighthouse trust add api.bls.gov`` to enable live fetches.

An API key is optional but recommended (500 requests/day vs. 10 without).
Register at: https://data.bls.gov/registrationEngine/

---

## Translating a question into a BLS query

1. **Identify the series.** Know the BLS series ID if possible: `UNRATE` is a FRED alias; the BLS native ID is `LNS14000000`. Use `search_series` with keywords to find canonical IDs.
2. **Use `fetch_series` with the ID directly.** BLS series IDs are stable: `CES0000000001` (total nonfarm payrolls), `CUUR0000SA0` (CPI-U all items).
3. **Date range matters.** Specify `start_year`/`end_year` to limit the response. BLS API returns up to 20 years.
4. **Seasonal adjustment.** CES and CPS series come in SA (seasonally adjusted) and NSA variants. For policy/media use SA.

---

## Tool playbook

| Task | How to use | Notes |
|---|---|---|
| Find series by keyword | `run(ctx, "unemployment rate")` | Curated catalog search; returns series IDs |
| Fetch observations | `_bls.fetch_series(["LNS14000000"])` | POST to BLS API; returns last 10 quarters |
| Compare geographies | `_bls.compare_geographies(["LAUMT062076000000003", "LAUMT364563000000003"])` | State/metro unemployment series |
| Get occupation wages | `_bls.get_occupation_data("software developer")` | Returns OES series stubs |
| Watch surveys | `run_watchable(ctx, "employment")` | Lists BLS surveys |

---

## Known biases and limitations

1. **Series IDs are not self-documenting.** `CUUR0000SA0` is CPI-U All Items; you need the BLS series ID documentation to know this.
2. **No server-side text search.** BLS API has no keyword search; the skill uses a curated catalog. For obscure series, use the BLS website to find the series ID first.
3. **20-year data limit.** BLS API returns at most 20 years per request. For longer histories use FRED.
4. **Area code structure.** Metro and state unemployment series have complex ID formats (LAUS program). Use `compare_geographies` with known IDs or look up FIPS codes from Census.
5. **OES data lags.** Occupational wage data is published annually (typically May for the prior year).
