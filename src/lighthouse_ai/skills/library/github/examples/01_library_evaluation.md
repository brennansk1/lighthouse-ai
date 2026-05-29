# Example 1 — Library evaluation (Decide mode)

**Question:** Which Python HTTP client library should I use for production
async workloads — httpx, aiohttp, or requests?

**Tool sequence:**
```python
# Step 1: Discover repositories
candidates = run(ctx, "python http client async", max_results=10)
# Expect: httpx, aiohttp, requests in results

# Step 2: For each candidate check license
for owner, repo in [("encode", "httpx"), ("aio-libs", "aiohttp"), ("psf", "requests")]:
    lic = get_license(owner, repo)     # via adapter, through ctx
    rels = list_releases(owner, repo, max_results=5)
    issues = list_recent_issues(owner, repo, state="open", max_results=10)
    advisories = get_security_advisories(owner, repo)
```

**Expected output shape:**
- 3 repo Documents: `metadata["full_name"]`, `metadata["stars"]`,
  `metadata["language"]`, `metadata["license"]`
- 1 license Document per repo: `metadata["spdx_id"]`
- Release Documents: `metadata["tag_name"]`, `metadata["published_at"]`
- Issue Documents: `metadata["number"]`, `metadata["title"]`, `metadata["labels"]`
- Advisory Documents: `metadata["ghsa_id"]`, `metadata["severity"]`,
  `metadata["cve_id"]`

**Output guidance:**
Build a comparison table: library | license | stars | last release | open issues | known CVEs.
Note any advisories with severity "high" or "critical" as blockers.
