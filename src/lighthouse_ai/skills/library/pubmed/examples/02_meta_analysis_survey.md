# Example 2 — Survey: "Summarize meta-analyses on cognitive behavioral therapy for depression"

## Question type
`exploratory_survey`

## Mode
`survey`

## Tool sequence

```python
# Step 1: Target meta-analyses specifically — highest synthesis quality
docs = run(
    ctx,
    "cognitive behavioral therapy[mh] AND depressive disorder[mh] AND meta-analysis[pt]",
    max_results=15,
)

# Step 2: PRISMA funnel application:
#   Inclusion: adults OR adolescents, published >= 2010, effect size reported
#   Exclusion: non-clinical samples, < 5 RCTs in the meta-analysis

# Step 3: Extract:
#   - Effect size (Hedges' g or Cohen's d — usually in abstract Results section)
#   - Number of included trials
#   - Comparison condition (waitlist / TAU / medication)
#   - Follow-up duration

# Step 4: Check for funnel-plot asymmetry mention (publication bias indicator)
```

## Notes

PubMed's ``meta-analysis[pt]`` filter is more precise than OpenAlex for this use case because
PubMed's editorial curation tags publication types reliably. A structured abstract will contain
the effect size and heterogeneity (I²) in the Results section, which the adapter preserves.
