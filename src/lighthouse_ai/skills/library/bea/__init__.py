"""BEA (Bureau of Economic Analysis) research skill — national accounts and GDP.

Provides dataset discovery, NIPA table fetching, regional accounts, and
industry-level GDP against the BEA API (apps.bea.gov/api). All network
access goes through SkillContext primitives; the import guard enforces that
this package never touches httpx/requests/urllib directly.

**Egress requirement:** ``apps.bea.gov`` must be on the platform allowlist.
Run ``lighthouse trust add apps.bea.gov`` to enable live fetches. Without
the trust grant the skill loads and runs but degrades gracefully to an empty
result list with a logged diagnostic.
"""
