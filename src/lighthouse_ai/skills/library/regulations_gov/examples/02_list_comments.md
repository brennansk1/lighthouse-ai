# Example 2 — List public comments on a rulemaking

**Question:** What did the public say about EPA's proposed particulate matter standard?

**Tool sequence:**
```python
from lighthouse_ai.sources.regulations_gov import list_comments
docs = list_comments("EPA-HQ-OAR-2022-0873", max_results=20)
```

**Expected output shape:**
- Up to 20 Documents, each with:
  - `metadata["comment_id"]`: comment identifier
  - `metadata["grade"]`: `"B"` (unverified public submission)
  - `metadata["posted_date"]`: ISO date
  - `metadata["docket_id"]`: parent docket
  - `doc.text`: title + first 500 characters of comment text

**Notes:**
- Comments are grade B — unverified third-party. Flag mass comment campaigns.
- For the full comment text, fetch the URL in `metadata["url"]`.
