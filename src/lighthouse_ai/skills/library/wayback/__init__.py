"""Internet Archive Wayback Machine skill — historical web retrieval.

Queries the Wayback CDX HTTP API (no AGPL internetarchive package) to look
up, list, fetch, and submit snapshots.  Critical for Reconstruct mode,
journalism dead-link recovery, and legal "what did the page say on date X"
use cases.

All network access goes through SkillContext primitives; the import guard
enforces that this package never touches httpx/requests/urllib directly.
"""
