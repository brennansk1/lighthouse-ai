# Example: add a page monitor, then watch it for a recall keyword

## 1. Pre-flight (Add source)

Question: `Can I monitor https://example.gov/product-recalls ?`

`run(ctx, question)` returns one Document:

> ✓ good: good to monitor (feed available) (https://example.gov/product-recalls)

with metadata `{robots_ok: true, reachable: true, extract_tier: "static",
change_method: "feed", feed_url: "https://example.gov/recalls.xml", verdict:
"good", reason: "good to monitor (feed available)"}`.

If the host were not yet allowlisted the verdict would be `◐ limited` with
`trust_add_hint: "example.gov"` and the reason instructing
`lighthouse trust add example.gov`.

## 2. Watch tick (first / baseline)

Query (no prior snapshot):
`https://example.gov/product-recalls ||CRITERIA|| {"kind": "keyword", "terms": ["recall"]}`

`run_watchable` fetches the page, builds a snapshot, and — because there is no
prior snapshot — emits a `web_monitor_baseline` Document (`change=false`) whose
`metadata["snapshot"]` the session persists.

## 3. Watch tick (subsequent — keyword newly appears)

Query (prior snapshot passed back):

```
https://example.gov/product-recalls
||CRITERIA|| {"kind": "keyword", "terms": ["recall"]}
||SNAPSHOTS|| {"https://example.gov/product-recalls": {"text": "...old text...", "content_hash": "...", "fetched_at": "2026-05-29T00:00:00"}}
```

When the new page text contains "recall" (and the old did not),
`run_watchable` emits a `web_monitor_change` Document
(`change=true`, `reason="matched keyword(s): recall"`) with the added lines in
the body and the new snapshot in metadata for the next tick.
