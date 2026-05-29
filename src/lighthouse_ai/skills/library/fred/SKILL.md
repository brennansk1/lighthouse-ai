# FRED (St. Louis Fed) — Planner Guide

## When to use this skill

FRED is the right primary source when the research question involves **U.S. macroeconomic time series**: GDP, unemployment, inflation (CPI/PCE), interest rates, money supply, housing, trade, and hundreds of other official series sourced from the Fed, BLS, BEA, Census, Treasury, and other agencies. FRED redistributes these series with consistent identifiers and vintage tracking.

### Economic-data source matrix

| Data type | Right skill | Why |
|---|---|---|
| U.S. macro time series (any agency) | **FRED** | Single access point for 800,000+ series; point-in-time vintages; release calendar |
| National accounts / GDP detail | **BEA** | Authoritative NIPA tables; BEA controls GDP methodology |
| Employment, CPI, wages (detailed) | **BLS** | Authoritative source; more granular series and occupation data |
| International development indicators | **World Bank** | 200+ economies; development focus |
| Cross-country OECD comparisons | **OECD** | Member-country harmonized statistics |
| U.S. demographics / ACS | **Census** | Block-level geography; demographic breakdown |

**Use FRED for:**
- Finding and fetching any U.S. macro time series by keyword (GDP, PCE, CPI, FFR, M2, housing starts, etc.)
- Comparing multiple series on the same time axis (e.g., unemployment vs. GDP growth)
- Getting point-in-time vintage data — what did the BEA report for Q3 GDP *at the time of the first release* vs. the third revision?
- Watching for new data releases across any FRED-hosted series via the release calendar
- Exploring series relationships: find all series in a FRED release (e.g., "Employment Situation")

**Do NOT use FRED for:**
- Detailed NIPA table breakdowns (use BEA directly)
- Occupational wage statistics (use BLS)
- International series (use World Bank or OECD)
- U.S. demographic cross-sections (use Census)

---

## Egress requirement

``api.stlouisfed.org`` is NOT on the default Lighthouse platform allowlist.
This skill loads and degrades gracefully (returns ``[]`` with a logged note)
until the user explicitly grants trust:

```
lighthouse trust add api.stlouisfed.org
```

A free FRED API key is also required. Register at:
https://fred.stlouisfed.org/docs/api/api_key.html

Set the key:
```
lighthouse config set fred.api_key YOUR_KEY
```

---

## Translating a question into a FRED query

1. **Identify the series.** Is it a named series ("unemployment rate", "federal funds rate", "real GDP")? Use `search_series` with those keywords.
2. **Use the series ID directly.** FRED series IDs are stable identifiers: `UNRATE`, `GDPC1`, `FEDFUNDS`, `CPIAUCSL`. If you know the ID, use `fetch_series` directly.
3. **Seasonal adjustment matters.** Many series come in SA (seasonally adjusted) and NSA variants. For policy work use SA; for raw comparisons use NSA.
4. **Vintage data for point-in-time.** Use `get_revisions` to see when a series was revised; use the FRED Alfred interface for actual vintage values.

---

## Tool playbook

| Task | How to use | Notes |
|---|---|---|
| Find series by keyword | `run(ctx, "unemployment rate seasonally adjusted")` | Returns matching series metadata |
| Fetch observations | `_fred.fetch_series("UNRATE")` | Returns last 10 obs in text |
| Compare series | `_fred.compare_series(["UNRATE", "GDPC1"])` | Returns metadata doc per series |
| Get revision history | `_fred.get_revisions("GDP")` | Lists vintage dates |
| Watch for new releases | `run_watchable(ctx, "employment")` | Lists FRED releases |

### Point-in-time analysis (Reconstruct mode)

For Reconstruct questions ("what did the data show at the time of the decision"):
1. Use `get_revisions(series_id)` to see the vintage date list.
2. The first vintage date is the initial release; subsequent dates are revisions.
3. Document which vintage was available at the time of the decision.

---

## Known biases and limitations

1. **FRED redistributes, doesn't originate.** For methodology questions always trace back to the source agency (BLS, BEA, Census, etc.).
2. **Not all series are updated equally.** Some series have annual updates; others are monthly or weekly. Check `observation_end` in metadata.
3. **Seasonal adjustment caveat.** Always note whether a series is seasonally adjusted in output; comparing SA with NSA is a common error.
4. **Discontinued series.** FRED preserves discontinued series; check `observation_end` — if it's years in the past the series may be defunct.
5. **API key required.** Without a key, FRED returns 400 errors. The skill degrades gracefully.

---

## Watch mode notes

`run_watchable` lists FRED releases. The Watch tick deduplicates against prior
results using document IDs. New releases appear as new Documents. For
specific series, set up a Watch on the series ID and poll `fetch_series`.

Typical Watch cadence: daily for high-frequency series (Fed funds rate, jobless
claims), weekly for medium-frequency (payrolls, CPI), monthly for slow-moving.
