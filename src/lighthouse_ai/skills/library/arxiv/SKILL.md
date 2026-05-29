# arXiv — Planner Guide

## When to use this skill

arXiv is the right primary source for **recent research** in computer science, physics,
mathematics, statistics, quantitative biology, electrical engineering, and economics. It is a
**preprint server** — papers are posted before peer review. Treat findings as promising but
unverified until you can confirm peer-reviewed publication status.

**Use arXiv for:**
- Finding the original paper that introduced a method, architecture, or algorithm.
- Surveying the current state of research on a CS/ML/physics/math topic.
- Identifying authors and research groups active in a subfield.
- Comparing competing approaches to a methodology question (e.g. training strategies, loss functions).
- Causal or mechanistic explanation questions in STEM fields.
- Exploratory surveys across a domain (output_shape=enumerable is ideal for PRISMA-style funnels).

**Do NOT rely on arXiv for:**
- Questions about popular media, business, law, medicine (use PubMed/OpenAlex for clinical evidence).
- Breaking news or current events (use general_web or news skill).
- Policy, legal, or regulatory questions.
- Any question where peer review is a prerequisite — arXiv preprints are not peer-reviewed.
  Always caveat findings with "preprint, not peer-reviewed" for load-bearing claims.
- Consumer or non-technical decision questions (modes_weak_fit: decide, watch).

---

## Important caveat: arXiv is not peer-reviewed

arXiv posts papers at authors' initiative, without formal editorial peer review.
A paper on arXiv may later be rejected by journals, retracted, or substantially revised.
The platform's `authority="preprint"` reflects this: the discipline gate will not award
the same epistemic weight as a peer-reviewed journal source. Always note "preprint (arXiv)"
in citations and flag load-bearing claims for corroboration.

---

## Translating a question into an arXiv query

arXiv supports structured field-prefixed queries. Prefer these over free-text when you know
the category, author, or title keywords:

| Goal | Query form | Example |
|---|---|---|
| Topic search | `all:keyword` (default) | `attention mechanism transformers` |
| Category filter | `cat:category_code` | `cat:cs.LG` (Machine Learning) |
| Author search | `au:surname` | `au:LeCun` |
| Title keyword | `ti:keyword` | `ti:diffusion models` |
| Combined | `ti:keyword AND cat:code` | `ti:attention AND cat:cs.CL` |

### Common arXiv category codes

- `cs.AI` — Artificial Intelligence
- `cs.CL` — Computation and Language (NLP)
- `cs.CV` — Computer Vision
- `cs.LG` — Machine Learning
- `cs.RO` — Robotics
- `econ.EM` — Econometrics
- `math.ST` — Statistics Theory
- `physics.optics` — Optics
- `q-bio.NC` — Neurons and Cognition
- `stat.ML` — Machine Learning (Statistics)

---

## Tool playbook

| Task | Entrypoint | Notes |
|---|---|---|
| Search for papers by topic | `run(ctx, question)` | Returns up to `max_results` papers (title + abstract) |
| Watch for new submissions | `run_watchable(ctx, query, since=checkpoint)` | Filters client-side by `published_date > since` |

### Typical sequence for Investigate / Survey

```
1. run(ctx, question, max_results=10)        # fetch candidate papers
2. (planner) rank by relevance to sub-questions
3. (planner) fetch full PDFs via general_web skill for top 2–3 papers if depth=thorough
```

For Survey mode the enumerable corpus from `run` feeds the PRISMA funnel directly —
screen titles/abstracts, apply inclusion criteria, extract methodology attributes.

---

## Watch mode notes

`run_watchable` fetches recent submissions and filters by `published_date > since`.
Because the arXiv API sorts by submission date (`sortBy=submittedDate`), the newest
papers appear first. The client-side filter drops anything already seen in the last tick.

Recommended cadence: daily for active research areas, weekly for slower fields.
Use category-qualified queries (e.g. `cat:cs.LG AND diffusion`) to reduce noise.
The `since=` parameter must be a `datetime` object (timezone-naive UTC or aware).

---

## Known biases and limitations

1. **Preprint quality varies.** No peer review gatekeeping. Some papers contain errors that
   are later corrected. Prefer citing the published venue when available.

2. **CS/physics/math bias.** Coverage is thin for biology, clinical medicine, social sciences,
   and humanities. For those fields prefer PubMed, OpenAlex, or Semantic Scholar.

3. **Recency vs comprehensiveness trade-off.** arXiv is excellent for recent work (2018+) but
   older foundational papers (pre-2000 in many fields) may not be posted.

4. **Abstract-only.** The skill returns titles and abstracts. For full-text analysis, fetch the
   PDF directly via the general_web skill using the paper's `url` from the document metadata.

5. **Author disambiguation.** `au:Smith` will match all authors named Smith. Use full names or
   combine with a category filter to narrow the result set.

6. **Rate limit.** arXiv requests approximately 3-second spacing between API calls
   (`rate_limit_per_sec=0.34`). The runner enforces politeness; do not call in a tight loop.
