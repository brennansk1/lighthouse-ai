# Example 3 — Commit history for Reconstruct mode

**Question:** When was the `tokio` async runtime's Timer implementation
rewritten, and who authored the change?

**Tool sequence:**
```python
# Search for the repo
repos = run(ctx, "tokio rust async runtime", max_results=3)
# Find tokio-rs/tokio

# Get commit history filtered to a date window
commits = get_commit_history(
    "tokio-rs", "tokio",
    max_results=50,
    since="2020-01-01T00:00:00Z",
    path="tokio/src/time",
)
```

**Expected output shape:**
- Commit Documents with:
  - `metadata["sha"]`: full SHA
  - `metadata["message"]`: first 300 chars of commit message
  - `metadata["author"]`: committer name
  - `metadata["committed_at"]`: ISO timestamp

**Notes:**
- Use `path=` to narrow commits to the subsystem of interest.
- Cross-reference commit SHAs with GitHub release tags to determine which
  release first included the change.
- For `since=` filtering in Watch mode, store the latest `committed_at` as
  the checkpoint.
