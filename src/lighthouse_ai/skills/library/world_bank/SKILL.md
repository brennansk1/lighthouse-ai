# World Bank Open Data — Planner Guide

## When to use this skill

World Bank is the right primary source when the research question requires **international development indicators** across multiple countries: GDP per capita comparisons, poverty rates, education attainment, health expenditure, infrastructure, environmental data, and governance. World Bank compiles data from 200+ economies and is the standard reference for cross-country development research.

### Economic-data source matrix

| Data type | Right skill | Why |
|---|---|---|
| U.S. macro time series | **FRED** | Faster access; U.S.-only |
| U.S. national accounts detail | **BEA** | Authoritative NIPA |
| U.S. labor/prices | **BLS** | Authoritative labor stats |
| International development | **World Bank** | 200+ economies; development focus |
| OECD-country comparisons | **OECD** | Richer methodology for wealthy-country comparisons |
| U.S. demographics | **Census** | Block-level; ACS detail |

**Use World Bank for:**
- GDP, GDP per capita, GDP growth across countries (NY.GDP.MKTP.CD, NY.GDP.PCAP.CD)
- Poverty headcount ratios (SI.POV.DDAY)
- Life expectancy, child mortality, maternal mortality (SP.DYN.LE00.IN, SH.DYN.MORT)
- School enrollment, literacy rates (SE.PRM.ENRR, SE.ADT.LITR.ZS)
- Access to electricity, safe water, internet (EG.ELC.ACCS.ZS, SH.H2O.SMDW.ZS)
- CO2 emissions, forest coverage (EN.ATM.CO2E.PC)
- Country metadata: region, income level, capital city

**Do NOT use World Bank for:**
- U.S.-specific detailed statistics (use FRED, BEA, BLS, Census)
- OECD-member detailed comparisons with richer methodology (use OECD)
- Real-time data (World Bank data typically lags 1–3 years)

---

## Egress requirement

``api.worldbank.org`` is NOT on the default Lighthouse platform allowlist.
Run ``lighthouse trust add api.worldbank.org`` to enable live fetches.
No API key required.

---

## Translating a question into a World Bank query

1. **Identify the indicator.** World Bank indicators have codes like `NY.GDP.MKTP.CD` (GDP, current USD). Use `search_indicator` with keywords.
2. **Specify the country.** Use ISO 3166-1 alpha-3 codes: `USA`, `CHN`, `DEU`, `IND`, or `WLD` for world aggregate.
3. **For comparisons.** Use `compare_countries` with a list of country codes.
4. **Topic browsing.** Use `list_indicators_by_topic(topic_id)` to browse: 3=Economy, 5=Education, 8=Health, 19=Poverty.

---

## Tool playbook

| Task | How to use | Notes |
|---|---|---|
| Search indicators | `run(ctx, "GDP per capita")` | Returns matching indicator metadata |
| Fetch indicator for one country | `_world_bank.fetch_indicator("NY.GDP.PCAP.CD", "USA")` | 10 most recent values |
| Compare countries | `_world_bank.compare_countries("SP.DYN.LE00.IN", ["USA", "CHN", "IND"])` | One doc per country |
| Browse by topic | `_world_bank.list_indicators_by_topic(8)` | Topic 8 = Health |
| Get country metadata | `_world_bank.get_country_metadata("BRA")` | Region, income level, capital |

---

## Known biases and limitations

1. **Data lags.** World Bank data typically lags 1–3 years behind the present. For 2023 data, check if 2023 is available or if the latest is 2022/2021.
2. **Coverage gaps.** Small countries and conflict-affected states have sparse data. Missing values appear as `null` in the API response.
3. **Methodological differences.** Countries report with different methodologies; World Bank harmonizes where possible but comparability is never perfect. Always note the indicator's methodology in output.
4. **Population-weighted aggregates.** World averages (WLD) are population-weighted. Use regional aggregates (e.g., `SSA` for Sub-Saharan Africa) for geographic groupings.
5. **Historical revisions.** World Bank revises historical data when countries submit corrected statistics. Note the access date in output.
