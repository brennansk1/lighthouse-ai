# Example: Compare coverage of a political event across outlets

## Question
How are outlets with different political leanings covering the immigration policy debate?

## Tool sequence
1. `compare_coverage(ctx, "immigration policy")`
2. Inspect `result["outlets"]` — each entry has `outlet_id`, `allsides_rating`, `documents`
3. Use `result["bias_overlay"]` to annotate the Adjudicate perspective matrix
4. Summarize divergent framings between Center (Reuters/AP) and Left (Guardian)

## Expected shape
```json
{
  "outlets": [
    {"outlet_id": "reuters",  "allsides_rating": "center",    "documents": [...]},
    {"outlet_id": "associated_press", "allsides_rating": "center", "documents": [...]},
    {"outlet_id": "bbc_news", "allsides_rating": "lean_left", "documents": [...]},
    {"outlet_id": "npr",      "allsides_rating": "lean_left", "documents": [...]},
    {"outlet_id": "guardian", "allsides_rating": "left",      "documents": [...]},
    {"outlet_id": "propublica","allsides_rating": "lean_left","documents": [...]}
  ],
  "bias_overlay": {"reuters": "center", "bbc_news": "lean_left", ...}
}
```
