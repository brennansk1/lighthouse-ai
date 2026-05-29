"""OECD research skill — comparative cross-country economic and social indicators.

Provides dataset search, SDMX data fetching, and country comparison against
the OECD SDMX JSON API (sdmx.oecd.org/public/rest). No authentication is
required. All network access goes through SkillContext primitives; the import
guard enforces that this package never touches httpx/requests/urllib directly.

**Egress requirement:** ``sdmx.oecd.org`` must be on the platform allowlist.
Run ``lighthouse trust add sdmx.oecd.org`` to enable live fetches. Without
the trust grant the skill loads and runs but degrades gracefully to an empty
result list with a logged diagnostic.
"""
