# Example 1 — High-impact survey: "What are the most influential papers on graph neural networks?"

## Question type
`exploratory_survey`

## Mode
`survey`

## Tool sequence

```python
# Step 1: Search and sort by citation count
docs = run(ctx, "graph neural networks message passing", max_results=10)

# Step 2: Planner sorts by doc.metadata["citation_count"] descending
# High citation_count = most influential in the field
# Example expected results:
#   - Kipf & Welling, 2017 (GCN) → ~15,000+ citations
#   - Velickovic et al., 2018 (GAT) → ~8,000+ citations
#   - Hamilton et al., 2017 (GraphSAGE) → ~7,000+ citations

# Step 3: Planner groups by citation era:
#   "Foundational" (>5000 citations): the canonical papers
#   "Established" (1000-5000): widely adopted methods
#   "Emerging" (<1000): recent contributions

# Step 4 (optional): Fetch S2 paper page for top 3 to see citation intent breakdown
```

## Expected document metadata

```json
{
  "source": "semantic_scholar",
  "title": "Semi-Supervised Classification with Graph Convolutional Networks",
  "url": "https://www.semanticscholar.org/paper/36eff562f65125511b5dfab68ce7f7a943c27478",
  "grade": "A",
  "published_date": "2017",
  "citation_count": 14892,
  "skill_id": "semantic_scholar",
  "skill_version": "0.1.0",
  "fetch_backend": "tier-a"
}
```
