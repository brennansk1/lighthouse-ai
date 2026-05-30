# Web Monitor — Planner Guide

## When to use this skill

Web Monitor is the Watch-v2 channel for **arbitrary web pages the user pastes**
— a page (or a section of a page) they want to keep an eye on that does *not*
already have a dedicated skill or an RSS feed. It is the right tool when:

- The user says "watch this page" / "alert me when this changes" and gives a URL.
- A specialist skill (RSS, a source adapter) does not cover the site.
- The user wants change-detection with explicit trigger criteria (any change,
  a keyword appearing, a named region changing, a number crossing a threshold).

**Do NOT use Web Monitor when:**
- The site publishes an RSS/Atom feed — prefer the `rss` skill (cheaper, cleaner
  items). Web Monitor's pre-flight will itself tell you a feed exists.
- The page is fully client-rendered (SPA) and Tier-B JS rendering is not enabled
  — the pre-flight returns `◐ limited` / `✗ blocked` with the reason; surface it.

## Two entrypoints

### `run(ctx, question, *, max_results=5)` — scrapability pre-flight
For each http(s) URL in the question, returns a Document whose text is the
verdict (`✓ good` / `◐ limited` / `✗ blocked`) and whose metadata carries the
full verdict: `robots_ok`, `crawl_delay`, `reachable`, `trust_add_hint`,
`extract_tier` (`static`/`js`/`none`), `change_method` (`feed`/`etag`/`diff`),
`feed_url`, `verdict`, `reason`. Use this on the "Add source" screen so the user
sees, before committing, whether the page is monitorable and how.

### `run_watchable(ctx, query, *, since=None, max_results=5)` — watch tick
For each monitored URL: fetch + broker + extract → build a content `Snapshot` →
evaluate the trigger criteria against the **prior** snapshot → emit a change
Document when the trigger fires. The first tick (no prior snapshot) emits a
`web_monitor_baseline` Document (`change=False`) so the session records the
snapshot without alerting.

## Stateless snapshot handoff (important)

The skill holds **no state**. The Watch session is responsible for persistence:

- Each change/baseline Document carries the **current snapshot** in
  `metadata["snapshot"]` (a dict: `text`, `content_hash`, `fetched_at`, `url`).
  Persist it in `state.db` keyed by URL.
- On the next tick, pass the prior snapshots back in `query` as a JSON map after
  a `||SNAPSHOTS||` marker:
  `"https://example.com/page ||SNAPSHOTS|| {\"https://example.com/page\": {...}}"`.
- Trigger criteria are passed after a `||CRITERIA||` marker (JSON), e.g.
  `"<url> ||CRITERIA|| {\"kind\": \"keyword\", \"terms\": [\"recall\"]}"`.
  Default (no marker) is `{"kind": "any_change"}`.

## Trigger kinds (see `modes/web_triggers.py`)

- `any_change` — content hash differs.
- `keyword` — `terms` newly appear in the page text (`require_new=true` default).
- `selector_text` — a named text region (delimited by `before`/`after` anchors,
  a guided substring selector — **not** raw XPath) changed, or now `contains` a
  substring. A broken selector self-reports (`broken=true`) instead of passing.
- `threshold` — a number parsed from the page (`label` or `pattern`) crosses
  `above` / `below` / `equals`, or `changed` since the prior snapshot.
