"""Congress.gov research skill — bills, votes, committees, and member activity.

Provides bill search, individual bill fetch, vote/action record retrieval,
and committee tracking (watchable) against the Congress.gov API v3. All
network access goes through SkillContext primitives; the import guard enforces
that this package never touches httpx/requests/urllib directly.

**Egress requirement:** ``api.congress.gov`` must be on the platform allowlist.
Run ``lighthouse trust add api.congress.gov`` to enable live fetches. Without
the trust grant the skill loads and runs but degrades gracefully to an empty
result list with a logged diagnostic.

**API key requirement:** A free key from https://api.congress.gov/sign-up/ is
required.
"""
