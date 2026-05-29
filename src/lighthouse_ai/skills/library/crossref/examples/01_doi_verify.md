# Example 1 — DOI verification: "Verify and get metadata for 'Attention Is All You Need' (Vaswani et al., 2017)"

## Question type
`factual_lookup`

## Mode
`investigate`

## Tool sequence

```python
# Step 1: Search with author + title fragment
docs = run(ctx, "Attention Is All You Need Vaswani transformer 2017", max_results=3)

# Step 2: Planner identifies the matching paper
# → doc with title "Attention Is All You Need" and published_date containing "2017"
# → doi extracted from doc.metadata["url"]: "https://doi.org/10.48550/arxiv.1706.03762"

# Step 3: Citation is verified; metadata confirmed
# Note: this DOI is actually a "posted-content" (arXiv) type → Grade B in Crossref
# The NeurIPS proceedings version would be Grade A
```

## Expected document metadata

```json
{
  "source": "crossref",
  "title": "Attention Is All You Need",
  "url": "https://doi.org/10.48550/arxiv.1706.03762",
  "grade": "B",
  "published_date": "2017-6-12",
  "skill_id": "crossref",
  "skill_version": "0.1.0",
  "fetch_backend": "tier-a"
}
```

## Notes

Note that the arXiv preprint version returns Grade B. If you need the peer-reviewed
proceedings version, search specifically for the NeurIPS 2017 citation.
