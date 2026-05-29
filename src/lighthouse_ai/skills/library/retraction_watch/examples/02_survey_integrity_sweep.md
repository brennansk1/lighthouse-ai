# Example 2 — Survey integrity sweep: "After collecting COVID-19 treatment papers, spot-check for retractions"

## Use case
Post-survey integrity check composing into a PubMed survey workflow

## Tool sequence

```python
# After a PubMed survey of COVID-19 treatment papers:
papers = pubmed_run_skill_result.documents  # e.g. 15 papers

# Spot-check papers that cite hydroxychloroquine treatment (known retraction cluster)
for paper in papers:
    title_lower = paper.metadata.get("title", "").lower()
    if "hydroxychloroquine" in title_lower or "hcq" in title_lower:
        # Need DOI — if not in PubMed metadata, resolve via Crossref first
        doi = paper.metadata.get("doi", "")
        if doi:
            rw_docs = run(ctx, doi, max_results=1)
            if rw_docs:
                # Mark this paper as retracted in the corpus
                paper.metadata["integrity_flag"] = "retracted"
                paper.metadata["retraction_date"] = rw_docs[0].metadata["retraction_date"]
```

## Notes

The Surgisphere dataset scandal (2020) produced high-profile retractions in Lancet and NEJM
for HCQ/COVID papers. This sweep pattern is important for any survey in a contested therapeutic
area. The retraction_watch skill returns an empty list (not an error) for clean papers, so
the iteration is safe.
