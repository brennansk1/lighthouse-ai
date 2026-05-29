# News Orchestrator — Research Skill Guide

## What this skill is

The News Orchestrator is the SL12 meta-skill that coordinates all six
first-party news outlet skills (Reuters, AP, BBC News, NPR, The Guardian,
ProPublica) in a single call.  It is the primary entry point for:

- Broad news search across multiple outlets at once
- Side-by-side coverage comparison with AllSides bias overlay
- Adjudicate mode (perspective diversity across Center / Lean Left / Left)
- Watch mode continuous monitoring across all outlets

**Use this skill when the question is news-oriented and you want coverage
across the political-bias spectrum rather than one outlet's perspective.**

## Outlet coverage and AllSides ratings

| Outlet          | Bias Rating | Authority             |
|-----------------|-------------|----------------------|
| Reuters         | Center      | Wire service          |
| Associated Press| Center      | Wire service          |
| BBC News        | Lean Left   | Public broadcaster    |
| NPR             | Lean Left   | Public broadcaster    |
| The Guardian    | Left        | Newspaper             |
| ProPublica      | Lean Left   | Investigative nonprofit |

Every returned Document carries `metadata["allsides_rating"]` and
`metadata["outlet"]` so the planner and Adjudicate mode can see provenance
without a separate lookup.

## Tools

### `search_news(ctx, query, *, outlets=None, max_results=5)`
Fan-out the query across all trusted outlets (or a filtered subset).
Returns a flat list of Documents, each tagged with outlet + bias.
Best for: "What are news outlets reporting on topic X?"

### `compare_coverage(ctx, query, *, outlets=None)`
Same query across N outlets, returns a structured side-by-side dict:
```
{
  "outlets": [
    {"outlet_id": "reuters", "allsides_rating": "center", "documents": [...], ...},
    ...
  ],
  "bias_overlay": {"reuters": "center", "bbc_news": "lean_left", ...}
}
```
Best for: "How do outlets with different political leanings cover event X?"

### `register_custom_outlet(feed_url, outlet_id, outlet_name, allsides_rating="unknown")`
Add a user-supplied RSS feed to the in-process outlet pool.  Ephemeral —
not persisted across process restarts.  Useful for niche sources during a
research session.

### `validate_outlet_access(ctx, outlet_id=None)`
Best-effort reachability check for one or all outlets.  Returns a list of
`{"outlet_id", "reachable", "error"}` dicts.  Used by `lighthouse doctor news`.

### `get_bias_overlay()`
Return the static AllSides rating map: `{outlet_id: allsides_rating}`.
No network call required.

## Bias and limitations

- The six seed outlets skew Center-to-Left on the AllSides scale; no
  right-leaning outlet is available in the free/fetchable tier without
  paywall or ToS constraints.  The planner should note this gap.
- Wire services (Reuters, AP) provide brief headlines; full body text
  requires a `fetch_article` call on the individual outlet skill.
- ProPublica's open data tools (`search_data_repo`) are only accessible
  via the `propublica` skill directly; this skill uses RSS only.
- EgressBlocked on any one outlet is silently skipped; the result set
  may be smaller than expected.

## When to use vs per-outlet skills

| Situation | Skill to use |
|-----------|--------------|
| Need Reuters-specific topics/feeds | `reuters` directly |
| Guardian tag-based deep dive | `guardian` directly |
| ProPublica nonprofit data | `propublica` directly |
| Broad coverage / bias comparison | **`news_orchestrator`** |
| Watch mode across all outlets | **`news_orchestrator`** |

## Citation

Documents returned by this skill retain their outlet provenance via
`metadata["outlet"]`.  Cite as: [Outlet Name], [article title], [date], [URL].
