# Example 3 — Watch for new package releases (Watch mode)

**Question:** Notify me when a new version of `django` (PyPI), `react` (npm),
or `tokio` (crates.io) is published.

**Watch setup:**
```python
# Each registry watched independently via prefix syntax
django_docs = run_watchable(ctx, "pypi:django", since=last_checkpoint, max_results=5)
react_docs  = run_watchable(ctx, "npm:react", since=last_checkpoint, max_results=5)
tokio_docs  = run_watchable(ctx, "crates:tokio", since=last_checkpoint, max_results=5)
```

**Expected output per tick (when a new release exists):**
- PyPI version Document: `metadata["version"]`, `metadata["upload_time"]`
- npm version Document: `metadata["version"]`, `metadata["published_at"]`
- crates.io version Document: `metadata["version"]`, `metadata["created_at"]`,
  `metadata["yanked"]` (flag yanked releases as non-events)

**Watch checkpoint logic:**
After each tick, store the maximum timestamp seen as the new checkpoint:
```python
# Example: pick latest upload_time from all version docs returned
timestamps = [d.metadata.get("upload_time", "") for d in django_docs if d.metadata.get("upload_time")]
if timestamps:
    new_checkpoint = max(timestamps)
```

**Cadence recommendation:**
- Django (stable, security-focused): daily is sufficient.
- React (frequent minors): weekly unless you need same-day notification.
- Tokio (async Rust, fast-moving): daily for security-sensitive applications.
