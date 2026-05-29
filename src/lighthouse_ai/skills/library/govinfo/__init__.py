"""GovInfo research skill — CFR, U.S. Code, Congressional Record, GAO reports.

Provides collection search, individual document fetch, CFR section lookup,
U.S. Code section lookup, and recent-collection listing (watchable) against
the GovInfo API (api.govinfo.gov). All network access goes through SkillContext
primitives; the import guard enforces that this package never touches
httpx/requests/urllib directly.

**Egress requirement:** ``api.govinfo.gov`` must be on the platform allowlist.
Run ``lighthouse trust add api.govinfo.gov`` to enable live fetches. Without
the trust grant the skill loads and runs but degrades gracefully to an empty
result list with a logged diagnostic.

**API key requirement:** A free key from https://api.govinfo.gov/docs/ is
required for higher rate limits.
"""
