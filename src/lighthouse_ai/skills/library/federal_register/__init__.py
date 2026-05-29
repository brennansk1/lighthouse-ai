"""Federal Register research skill — rule notices, executive orders, and rulemaking.

Provides search over Federal Register documents, individual rule fetch,
recent-agency listings (watchable), executive order retrieval, and
NPRM→final rulemaking tracking against the FederalRegister.gov API v1.
All network access goes through SkillContext primitives; the import guard
enforces that this package never touches httpx/requests/urllib directly.

**Egress requirement:** ``federalregister.gov`` must be on the platform
allowlist. Run ``lighthouse trust add federalregister.gov`` to enable live
fetches. Without the trust grant the skill loads and runs but degrades
gracefully to an empty result list with a logged diagnostic.
"""
