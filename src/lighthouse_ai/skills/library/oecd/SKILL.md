# OECD Data — Planner Guide

## When to use this skill

OECD is the right primary source for **harmonized comparative statistics across OECD member countries**: productivity comparisons, tax burden analysis, education at a glance, health system spending, labour market indicators, well-being indexes, and better life comparisons. OECD data is especially strong for high-income country comparisons where World Bank data is thinner or less harmonized.

### Economic-data source matrix

| Data type | Right skill | Why |
|---|---|---|
| U.S. macro time series | **FRED** | Faster; U.S.-only |
| U.S. national accounts | **BEA** | Authoritative NIPA |
| U.S. labor/prices | **BLS** | Authoritative labor stats |
| International development | **World Bank** | 200+ economies including low-income |
| Cross-country OECD comparisons | **OECD** | Harmonized for member countries; richest methodology |
| U.S. demographics | **Census** | Block-level; ACS detail |

**Use OECD for:**
- GDP by expenditure, income, and output — comparable across G7/G20
- Labour force statistics: employment, unemployment, hours worked
- Consumer and producer prices across countries
- Productivity and unit labour costs (critical for competitiveness analysis)
- Education at a Glance: enrolment rates, attainment, expenditure
- Health at a Glance: expenditure, outcomes, access
- Revenue Statistics: tax-to-GDP ratio, tax structure comparisons
- Better Life Index: 11 dimensions of well-being
- Pension systems, inequality, social spending

**Do NOT use OECD for:**
- Non-OECD developing countries (use World Bank)
- U.S. detailed granular statistics (use FRED, BLS, BEA, Census)
- Real-time or high-frequency data (OECD publishes annually or quarterly)

---

## Egress requirement

``sdmx.oecd.org`` is NOT on the default Lighthouse platform allowlist.
Run ``lighthouse trust add sdmx.oecd.org`` to enable live fetches.
No API key required.

---

## Translating a question into an OECD query

1. **Search the catalog.** Use `run(ctx, "productivity labour cost")` to find relevant datasets from the curated catalog.
2. **Note the dataset ID.** OECD dataset IDs follow the pattern `AGENCY.COLLECTION,DSD@DATAFLOW,VERSION`.
3. **For live data.** Use `_oecd.fetch_dataset(dataset_id, filter_expression)` to retrieve SDMX observations.
4. **For country comparison.** Use `_oecd.compare_countries(dataset_id, ["USA", "DEU", "JPN"])`.

---

## Tool playbook

| Task | How to use | Notes |
|---|---|---|
| Search datasets | `run(ctx, "labour productivity")` | Curated catalog search |
| Fetch dataset | `_oecd.fetch_dataset("OECD.SDD.NAD,...", filter_expression="USA..")` | SDMX response |
| Compare countries | `_oecd.compare_countries(dataset_id, ["USA", "DEU"])` | Per-country docs |
| List recent releases | `_oecd.list_recent_releases()` | Returns curated catalog |

---

## Known biases and limitations

1. **OECD membership.** Data covers ~38 OECD member countries plus selected partners. Coverage of non-members is limited.
2. **SDMX complexity.** Dataset IDs and filter expressions require knowledge of OECD's SDMX structure. Use `search_dataset` to find the right dataset first.
3. **Annual/quarterly cadence.** Most OECD data is annual; some is quarterly. Real-time tracking requires BLS/FRED.
4. **Harmonization trade-offs.** Harmonization introduces methodological choices that differ from national statistics. For country-specific analysis, prefer the national source (BLS for U.S. labor, etc.).
5. **Coverage gaps in Better Life Index.** Some well-being indicators are survey-based and have lower precision than statistical indicators.
