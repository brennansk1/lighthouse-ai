# Example 2 — Cross-registry comparison (Survey mode)

**Question:** Compare the state of HTTP client libraries across Python (httpx),
JavaScript (axios), and Rust (reqwest).

**Tool sequence:**
```python
# Query each registry for the named package
httpx_docs  = run(ctx, "pypi:httpx", max_results=1)
axios_docs  = run(ctx, "npm:axios", max_results=1)
reqwest_docs = run(ctx, "crates:reqwest", max_results=1)

# Get version history for release cadence
httpx_vers  = pypi_get_versions("httpx", max_results=10)
axios_vers  = npm_get_versions("axios", max_results=10)
reqwest_vers = crates_get_versions("reqwest", max_results=10)
```

**Expected output shape per package:**
- 1 metadata Document: `metadata["name"]`, `metadata["version"]`,
  `metadata["license"]`, `metadata["description"]`
- Version Documents (10 each): `metadata["version"]`,
  `metadata["upload_time"]` / `metadata["published_at"]` / `metadata["created_at"]`

**Output guidance:**
Comparison table: library | ecosystem | latest version | license | release cadence
(avg days between last 5 releases) | downloads / month (if available).
Note: crates.io exposes `downloads` and `recent_downloads` directly.
