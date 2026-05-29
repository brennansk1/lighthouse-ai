# Example 2 — Find GAO reports on a topic

**Question:** What has the GAO said about VA healthcare quality?

**Tool sequence:**
```python
docs = run(ctx, "VA healthcare quality veterans", max_results=5)
# Or target the collection directly:
from lighthouse_ai.sources.govinfo import search_collection
docs = search_collection("VA healthcare quality", collection="GAOREPORTS", max_results=5)
```

**Expected output shape:**
- Documents from the GAOREPORTS collection, each with:
  - `metadata["collection_code"]`: `"GAOREPORTS"`
  - `metadata["title"]`: GAO report title
  - `metadata["date_issued"]`: publication date
  - `metadata["doc_class"]`: report number/class

**Notes:**
- GAO reports are grade A — authoritative retrospective audits.
- Reports assess past performance; they are not current policy pronouncements.
