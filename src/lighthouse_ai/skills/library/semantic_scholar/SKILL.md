# Semantic Scholar — Planner Guide

## When to use this skill

Semantic Scholar is the right source when the question is about **how a paper is received,
challenged, or extended by the scientific community** — not just whether it exists. Its
citation-intent classification and influential-citation flag are the signals OpenAlex lacks.

**Use Semantic Scholar for:**
- Citation-velocity analysis: how quickly is a paper accumulating citations?
- Finding papers that **support**, **contrast**, **extend**, or use as **background** a
  specific work (citation-intent signal, available via the S2 graph API beyond this skill's
  ``run`` entrypoint).
- Identifying papers with high "influential citation" status — cited in ways that changed
  downstream methodology.
- Locating the most-cited papers on a topic (``citation_count`` metadata).
- Finding related work clusters: S2's concept graph links papers through shared concepts.
- Cross-disciplinary literature sweeps for CS, biomedical, and social science topics.

**Do NOT rely on Semantic Scholar for:**
- MeSH-controlled clinical searches — use PubMed for precision clinical queries.
- Humanities and social science coverage (thinner than OpenAlex or Crossref).
- Retraction status — use retraction_watch (via Crossref) for that.
- Full-text content — results are title + abstract only.

---

## The Citation-Intent Angle

The key differentiator: S2 uses NLP to classify how a paper is cited. This is crucial for
**adjudicating conflicting evidence**:

| Citation intent | Meaning | Significance |
|---|---|---|
| `supporting` | Cites the paper to support its claims | Reinforces the result |
| `contrasting` | Cites the paper to dispute or limit its claims | Challenges the result |
| `extending` | Builds on the methodology or framework | Community adoption |
| `background` | Mentions it as prior work without central use | General context |

In Adjudicate mode: a paper cited primarily with **contrasting** intent has seen pushback;
one cited with **supporting** intent has been corroborated. High **extending** citations means
its methodology has been adopted (a form of indirect replication).

The citation-intent data is available via the S2 graph API (paper/{id}/citations endpoint)
beyond what this skill's ``run`` entrypoint returns. For citation-intent analysis, the planner
should note ``doc.metadata["citation_count"]`` as a proxy for influence and plan a follow-up
fetch via the general_web skill to the S2 graph endpoint.

---

## Translating a question into a Semantic Scholar query

S2's keyword search covers titles, abstracts, and venues. No field-prefix syntax in the
standard search endpoint. Boolean and phrase queries work.

| Goal | Query form | Notes |
|---|---|---|
| Influential papers on topic | `"contrastive learning image representations"` | Most-cited results |
| Find a specific paper | `"LeCun Yann deep learning review 2015 Nature"` | Author + year + venue |
| Disputed methodology | `"p-hacking researcher degrees of freedom"` | Gets critical papers |
| Replication studies | `"replication failure social priming"` | Finds the replication literature |

---

## Tool playbook

| Task | Entrypoint | Notes |
|---|---|---|
| Search for papers by topic | `run(ctx, question)` | Returns up to `max_results` papers with citation counts |
| Find highly-cited work | `run(ctx, query)` | Sort by `doc.metadata["citation_count"]` in planner |

### Typical sequence for Adjudicate

```
1. run(ctx, question, max_results=10)
   # Get the candidate corpus, with citation counts

2. (planner) sort by citation_count descending
   # High citation count = more community scrutiny = stronger signal

3. (planner) for the top 3-5 papers, note the S2 URL from doc.metadata["url"]
   # URL format: "https://www.semanticscholar.org/paper/{paperId}"

4. (optional) fetch the S2 paper page via general_web for citation-intent breakdown
   # The paper page shows "cites as supporting", "cites as contrasting" counts

5. Cross-reference with OpenAlex for affiliation-independence check
```

---

## Known biases and limitations

1. **Citation count vs citation quality.** High citation count can reflect field size, age,
   or controversy — not just quality. A paper cited 1000 times in contrasting citations is
   less reliable than one cited 100 times in supporting citations.

2. **Rate limit.** Unauthenticated requests: ~1 req/s (enforced). The adapter respects this.
   Pass ``S2_API_KEY`` (free registration at semanticscholar.org) to increase to 100+ req/min.

3. **Coverage gaps.** S2 covers CS, biomedical, and social science well. Humanities, law, and
   some regional journals have thinner coverage than OpenAlex or Crossref.

4. **Abstract-only.** Returns title + abstract. Full text requires a separate fetch.

5. **Citation intent requires graph API.** The ``run`` entrypoint returns citation counts but
   not per-citing-paper intent classification. That requires follow-up calls to the S2 graph
   API (beyond this skill's current entrypoint).

6. **Year-only dates.** Published dates from S2 are year-only (e.g. ``"2023"``), not
   month/day. This limits date-based filtering precision.
