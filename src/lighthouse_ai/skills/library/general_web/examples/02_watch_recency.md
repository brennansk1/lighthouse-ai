# Example 2 — Watch tick (recency role)

**Topic:** "OpenAI product announcements"
**Cadence:** daily
**Last tick:** 2024-03-14T09:00:00Z

**Tool sequence:**
1. `run_watchable(ctx, "OpenAI product announcements", since=datetime(2024,3,14,9,0), max_results=5)`
2. Internally calls `_searxng.search("OpenAI product announcements after:2024-03-14", categories="news")`
3. Returns 5 time-ordered Documents tagged `role="recency"`, `since="2024-03-14T09:00:00"`

**Expected output shape:**
- Up to 5 Documents, newest-first per news engine ordering
- All tagged `role="recency"`, `skill_id="general_web"`, `grade="C"`
- `since` metadata field present on each Document for dedup logic

**Downgrade note:**
`role=recency` Documents must not be the sole citation for load-bearing claims.
The Watch engine applies a "recency-only" badge and the hotness scorer weights
them for escalation detection rather than for factual citation.
