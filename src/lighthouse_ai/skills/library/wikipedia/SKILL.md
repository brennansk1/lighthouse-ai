# Wikipedia — Planner Guide

## When to use this skill

Wikipedia is the right first stop for **orientation and definitions**: understanding what something
is, its key attributes, its place in a taxonomy, and who the main actors are. It is weak for
**load-bearing citations** on contested or rapidly-changing topics.

**Use Wikipedia for:**
- Defining unfamiliar terms before constructing a search query for a primary source.
- Identifying the canonical name of a concept (e.g. the exact scientific name or official title)
  that you will then look up in arXiv, PubMed, or SEC EDGAR.
- Getting a structured overview of an entity's attributes via infoboxes (birth dates, headquarters,
  population, coordinates, etc.).
- Building timelines from "History" sections (Reconstruct mode, then verify with primary sources).
- Discovering the canonical category hierarchy for a topic (walk_category tool).
- Watching for significant article edits as a low-latency signal that a topic is changing
  (run_watchable / recent_revisions, Watch mode).

**Do NOT rely on Wikipedia as the sole citation for:**
- Any load-bearing claim in Investigate or Adjudicate output (grade=C triggers WEP downgrade).
- Breaking news or very recent events (coverage lags; use general_web or news skill).
- Primary medical, legal, or financial advice.
- Topics flagged as "citation needed" or "disputed" in the article.

---

## Translating a question into a Wikipedia search

1. **Extract the noun phrase.** "What causes the ozone hole?" → search `"ozone hole"`.
2. **Disambiguate upfront.** If the first result is a disambiguation page, pick the relevant
   branch and fetch that specific page.
3. **Use the infobox first for structured facts.** Dates, coordinates, population, revenue, etc. are
   faster to extract from the infobox than parsing prose.
4. **Section navigation.** The full extract returns all sections as plain text. For Reconstruct,
   look for "History" or "Background" sections.
5. **Category traversal for surveys.** For "list all X that Y" questions, walk the appropriate
   Wikipedia category rather than making many individual page fetches.

---

## Tool playbook

| Task | Tool | Notes |
|---|---|---|
| Find relevant pages | `search` | Returns top N hits with snippets |
| Get lead paragraph | `fetch_page(full_extract=False)` | Fast REST summary, ~1 paragraph |
| Get full article text | `fetch_page(full_extract=True)` | Action API, all sections, plain text |
| Extract infobox fields | `extract_infobox` | Dict of field→value; use for structured attributes |
| List pages in a category | `walk_category` | e.g. `walk_category(ctx, "Machine learning")` |
| Monitor for recent edits | `recent_revisions` | Watchable; accepts `since=` for incremental ticks |

### Typical sequence for Ask / Investigate

```
1. search(ctx, question, limit=5)           # find candidate pages
2. fetch_page(ctx, top_title)               # full extract of best hit
3. extract_infobox(ctx, top_title)          # structured attributes if needed
4. (optional) walk_category for breadth
```

### Infobox playbook

Infoboxes are the most reliable source of structured facts on Wikipedia. Use `extract_infobox`
when the user needs specific attributes of an entity (dates, locations, statistics). The returned
dict maps field names (as authored by Wikipedia editors) to cleaned values. Common infobox fields:

- People: `birth_date`, `death_date`, `birth_place`, `nationality`, `occupation`
- Organizations: `founded`, `headquarters`, `revenue`, `employees`, `CEO`
- Places: `population`, `area`, `coordinates`, `country`
- Events: `date`, `location`, `participants`, `outcome`

---

## Known biases and limitations

1. **Recency lag.** Articles often lag breaking news by hours to days. Edits to the article are
   a leading indicator (use `recent_revisions`) but the article text may not yet reflect them.

2. **Edit wars.** Contested topics (politics, religion, recent conflicts) may have unstable text
   and "disputed" / "citation needed" banners. Treat the text as summary-of-dispute, not ground truth.

3. **English-language bias.** This skill targets `en.wikipedia.org`. Topics with richer coverage
   in other language editions (geography, local politics) may be poorly represented here.

4. **Structural completeness varies.** Infoboxes exist for most notable people, places, and
   organizations but are absent from many concept or event articles. An empty dict from
   `extract_infobox` is expected for abstract topics.

5. **WEP downgrade.** Because `default_grade=C` and `signed=true`, the discipline gate will apply
   a WEP band reduction on any claim for which Wikipedia is the sole source. Triangulate with
   primary sources (arXiv, PubMed, OpenAlex) for load-bearing claims.

6. **Citations needed.** "Citation needed" tags in Wikipedia article text signal that the fact is
   asserted by an editor without a primary source — treat these facts with extra skepticism.

---

## Watch mode notes

`run_watchable` queries `list=recentchanges` filtered to the main article namespace (ns=0) and to
edits newer than the `since` checkpoint. The filtering is keyword-based on the article title; false
positives are possible for short query terms. For narrow topics, pass the exact article title as
`query` to get page-specific revision history.

Typical Watch cadence: hourly for fast-moving topics, daily for stable ones.
