"""ClinicalTrials.gov research skill — trial registry, endpoints, and amendments.

Provides search, individual trial fetch, endpoint extraction (pre-registered vs
reported), amendment chronology, and condition-based watchable browsing against
the ClinicalTrials.gov v2 REST API. All network access goes through
SkillContext primitives; the import guard enforces that this package never
touches httpx/requests/urllib directly.

**Egress requirement:** ``clinicaltrials.gov`` must be on the platform allowlist.
Run ``lighthouse trust add clinicaltrials.gov`` to enable live fetches. Without
the trust grant the skill loads and runs but degrades gracefully to an empty
result list with a logged diagnostic.
"""
