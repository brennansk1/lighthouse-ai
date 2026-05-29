"""regulations.gov research skill — public comment dockets and rulemaking participation.

Provides docket search, individual docket fetch, public comment listing
(watchable), and docket activity tracking against the Regulations.gov API v4.
All network access goes through SkillContext primitives; the import guard
enforces that this package never touches httpx/requests/urllib directly.

**Egress requirement:** ``api.regulations.gov`` must be on the platform
allowlist. Run ``lighthouse trust add api.regulations.gov`` to enable live
fetches. Without the trust grant the skill loads and runs but degrades
gracefully to an empty result list with a logged diagnostic.

**API key requirement:** regulations.gov requires a free API key from
https://open.gsa.gov/api/regulationsgov/. Pass via the REGULATIONS_GOV_API_KEY
environment variable or skill configuration.
"""
