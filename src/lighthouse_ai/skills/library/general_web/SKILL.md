# General Web — Planner Guide

**Skill ID:** `general_web`  
**Grade:** C (default) — quality varies significantly by source  
**Tier:** A (Tier-B JS rendering declared; stub currently falls through to static fetch)  
**Always available:** yes — universal fallback, no API key required

---

## When to use General Web

### Six roles (tracked on Recommendation.role)

| Role | When to assign | WEP note |
|---|---|---|
| `primary` | No specialty source fits the question; open web is the best available | Sole source drops −1 WEP band |
| `fallback` | Specialty skills returned thin/empty results | Same downgrade; combine with specialty if possible |
| `gap_filler` | CRAG mid-loop: a sub-question has no evidence from selected skills | Targeted query per gap; does not downgrade if specialty already covers the claim |
| `breadth` | Survey mode: scan the landscape before filtering | Expected low precision; complement with enumerable specialty sources |
| `recency` | News / current events; Watch mode | Must not be the sole citation for a load-bearing claim |
| `cross_check` | Adjudicate "popular" lens; popular opinion vs. authoritative sources | Use as the `popular` perspective only |
| `disambiguator` | Ask mode: resolve ambiguous entity references before committing to a query | Quick single call; no downstream downgrade if result is used for reformulation only |

---

## How to translate a question into a web query

1. **Strip framing words.** Remove "what is", "how does", "explain" — use noun phrases and key verbs.
2. **Add specificity.** Add a year, a proper noun, or a qualifier if the question is ambiguous.  
   Example: "climate change effects" → "climate change effects on crop yields 2022–2024"
3. **Use `search_news` for current events.** If the question involves events from the last 6 months, route to `search_news` not `search_web`.
4. **Use `search_scholar` for academic orientation.** If you need a quick literature pointer before calling arXiv/PubMed, `search_scholar` filters to scholarly domains.
5. **Use `expand_query` to diversify.** Call it once to generate 3–5 variants, then run `search_web` on the top 2 variants to broaden coverage.
6. **Follow citation chains with `follow_chain`.** When a page references another page that likely contains the primary evidence, pass the target URL to `follow_chain` (max_depth=2 is usually sufficient).

---

## Tool playbook

```
search_web(ctx, query, *, since=None, max_results=5)
    → General open-web search. Tier-A static fetch per result. Snippet fallback on egress-blocked URLs.

fetch_url(ctx, url, *, extra_meta=None)
    → Fetch one URL statically. Returns None if egress-blocked or broker-rejected.

fetch_url_js(ctx, url, *, extra_meta=None)
    → JS-rendering fetch (Tier-B stub). Currently falls through to static fetch with a metadata note.
      Use when a page is known to require JS rendering; content may be incomplete until Tier-B lands.

search_news(ctx, query, *, since=None, max_results=5)
    → News-category search. Results tagged role="recency". Use for Watch ticks and current events.

search_scholar(ctx, query, *, max_results=5)
    → Science-category search filtered to scholarly domains. Grade C — orientation only.
      For citation-grade evidence use arXiv / OpenAlex / PubMed skills.

search_images(ctx, query, *, max_results=5)
    → Returns image URLs + alt-text metadata. No binary pixel data.

search_videos(ctx, query, *, max_results=5)
    → Returns video URLs + descriptions. Metadata only. For transcripts use YouTube skill.

expand_query(ctx, query, *, max_variants=5)
    → Returns a list of query strings (the original + variants). Does NOT run the searches.

follow_chain(ctx, seed_url, *, max_depth=2, max_pages=5)
    → Fetches seed_url then follows hrefs up to max_depth hops. Egress policy enforced on every hop.
```

### Typical Investigate flow (gap_filler role)

```python
# 1. Identify empty sub-question
empty_sq = "What was the market share of X in Q3 2023?"

# 2. Translate to a targeted query
query = "X market share Q3 2023"

# 3. Search (snippet fallback if host is egress-blocked)
docs = search_web(ctx, query, max_results=3)

# 4. If thin, try expand_query + follow top variant
if len(docs) < 2:
    variants = expand_query(ctx, query, max_variants=3)
    if len(variants) > 1:
        docs += search_web(ctx, variants[1], max_results=2)
```

### Typical Watch tick flow

```python
# Called by run_watchable — search_news with since=last_tick
docs = search_news(ctx, topic_query, since=last_tick_at, max_results=5)
# Results are time-ordered by news engines; role="recency" tag applied automatically
```

---

## Known biases and quality-variance

- **Source heterogeneity.** SearXNG federates across many engines; result quality ranges from peer-reviewed preprints (via scholarly engines) to tabloids. Evaluate each Document's `url` and `engine` metadata.
- **Grade C by default.** Every Document carries `grade=C` unless overridden by a specialty skill running in parallel. Do not cite General Web as the primary authority for load-bearing factual claims.
- **Egress ceiling.** Many web pages cannot be fully fetched because their hosts are not on the platform allowlist. The snippet fallback documents are marked `fallback="snippet"` in metadata — they contain only the 200–400 character SearXNG excerpt, not the full article. Check this field before relying on the text length.
- **Snippet fallback is not the full article.** When `metadata["fallback"] == "snippet"`, the Document's `text` is the search engine snippet only. Use `fetch_url` or `follow_chain` for a full-page fetch when the host is on the allowlist.
- **No JavaScript rendering in the current pass.** `fetch_url_js` is a stub. SPAs and paywalled JavaScript-rendered pages will return thin content until Tier-B lands.

---

## Downgrade rules (MODE_SKILL_INTEGRATION.md §5.4)

1. **Single-source General-Web claim** → −1 WEP band
2. **Tier-B `fetch_backend="js"` single-source** → additional −1 WEP band (future; not triggered by current stub)
3. **General Web + specialty triangulation** → not downgraded
4. **`role=recency`** → "recency-only" badge; must not be the sole citation for a load-bearing claim

---

## Per-mode use summary

| Mode | Role | Notes |
|---|---|---|
| Investigate | primary / gap_filler / breadth | High-stakes load-bearing claims from General Web alone drop one WEP band |
| Survey | gap_filler (rare primary) | Use search_web with targeted per-sub-question queries |
| Reconstruct | breadth + recency | search_news for dated events; check timestamps in result metadata |
| Decide | per-option popular reception | One call per option; cross-check role |
| Adjudicate | popular lens, role=cross_check | Include alongside primary-source skills |
| Watch | recency via search_news | Primary watchable tool; run_watchable calls search_news with since= |
| Ask | disambiguator / implicit top-3 | Single targeted call per turn; planner decides whether to call |
