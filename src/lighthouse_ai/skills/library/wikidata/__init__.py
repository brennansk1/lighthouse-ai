"""Wikidata research skill — structured knowledge graph, entity lookup, identifier resolution.

Provides entity search, property fetch, and cross-source identifier resolution
(person → ORCID + VIAF + IMDb + ISNI in one query) against the Wikidata REST
API (www.wikidata.org). All network access goes through SkillContext primitives;
the import guard enforces that this package never touches httpx/requests/urllib
directly.

EGRESS NOTE: wikidata.org and query.wikidata.org are NOT in the platform's
default allowlist (DEFAULT_ALLOWED_DOMAINS). ctx.fetch calls will raise
EgressBlocked until the user runs:

    lighthouse trust add wikidata.org

The skill handles this gracefully: run() degrades to [] with a logged note
rather than crashing. See SKILL.md for details.
"""
