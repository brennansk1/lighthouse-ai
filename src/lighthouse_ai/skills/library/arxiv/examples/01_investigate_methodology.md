# Example 1 — Methodology evaluation: "What attention mechanisms are used in vision transformers?"

## Question type
`methodology_evaluation`

## Mode
`investigate`

## Tool sequence

```python
# Step 1: Search with a category-qualified query for precision
docs = run(ctx, "ti:attention AND cat:cs.CV vision transformers", max_results=10)
# → list of Documents, each with title + abstract

# Step 2: Planner screens abstracts for attention-mechanism keywords
# (multi-head self-attention, linear attention, sparse attention, etc.)

# Step 3 (optional, depth=thorough): fetch full PDF for top paper
# → hand off to general_web skill using doc.metadata["url"]
```

## Expected document metadata

```json
{
  "source": "arxiv",
  "title": "An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale",
  "url": "http://arxiv.org/abs/2010.11929v2",
  "grade": "A",
  "published_date": "2020-10-22T17:54:52Z",
  "skill_id": "arxiv",
  "skill_version": "0.1.0",
  "fetch_backend": "tier-a"
}
```

## Notes

arXiv is the primary lens for this question type: the seminal ViT paper (Dosovitskiy et al.)
and its follow-ons are all on arXiv. Use `cat:cs.CV` to restrict to computer vision.
The abstract alone is usually sufficient to identify which attention variant a paper uses.
