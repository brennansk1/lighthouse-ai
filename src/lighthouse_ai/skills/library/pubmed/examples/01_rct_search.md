# Example 1 — Clinical RCT search: "What do randomized trials show about SGLT2 inhibitors for heart failure?"

## Question type
`causal_explanation` + `methodology_evaluation`

## Mode
`investigate`

## Tool sequence

```python
# Step 1: MeSH + pub-type filtered query for RCTs
docs = run(
    ctx,
    "sodium-glucose transporter 2 inhibitors[mh] AND heart failure[mh] AND randomized controlled trial[pt]",
    max_results=10,
)

# Step 2: Planner screens abstracts for:
#   - Primary endpoints (LVEF improvement, hospitalization, mortality)
#   - Sample size and follow-up duration
#   - Blinding status (double-blind vs open-label)

# Step 3: Rank by evidence quality: meta-analyses > large RCTs > small RCTs

# Step 4: Note any industry funding disclosures in the abstract
# (conflict-of-interest signal; check for manufacturer-funded trials)
```

## Expected document metadata

```json
{
  "source": "pubmed",
  "title": "Dapagliflozin in Patients with Heart Failure and Reduced Ejection Fraction",
  "url": "https://pubmed.ncbi.nlm.nih.gov/31535829/",
  "grade": "A",
  "published_date": "2019-11",
  "skill_id": "pubmed",
  "skill_version": "0.1.0",
  "fetch_backend": "tier-a"
}
```

## Notes

The MeSH + ``[pt]`` combination is the most powerful filter for clinical evidence quality.
Without ``[pt]``, you get a mix of reviews, editorials, and case reports alongside RCTs.
The DAPA-HF trial (NEJM, 2019) and EMPEROR-Reduced trial are the seminal papers here.
