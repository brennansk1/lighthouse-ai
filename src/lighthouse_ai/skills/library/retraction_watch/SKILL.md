# Retraction Watch — Planner Guide

## What this skill is (and is not)

Retraction Watch is a **composing utility**, not a destination skill. It is not a place to
start a research question — it is a check you run against papers identified by other academic
skills (arXiv, OpenAlex, PubMed, Crossref) before relying on them as evidence.

**``category = "utility"`` and ``audit_tags = ["composing", "integrity-check"]``**

**Use Retraction Watch for:**
- Checking whether a specific paper (identified by DOI) has been retracted, had an expression
  of concern issued, or has a formal correction.
- Post-survey integrity sweeps: after collecting papers from PubMed or OpenAlex, spot-check
  the most-cited ones for retraction status.
- Clinical or public-health contexts where a retracted paper may have influenced guidelines.
- Nutrition science, social psychology, and cancer biology — historically high retraction rates.

**Do NOT use Retraction Watch as:**
- A primary search tool for finding papers on a topic (use arXiv, OpenAlex, PubMed, Crossref).
- A complete integrity signal: an empty result means "no retraction record found in Crossref
  Labs data," not "confirmed clean." Some retractions, especially in non-English journals,
  may lag the dataset.

---

## How it works

Retraction Watch data is distributed by Crossref Labs (DOI ``10.13003/c23rw1d9``). Each
retraction notice is a separate Crossref-registered DOI linked to the original paper via a
``relation.type:retraction`` + ``relation.object:{original_doi}`` filter on the Crossref
works API. This skill queries that filter path.

### Identifier formats supported

| Identifier | Format | Example |
|---|---|---|
| DOI | bare or ``doi:`` prefix | ``10.1016/s0140-6736(97)11096-0`` |
| DOI URL | https://doi.org/... | ``https://doi.org/10.1038/nature00135`` |
| arXiv ID | ``arxiv:YYMM.NNNNN`` | ``arxiv:2310.00001`` → DOI ``10.48550/arXiv.2310.00001`` |
| PMID | ``pmid:NNNNN`` | Limited support (PMID → DOI mapping not available here) |

For PMID-based lookups, first resolve the PMID to a DOI via PubMed (the ``url`` field in
PubMed documents contains the PubMed URL; the DOI may be in the abstract or Crossref search).

---

## Composing pattern

The intended use is in a pipeline after a primary skill fetch:

```python
# 1. Fetch papers from primary skill
from lighthouse_ai.skills import load_skill, run_skill
from lighthouse_ai.sandbox.broker import build_default_broker

pubmed_skill = load_skill("pubmed")
rw_skill = load_skill("retraction_watch")
broker = build_default_broker(data_dir)

# 2. Run primary search
papers = run_skill(pubmed_skill, "hydroxychloroquine COVID-19 treatment", broker=broker)

# 3. Extract DOIs (from metadata["url"] or crossref lookup) and check each
for paper in papers.documents[:5]:  # spot-check top papers
    # PubMed URL is pubmed.ncbi.nlm.nih.gov/{pmid}/ — need DOI from Crossref
    # For papers where DOI is available in metadata:
    doi = paper.metadata.get("doi", "")
    if doi:
        rw_result = run_skill(rw_skill, doi, broker=broker)
        if rw_result.documents:
            print(f"RETRACTED: {paper.metadata['title']}")
            print(f"  Reason: {rw_result.documents[0].metadata.get('retraction_reason')}")
            print(f"  Date: {rw_result.documents[0].metadata.get('retraction_date')}")
```

---

## Return value semantics

- **Non-empty result**: the paper has a retraction notice (or expression of concern, or
  correction) registered with Crossref Labs. The document metadata contains:
  - ``retracted_doi``: the original paper's DOI
  - ``retraction_doi``: the retraction notice's own DOI
  - ``retraction_date``: date deposited (YYYY-MM-DD)
  - ``retraction_reason``: update type from Crossref (``"retraction"``, ``"correction"``,
    ``"expression_of_concern"``)

- **Empty result**: no retraction record found in the Crossref Labs dataset. This means
  the paper is *probably* not retracted, but absence of evidence is not evidence of absence —
  the dataset covers major English-language journals well, but has gaps.

---

## High-retraction-rate domains

In these fields, running the retraction check on any paper cited as load-bearing evidence is
strongly recommended:

| Domain | Notable cases |
|---|---|
| Cancer biology | Bharat Aggarwal lab, numerous retractions |
| Social psychology | Ego depletion, power pose research (expressions of concern) |
| Nutrition science | Cornell Food and Brand Lab (Brian Wansink) |
| Anesthesiology | Scott Reuben fabrication |
| Clinical trials | Fujii (anesthesia) — 183 retractions |
| COVID-19 (2020–2022) | Surgisphere dataset papers (HCQ Lancet/NEJM) |

---

## Known limitations

1. **Coverage gaps.** Crossref Labs data is derived from publisher cooperation. Some smaller
   journals, preprint servers, and non-English publications may have retractions not yet in
   the dataset.

2. **arXiv papers.** arXiv does not register retraction notices via Crossref; arXiv handles
   withdrawals internally. The ``arxiv:`` identifier path converts to the Crossref DOI for
   the published version (if one exists), but the arXiv preprint itself will not show up here.

3. **Expressions of concern vs retractions.** An expression of concern is a weaker signal
   than a retraction but still warrants scrutiny. Both are returned by this skill.

4. **Date lag.** Crossref Labs updates with some lag after journal-level retraction. Very
   recent retractions may not appear immediately.

5. **Rate limit.** Uses the Crossref API (1 req/s polite pool). Bulk-checking many DOIs
   should be paced accordingly.
