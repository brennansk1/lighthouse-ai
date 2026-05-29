# Example 1 — DOI lookup: "Check retraction status of Wakefield MMR/autism paper"

## Use case
Integrity check composing into a Crossref/PubMed workflow

## Tool sequence

```python
# The Wakefield Lancet paper: DOI 10.1016/s0140-6736(97)11096-0
# (Retracted 2010 — fraud, ethics violations)

result = run(ctx, "10.1016/s0140-6736(97)11096-0", max_results=1)

if result:
    doc = result[0]
    print(f"RETRACTED: {doc.metadata['retracted_doi']}")
    print(f"Retraction DOI: {doc.metadata['retraction_doi']}")
    print(f"Date: {doc.metadata['retraction_date']}")
    print(f"Type: {doc.metadata['retraction_reason']}")
else:
    print("No retraction record found")
```

## Expected document metadata

```json
{
  "source": "retraction_watch",
  "retracted_doi": "10.1016/s0140-6736(97)11096-0",
  "retraction_reason": "retraction",
  "retraction_date": "2010-02",
  "skill_id": "retraction_watch",
  "skill_version": "0.1.0",
  "fetch_backend": "tier-a"
}
```

## Notes

Non-empty result = retraction confirmed. Always surface this to the user with the retraction
date and reason before using the paper as evidence. In this case, the paper should be
excluded from any corpus and any citations to it in other papers should be flagged.
