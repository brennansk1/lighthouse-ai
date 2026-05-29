# Example 3 — Retrieve recent executive orders

**Question:** What executive orders has the President signed recently?

**Tool sequence:**
```python
# Via the adapter directly (skill run() uses search_rules; for EOs call adapter):
from lighthouse_ai.sources.federal_register import get_executive_orders
docs = get_executive_orders(max_results=10)
```

**Expected output shape:**
- Documents of type `"Presidential Document"`, each with:
  - `metadata["document_type"]`: `"Presidential Document"`
  - `metadata["title"]`: EO title
  - `metadata["publication_date"]`: date signed/published
  - `metadata["citation"]`: e.g. `"89 FR 12345"`

**Notes:**
- Executive orders are archived indefinitely by the Federal Register.
- To search for EOs on a specific topic, use `run(ctx, "executive order topic")`.
- Cross-reference with GovInfo (PLAW/PRESDOCU collection) for the codified
  version and any implementing regulations.
