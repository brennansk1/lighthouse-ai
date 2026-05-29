# Example 2 — Security advisory watch (Watch mode)

**Question:** Alert me when a new security advisory is published for
`django/django`.

**Watch setup:**
```python
docs = run_watchable(ctx, "django/django", since=last_checkpoint, max_results=20)
# Filter docs where metadata["type"] == "release"
# Cross-reference with get_security_advisories("django", "django") for GHSA
```

**Expected output shape per tick:**
- Release Documents with `published_at` after ``since``:
  - `metadata["tag_name"]`: e.g. `"4.2.16"`
  - `metadata["published_at"]`: ISO timestamp
  - `metadata["prerelease"]`: `false` for stable releases
- If get_security_advisories returns new entries:
  - `metadata["ghsa_id"]`: e.g. `"GHSA-xxxx-xxxx-xxxx"`
  - `metadata["severity"]`: `"high"` / `"critical"` / `"medium"` / `"low"`
  - `metadata["cve_id"]`: e.g. `"CVE-2024-45230"` (may be empty for draft advisories)

**Notes:**
- Django security releases follow a predictable pattern: the advisory is
  published the same day as the release.  Watching releases is a reliable
  proxy for new security advisories.
- For a tighter signal, combine watchable releases with a daily call to
  `get_security_advisories` filtered by `published_at`.
