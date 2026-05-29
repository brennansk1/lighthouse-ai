# Example 2 — Compare countries on a health indicator

**Question:** How does life expectancy at birth compare across high-income and
low-income countries?

**Tool sequence:**
```python
# 1. Find the right indicator
docs = run(ctx, "life expectancy at birth", max_results=5)
# → returns indicators including "Life expectancy at birth (years)"

# 2. Each Document represents a country-indicator pair
for doc in docs:
    print(doc.metadata["country"], doc.text)
```

**Expected output shape:**
- Documents with `metadata["country"]` (ISO 3166-1 alpha-3) and
  `metadata["indicator_code"]`.
- `doc.text` contains a compact summary: "WHOSIS_000001 — USA: 2020: 77.3; 2019: 78.8"

**Notes:**
- Use for Adjudicate mode: each country is an independent perspective-lens.
- For a strict country comparison, filter docs by `metadata["country"]` and
  sort by the numeric values in `doc.text`.
