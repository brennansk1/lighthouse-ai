# PubMed — Planner Guide

## When to use this skill

PubMed is the **clinical evidence wedge** — the right primary source when the question concerns
biomedical research, pharmacology, epidemiology, public health, clinical practice, or life
science. It indexes ~36M citations from MEDLINE and related life-science journals, with full
NCBI curation including MeSH vocabulary and publication-type tagging.

**Use PubMed for:**
- Clinical questions: drug efficacy, treatment comparisons, safety profiles, dosing.
- Epidemiological questions: disease prevalence, risk factors, population health.
- Systematic reviews and meta-analyses on biomedical topics.
- Finding randomized controlled trials (the gold standard for clinical evidence).
- Public health questions: vaccines, infectious disease, occupational health.
- Neuroscience, genetics, molecular biology, pharmacology.

**Do NOT rely on PubMed for:**
- Computer science, physics, mathematics, or engineering — use arXiv or OpenAlex.
- Social science without a clinical angle — use OpenAlex instead.
- Legal, regulatory, or policy documents — use Federal Register / CourtListener.
- Grey literature (preprints, dissertations) — PubMed indexes published journals only.

---

## MeSH Terms + Publication Type: The Clinical Wedge

This is the most important concept in using PubMed well. MeSH (Medical Subject Headings) is
the NLM's controlled vocabulary for indexing articles — it lets you find papers about a
concept even when authors use different terminology.

### MeSH field tags

| Field tag | Meaning | Example |
|---|---|---|
| `[mh]` | MeSH heading | `"diabetes mellitus[mh]"` |
| `[tiab]` | Title / abstract | `"glycemic control[tiab]"` |
| `[pt]` | Publication type | `"randomized controlled trial[pt]"` |
| `[dp]` | Date published (YYYY/MM/DD) | `"2020/01/01:2024/01/01[dp]"` |
| `[au]` | Author | `"Smith J[au]"` |
| `[ta]` | Journal title abbreviation | `"NEJM[ta]"` |

### Publication type filters — separating evidence quality

The ``[pt]`` tag is the most powerful quality filter. Use it to narrow to specific study designs:

| Publication type tag | Evidence level | When to use |
|---|---|---|
| `"randomized controlled trial[pt]"` | Level 1 | Drug/intervention efficacy |
| `"meta-analysis[pt]"` | Level 1 (synthesis) | Pooled effect sizes, systematic reviews |
| `"systematic review[pt]"` | Level 1 (synthesis) | Comprehensive literature summaries |
| `"clinical trial[pt]"` | Level 2 | Any prospective clinical trial |
| `"cohort studies[pt]"` | Level 3 | Observational longitudinal studies |
| `"case-control studies[pt]"` | Level 3 | Retrospective exposure-outcome |
| `"review[pt]"` | Narrative | Background, not primary evidence |

**The clinical evidence hierarchy**: meta-analyses > RCTs > cohort studies > case-control >
case series > expert opinion. A question about drug efficacy should prioritize RCTs and
meta-analyses; a question about rare adverse events may require case reports.

### Example query translations

| Clinical question | PubMed query |
|---|---|
| RCTs on metformin for T2DM | `"metformin[mh] AND diabetes mellitus, type 2[mh] AND randomized controlled trial[pt]"` |
| COVID-19 vaccine safety meta-analyses | `"COVID-19 vaccines[mh] AND meta-analysis[pt]"` |
| SSRI adverse effects in adolescents | `"antidepressive agents[mh] AND adolescent[mh] AND adverse effects[tiab]"` |
| Recent trials on GLP-1 agonists | `"glucagon-like peptide-1 receptor agonists[mh] AND clinical trial[pt] AND 2020:2024[dp]"` |

---

## Tool playbook

| Task | Entrypoint | Notes |
|---|---|---|
| Search for articles by topic | `run(ctx, question)` | PubMed syntax supported; returns title + abstract |
| Watch for new publications | `run_watchable(ctx, query, since=checkpoint)` | Filters client-side by published_date > since |

### Typical sequence for clinical Investigate / Survey

```
1. run(ctx, "keyword[mh] AND pub_type[pt]", max_results=10)
   # MeSH + pub-type narrows to relevant, high-quality papers

2. (planner) rank by evidence level (meta-analysis > RCT > cohort)
   # Publication type is in the abstract; check for "randomized", "meta-analysis" keywords

3. (planner) check for systematic review / Cochrane Review hits
   # These are the most authoritative synthesis sources

4. (optional) cross-check retraction status via retraction_watch skill
   # PMIDs are in doc.id (format: "pubmed:12345678")
```

### Extracting PMID for cross-tool use

Every document returned has `id` in the format `"pubmed:PMID"`. Strip the prefix to get the
raw PMID for passing to retraction_watch or ClinicalTrials.gov lookups:

```python
pmid = doc.id.split("pubmed:", 1)[-1]  # e.g. "38245678"
```

---

## Watch mode notes

`run_watchable` is best combined with a ``[dp]`` date range appended to the query string for
server-side pre-filtering on longer cadences (e.g. weekly):

```
"metformin AND randomized controlled trial[pt] AND 2024/04/01:3000[dp]"
```

This ensures PubMed only returns articles indexed after the cutoff date, supplementing the
client-side filter. Without ``[dp]``, the relevance-sorted results may not surface very recent
papers that haven't accumulated citations yet.

Recommended cadence: weekly for active clinical research areas.

---

## Known biases and limitations

1. **Biomedical scope only.** PubMed is authoritative for medicine and life science; it has
   virtually no coverage of CS, economics, social science, or humanities.

2. **English-language bias.** MEDLINE indexes primarily English-language journals, with some
   non-English content. International clinical trials in other languages may be missed.

3. **Publication bias.** Like all journal-based indexes, PubMed over-represents positive
   results. Null findings and replication failures are less likely to be published. A
   meta-analysis should ideally include a funnel-plot asymmetry check.

4. **Structured abstract variability.** PubMed efetch returns structured abstracts with
   section labels (Background, Methods, Results, Conclusions) for many journals. The adapter
   concatenates these with labels, so the text field may read:
   ``"Background: ... Methods: ... Results: ... Conclusions: ..."``

5. **Date precision.** Published dates are sometimes year-only (``"2023"``) or month-year
   (``"2023-Mar"``). The watchable filter handles partial dates but with lower precision.

6. **Rate limit.** Without an NCBI API key, PubMed allows 3 requests/second. With an API
   key (free, register at NCBI), the limit rises to 10 req/s. Set ``NCBI_API_KEY`` to avoid
   throttling on large surveys.
