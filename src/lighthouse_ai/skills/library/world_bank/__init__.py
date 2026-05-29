"""World Bank Open Data research skill — international development indicators.

Provides indicator search, time-series fetching, topic-based browsing, and
multi-country comparison against the World Bank API v2 (api.worldbank.org/v2).
No authentication is required. All network access goes through SkillContext
primitives; the import guard enforces that this package never touches
httpx/requests/urllib directly.

**Egress requirement:** ``api.worldbank.org`` must be on the platform allowlist.
Run ``lighthouse trust add api.worldbank.org`` to enable live fetches. Without
the trust grant the skill loads and runs but degrades gracefully to an empty
result list with a logged diagnostic.
"""
