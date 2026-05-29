"""U.S. Census Bureau research skill — demographics, ACS, and decennial census.

Provides dataset discovery, ACS 5-year table fetching, decennial census data,
and geographic identifier lookup against the Census Data API
(api.census.gov). All network access goes through SkillContext primitives;
the import guard enforces that this package never touches httpx/requests/urllib
directly.

**Egress requirement:** ``api.census.gov`` must be on the platform allowlist.
Run ``lighthouse trust add api.census.gov`` to enable live fetches. Without
the trust grant the skill loads and runs but degrades gracefully to an empty
result list with a logged diagnostic.
"""
