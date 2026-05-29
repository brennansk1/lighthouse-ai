# Example 1 — Look up a CFR section

**Question:** What does 40 CFR Part 50 say about the NAAQS for particulate matter?

**Tool sequence:**
```python
from lighthouse_ai.sources.govinfo import get_cfr_section
docs = get_cfr_section(40, "50")
```

**Expected output shape:**
- 1–3 Documents from the CFR collection, each with:
  - `metadata["collection_code"]`: `"CFR"`
  - `metadata["title"]`: e.g. `"Title 40 - Protection of Environment"`
  - `metadata["date_issued"]`: edition year
  - `metadata["package_id"]`: GovInfo package ID for the full document

**Notes:**
- The CFR is republished annually. Check `date_issued` for the edition year.
- For the most recent amendments not yet in the annual edition, check the
  Federal Register skill.
