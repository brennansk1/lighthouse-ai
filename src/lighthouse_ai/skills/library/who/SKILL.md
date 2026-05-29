# WHO (World Health Organization) — Planner Guide

## When to use this skill

WHO is the right primary source when the research question requires
**cross-country, population-level health data** from an internationally
authoritative source: mortality rates, disease prevalence, health system
capacity, vaccine coverage, and outbreak surveillance at global scale.

### Clinical wedge: PubMed vs ClinicalTrials.gov vs WHO

| Unit of research | Right skill | Why |
|---|---|---|
| Published biomedical papers | **PubMed** | Peer-reviewed results, abstracts, MeSH-indexed |
| Registered clinical trials | **ClinicalTrials.gov** | Protocol records, endpoints, enrollment status |
| Cross-country health indicators | **WHO** | Population-level surveillance, ICD codes, outbreak data |

**Use WHO for:**
- Comparing **mortality or morbidity rates** across countries or regions
  (e.g. "maternal mortality per 100,000 live births by country").
- Looking up **ICD code** definitions and hierarchies (ICD-10, ICD-11).
- Tracking **disease outbreaks** — WHO Disease Outbreak News is the
  authoritative international alert source.
- Finding **health system indicators** (hospital bed density, health workforce,
  vaccination coverage) for policy or comparative research.
- Understanding the **global burden of disease** (e.g. total DALYs lost to
  cardiovascular disease by region).
- Cross-country comparisons for Adjudicate mode (multiple countries as
  independent perspective-lenses).

**Do NOT use WHO for:**
- Individual-level or trial-level clinical data (use ClinicalTrials.gov or PubMed).
- U.S.-specific health statistics (use CDC/BLS/Census — not a v1 skill, but
  PubMed + WHO cover the global context).
- Peer-reviewed mechanistic studies (use PubMed).
- Real-time hospital or patient data (WHO data has 1–3 year reporting lags
  for most indicators).

---

## Egress requirement

Neither ``ghoapi.azureedge.net`` nor ``who.int`` is on the default Lighthouse
platform allowlist. This skill loads and degrades gracefully (returns ``[]``
with a logged note) until the user explicitly grants trust:

```
lighthouse trust add ghoapi.azureedge.net
```

---

## Translating a question into a WHO GHO query

The GHO OData API does not support semantic search — it lists ~2,000 indicators
and this skill filters client-side on the indicator name. Query strategy:

1. **Use WHO indicator vocabulary.** Good terms: "maternal mortality",
   "under-5 mortality", "HIV prevalence", "tuberculosis incidence",
   "life expectancy at birth", "vaccination coverage DTP3".
2. **Be specific for rare indicators.** Broad terms like "cancer" match many
   indicators; narrow to "cancer mortality" or "breast cancer incidence" to
   reduce noise.
3. **Country codes for comparison.** For country-specific fetches, use ISO
   3166-1 alpha-3 codes (e.g. "USA", "GBR", "ZAF") in follow-up queries.

---

## Tool playbook

| Task | How to use | Notes |
|---|---|---|
| Find indicators for a topic | `run(ctx, "maternal mortality")` | Returns matching indicator metadata |
| Compare countries on a metric | `run(ctx, "life expectancy")` + inspect country field | Each doc represents a country-indicator pair |
| Watch outbreak indicators | `run_watchable(ctx, "outbreak")` | GHO does not time-filter; dispatcher deduplicates across ticks |
| ICD code lookup | `run(ctx, "ICD-10 code diabetes")` | GHO includes ICD-10/11 classification indicators |

### Country comparison workflow

```
1. run(ctx, "maternal mortality", max_results=5)
   → identify the indicator code (e.g. "MDG_0000000026")
2. Use indicator_code from metadata for follow-up country comparison
3. Each returned Document represents one country's data series
```

---

## Known biases and limitations

1. **Reporting lag.** Most WHO GHO indicators lag 1–3 years behind the
   current date. Do not use for real-time or near-term trend analysis.

2. **Country coverage varies.** High-income countries report more consistently
   than low-income ones. Missing values for a country do not mean the
   indicator is zero — they mean data was not reported.

3. **Indicator granularity.** GHO indicators are national aggregates. For
   subnational or regional data, look for disaggregated supplements or use
   country-specific sources.

4. **Client-side filtering.** This skill filters the full ~2000-indicator list
   client-side. Short or ambiguous query terms (e.g. "rate") will match many
   indicators. Use specific terms to reduce noise.

5. **GHO vs WHO Publications.** GHO is the machine-readable data API. WHO also
   publishes reports (World Health Statistics, Global Burden of Disease
   estimates in partnership with IHME). GHO data is authoritative for the
   indicators it tracks; for narrative context also check WHO publications via
   the general_web skill.

6. **Grade A caveat.** WHO data is grade A as an international authority, but
   the underlying data comes from member-state reports of varying quality.
   For load-bearing claims in contested contexts, cite both WHO as the
   aggregator and the primary source country reports.

---

## Watch mode notes

`run_watchable` uses the GHO indicator search because the GHO OData API does
not expose a time-ordered "new data since X" endpoint. The dispatcher should
track document IDs across ticks to detect genuinely new or updated indicators.

For outbreak monitoring specifically, WHO Disease Outbreak News (DON) at
``who.int/csr/don`` provides the most timely signal — this is not currently
supported by the GHO OData API path but is a documented v1.1 addition.
