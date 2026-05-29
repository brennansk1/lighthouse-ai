"""FRED (St. Louis Fed) research skill — U.S. macro time series.

Provides search, fetch, release listing, revision history, and series
comparison against the FRED REST API (api.stlouisfed.org/fred). All network
access goes through SkillContext primitives; the import guard enforces that
this package never touches httpx/requests/urllib directly.

**Egress requirement:** ``api.stlouisfed.org`` must be on the platform allowlist.
Run ``lighthouse trust add api.stlouisfed.org`` to enable live fetches. Without
the trust grant the skill loads and runs but degrades gracefully to an empty
result list with a logged diagnostic.
"""
