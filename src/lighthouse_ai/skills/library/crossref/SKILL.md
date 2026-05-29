# Crossref — Planner Guide

## When to use this skill

Crossref is the **DOI registry** — the authoritative source for metadata about 155M+
scholarly works that have been assigned a Digital Object Identifier (DOI) by their publisher.
It is not primarily a search tool like PubMed or OpenAlex, but it has a strong keyword search
that returns well-structured metadata across all academic disciplines.

**Use Crossref for:**
- Finding authoritative metadata for a paper when you have a partial citation (title fragment,
  author + year) and need the DOI, journal, volume, pages.
- Verifying whether a claimed publication is real and correctly cited.
- Cross-disciplinary literature searches when you need structured publisher/journal metadata.
- Checking DOIs before using them in citations (Crossref is the canonical resolver).
- **Retraction status**: combined with the retraction_watch skill (which uses Crossref Labs
  data), any DOI can be checked for retraction, expression of concern, or correction.
- Funder-linked searches (Crossref indexes funder metadata for many journals).

**Do NOT rely on Crossref for:**
- MeSH-controlled clinical searches — use PubMed for that precision.
- Citation-intent or influential-citation signals — use Semantic Scholar.
- Preprints and grey literature — Crossref covers DOI-registered content only; arXiv papers
  get DOIs only when published in journals.
- Content not registered with DOIs (dissertations, most government reports, conference
  abstracts without proceedings DOIs).

---

## The Retraction Watch Overlay

Crossref Labs hosts the Retraction Watch database as a linked dataset. The retraction_watch
skill uses this path to check whether any DOI has been flagged. The workflow is:

1. Search this skill (Crossref) to identify papers and get their DOIs.
2. Extract the DOI from ``doc.metadata["url"]`` (format: ``https://doi.org/{doi}``).
3. Pass the DOI to the ``retraction_watch`` skill's ``lookup_doi`` tool.
4. If the paper is retracted, the retraction_watch result will contain the retraction notice
   metadata and reason.

This overlay is particularly important for:
- Clinical or public-health papers where a retraction may have influenced guidelines.
- Nutrition science (historically high retraction rate).
- Psychology and social science replication-crisis papers.

---

## Grade assignment

Crossref automatically grades documents based on their Crossref ``type`` field:

| Grade | Types |
|---|---|
| A | ``journal-article``, ``proceedings-article``, ``book-chapter`` |
| B | ``posted-content`` (preprints), ``dataset``, ``report``, ``component``, ``reference-entry``, others |

The grade is in ``doc.metadata["grade"]``. Grade-B documents from Crossref are not
peer-reviewed; treat them similarly to arXiv preprints.

---

## Translating a question into a Crossref query

Crossref keyword search is simpler than PubMed — no field tags or boolean operators in the
public API, just free-text keywords. Crossref's relevance ranking is well-tuned for
publisher-registered content.

| Goal | Query form | Notes |
|---|---|---|
| Topic search | `"CRISPR off-target editing"` | 2-5 key terms work well |
| Author + topic | `"LeCun deep learning review"` | Approximate; verify author field in result |
| Verify a citation | `"Attention is all you need Vaswani 2017"` | Good for citation verification |
| Funder check | `"NIH-funded mRNA vaccine efficacy"` | Returns papers with NIH funder metadata |

---

## Tool playbook

| Task | Entrypoint | Notes |
|---|---|---|
| Search for papers by topic | `run(ctx, question)` | Returns up to `max_results` DOI-registered works |
| Verify a paper's DOI + metadata | `run(ctx, "author title year")` | Useful for citation verification |

### Typical sequence for DOI verification + retraction check

```
1. run(ctx, "partial citation or title", max_results=5)
   # Find the exact paper and retrieve its DOI

2. (planner) extract DOI from doc.metadata["url"] field
   # url format: "https://doi.org/10.1234/journalname.2023.001"

3. (planner) pass DOI to retraction_watch skill
   # retraction_watch.lookup_doi(doi) → retraction record or None
```

---

## Known biases and limitations

1. **DOI registration required.** Crossref only indexes works with DOIs registered by member
   publishers. Many conference proceedings, preprints (unless published), dissertations, and
   government reports have no DOI and are invisible to this skill.

2. **Abstract completeness.** Crossref abstracts are stored as JATS XML and stripped to plain
   text. About 60% of Crossref records include an abstract; the rest return title-only Documents.

3. **No citation counts.** Unlike OpenAlex or Semantic Scholar, Crossref does not expose
   citation counts in the public API. For citation-signal-based ranking, use those skills.

4. **Grade B for posted-content.** Many preprint servers (bioRxiv, medRxiv, SSRN) register
   DOIs through Crossref. These receive Grade B; they are not peer-reviewed. The grade is in
   ``doc.metadata["grade"]`` — always check before using as authoritative evidence.

5. **Publisher metadata quality.** Crossref depends on member publishers submitting accurate
   metadata. Publication dates, author names, and abstracts can be incomplete or malformed for
   older records (pre-2005) or smaller publishers.

6. **Rate limit.** Without the polite-pool ``mailto`` User-Agent, Crossref throttles requests.
   The adapter sends an identifying User-Agent by default; in production set
   ``CROSSREF_MAILTO`` to identify your application.
