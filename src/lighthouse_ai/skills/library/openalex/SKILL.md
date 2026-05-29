# OpenAlex — Planner Guide

## When to use this skill

OpenAlex is the right primary source for **peer-reviewed academic literature** across
essentially every discipline — sciences, social sciences, humanities, economics, engineering,
and clinical medicine. With 250M+ indexed works and rich metadata (citation counts, institutional
affiliations, concept taxonomy, open-access links), it is the broadest-coverage academic graph
available without a paid subscription.

**Use OpenAlex for:**
- Surveying published, peer-reviewed evidence on any academic topic.
- Identifying highly-cited foundational papers (``cited_by`` metadata).
- Resolving **source independence**: the affiliation metadata lets you flag papers from the
  same institution or funder — a cluster of papers from one lab on one side of a debate is
  not independent evidence (authority=peer_reviewed, but affiliation = independence signal).
- Cross-domain literature sweeps: unlike arXiv (CS/physics/math-heavy) or PubMed
  (biomedical-only), OpenAlex covers all fields.
- PRISMA-style systematic reviews (output_shape=enumerable, suitable for Survey mode).
- Finding open-access versions of paywalled papers (check ``url`` metadata).

**Do NOT rely on OpenAlex for:**
- Preprints or grey literature — OpenAlex indexes primarily journal articles and proceedings.
  For cutting-edge ML/CS work, arXiv is better (preprints often precede journal publication by months).
- Full text — results are title + reconstructed abstract only. For full text, use the ``url``
  metadata with the general_web skill.
- Citation-intent classification (who cites whom and *how*) — use Semantic Scholar for that signal.
- Breaking news or current events.

---

## Affiliation as an Independence Signal

OpenAlex's institutional affiliation metadata is one of the most underused signals for source
independence. When assessing evidence quality in Adjudicate or Survey mode:

1. Check the ``institution`` field on documents in the corpus.
2. If multiple papers supporting a position share an institution or funder, flag this:
   **same-lab papers are correlated, not independent**.
3. Diversity of institution + geography + funding source strengthens a claim considerably.
4. Use the ``cited_by`` count as a secondary signal: highly-cited papers have been subjected
   to more community scrutiny.

---

## Translating a question into an OpenAlex query

OpenAlex supports free-text search over titles and abstracts. There is no structured
field-prefix syntax on the public search endpoint (unlike arXiv's ``cat:`` / ``au:`` prefixes),
so phrase queries and keyword combinations are the main tools:

| Goal | Query form | Notes |
|---|---|---|
| Broad topic | `"mRNA vaccines efficacy"` | Free-text, relevance-sorted |
| Specific concept | `"transformer attention mechanism"` | Works best with 2-3 key terms |
| Author-like search | `"LeCun deep learning"` | No ``au:`` prefix; use author + topic |
| Institution focus | `"MIT CSAIL reinforcement learning"` | Approximate; check affiliations in results |

### Query translation tips

- Start with 3-5 key terms. OpenAlex relevance ranking is strong.
- For clinical questions, prefer PubMed which supports MeSH term expansion for precision.
- For citation-graph traversal questions, hand off to Semantic Scholar after this skill
  identifies the seed papers.

---

## Tool playbook

| Task | Entrypoint | Notes |
|---|---|---|
| Search for papers by topic | `run(ctx, question)` | Returns up to `max_results` works (title + abstract) |
| Watch for new publications | `run_watchable(ctx, query, since=checkpoint)` | Filters client-side by `published_date > since` |

### Typical sequence for Investigate / Survey

```
1. run(ctx, question, max_results=10)         # fetch candidate papers
2. (planner) check affiliations for independence clusters
3. (planner) rank by cited_by count (foundational work) + recency
4. (planner) fetch full text via general_web skill for top 2–3 papers
```

For Survey mode the enumerable corpus feeds the PRISMA funnel directly —
screen titles/abstracts, apply inclusion criteria, extract study designs.

---

## Watch mode notes

`run_watchable` fetches recent works matching the query and filters by `published_date > since`.
The OpenAlex API sorts by relevance rather than by date on the free endpoint, so the `since=`
filter is applied client-side. This means some very recently published papers may be missed if
they rank lower than older papers. Increase `max_results` to improve coverage.

Recommended cadence: weekly (OpenAlex indexes at publication; daily is rarely necessary).

---

## Known biases and limitations

1. **Abstract-only.** Returns title + reconstructed abstract (from OpenAlex's inverted index).
   Full text requires a separate fetch.

2. **No grey literature.** Preprints, technical reports, and working papers are largely absent.
   Supplement with arXiv for CS/physics or SSRN for economics/law.

3. **Reconstructed abstract quality.** OpenAlex stores abstracts as an inverted index; the
   reconstruction can occasionally misorder words in dense technical abstracts. Verify against
   the source if an abstract seems garbled.

4. **Field imbalance.** Coverage is broadest for natural sciences and medicine; social science
   and humanities coverage, while growing, is less complete than Scopus or Web of Science.

5. **Affiliation metadata completeness.** Affiliation data is present for most but not all
   papers. Absence of affiliation data does not mean the paper is independent; it may just be
   uncurated. Use it as a positive signal when present, not a negative signal when absent.

6. **Rate limit.** Without the ``mailto`` polite-pool parameter, the API limits to ~10 req/s.
   The adapter passes a default mailto; in production use ``OPENALEX_MAILTO`` to identify your
   application.
