"""WHO Global Health Observatory research skill — international health data.

Provides search, indicator fetch, country comparison, ICD code lookup, and
outbreak monitoring against the WHO GHO OData API. All network access goes
through SkillContext primitives; the import guard enforces that this package
never touches httpx/requests/urllib directly.

**Egress requirement:** ``ghoapi.azureedge.net`` must be on the platform
allowlist. Run ``lighthouse trust add ghoapi.azureedge.net`` (or
``lighthouse trust add who.int``) to enable live fetches. Without the trust
grant the skill loads and runs but degrades gracefully to an empty result list
with a logged diagnostic.
"""
