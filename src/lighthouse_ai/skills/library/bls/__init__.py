"""BLS (Bureau of Labor Statistics) research skill — employment, CPI, and wages.

Provides series search, time-series fetching, survey listing, geographic
comparison, and occupational wage data against the BLS Public Data API v2
(api.bls.gov/publicAPI/v2). All network access goes through SkillContext
primitives; the import guard enforces that this package never touches
httpx/requests/urllib directly.

**Egress requirement:** ``api.bls.gov`` must be on the platform allowlist.
Run ``lighthouse trust add api.bls.gov`` to enable live fetches. Without
the trust grant the skill loads and runs but degrades gracefully to an empty
result list with a logged diagnostic.
"""
