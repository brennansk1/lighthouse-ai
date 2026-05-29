"""Wikipedia research skill — encyclopedic orientation and factual lookup.

Provides search, full-page fetch, infobox extraction, category traversal, and
recent-revision monitoring against the English Wikipedia REST/Action API. All
network access goes through SkillContext primitives; the import guard enforces
that this package never touches httpx/requests/urllib directly.
"""
