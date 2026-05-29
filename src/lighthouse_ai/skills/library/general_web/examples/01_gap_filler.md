# Example 1 — Gap-filler (Investigate mode)

**Question:** What was Tesla's global market share in Q3 2023?

**Skill role:** `gap_filler` — specialty skill (SEC EDGAR) returned no matching quarter.

**Query translation:**
- Strip framing → "Tesla market share Q3 2023"
- Qualifier added → year + quarter already specific enough

**Tool sequence:**
1. `search_web(ctx, "Tesla market share Q3 2023", max_results=5)`
2. Two results returned with `fallback="snippet"` (hosts egress-blocked)
3. One result fetched fully via `fetch_and_document`
4. Thin → `expand_query(ctx, "Tesla market share Q3 2023")` → variant "Tesla EV market share third quarter 2023"
5. `search_web(ctx, "Tesla EV market share third quarter 2023", max_results=3)` → 2 more documents

**Expected output shape:**
- 3–5 Documents, mix of full-page and snippet fallback
- All tagged `skill_id="general_web"`, `grade="C"`
- At least one tagged `fallback="snippet"` (demonstrating egress-aware snippet path)

**Downgrade note:**
If no specialty source (arXiv/OpenAlex) covers this claim, the general_web-only
Documents will receive a −1 WEP downgrade when cited as the sole source for the
market-share figure.
