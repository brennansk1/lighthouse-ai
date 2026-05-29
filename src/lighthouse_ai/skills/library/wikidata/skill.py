"""Wikidata skill entrypoints — ``run``.

All network access goes through ``ctx`` primitives (no httpx/requests/urllib).
The import guard in the registry enforces this statically.

EGRESS CAVEAT
-------------
wikidata.org and query.wikidata.org are NOT in the platform's default
``DEFAULT_ALLOWED_DOMAINS`` allowlist.  ``ctx.fetch`` will raise
``EgressBlocked`` if the user has not run::

    lighthouse trust add wikidata.org

The skill handles this gracefully: when ``EgressBlocked`` is caught the
entrypoints log a note and return ``[]``.  The skill still *loads* without
issue — only the runtime fetch path is blocked.

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("wikidata")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "Albert Einstein", broker=broker)
    for doc in result.documents:
        print(doc.metadata["label"], doc.metadata.get("identifiers", {}))
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from .parsers.entity import (
    entity_aliases,
    entity_description,
    entity_label,
    extract_identifier_props,
    parse_entity_claims,
)

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Wikidata Action API base URL
# ---------------------------------------------------------------------------

_API_BASE = "https://www.wikidata.org/w/api.php"

# Property IDs for commonly-requested identifiers (subset from parsers/entity.py)
_ORCID_PROP = "P496"
_VIAF_PROP  = "P214"
_IMDB_PROP  = "P345"
_ISNI_PROP  = "P213"


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using Wikidata.

    Strategy
    --------
    1. Search Wikidata for entities matching the question (wbsearchentities).
    2. For the top hits fetch full entity data (wbgetentities).
    3. Parse claims → flat properties dict; extract cross-source identifiers.
    4. Build one Document per entity via ctx.make_document.

    On EgressBlocked (wikidata.org not in the platform allowlist) the function
    logs a user-actionable note and returns [] without crashing.

    Parameters
    ----------
    ctx:
        Capability-restricted context (fetch + make_document only).
    question:
        The user's research question or entity name to look up.
    max_results:
        Maximum number of Documents to return (default 5).
    """
    try:
        hits = search_entity(ctx, question, limit=max_results)
    except Exception as exc:
        if _is_egress_blocked(exc):
            log.warning(
                "wikidata: EgressBlocked — wikidata.org is not in the platform allowlist. "
                "Run `lighthouse trust add wikidata.org` to enable this skill."
            )
            return []
        raise

    if not hits:
        return []

    docs: list[Document] = []
    seen: set[str] = set()

    for hit in hits[:max_results]:
        qid = hit.get("id", "")
        if not qid or qid in seen:
            continue
        seen.add(qid)

        try:
            entity = fetch_entity(ctx, qid)
        except Exception as exc:
            if _is_egress_blocked(exc):
                log.warning(
                    "wikidata: EgressBlocked fetching entity %s. "
                    "Run `lighthouse trust add wikidata.org` to enable this skill.",
                    qid,
                )
                return docs  # return whatever we managed before the block
            raise

        if entity is None:
            continue

        doc = _entity_to_document(ctx, qid, entity, hit)
        if doc is not None:
            docs.append(doc)

    return docs


# ---------------------------------------------------------------------------
# Named tools (used by run() and can be called directly in tests / planner)
# ---------------------------------------------------------------------------

def search_entity(
    ctx: SkillContext,
    query: str,
    *,
    limit: int = 5,
    language: str = "en",
) -> list[dict]:
    """Search Wikidata for entities matching ``query``.

    Uses the ``wbsearchentities`` Action API endpoint.

    Returns a list of dicts with keys: ``id``, ``label``, ``description``,
    ``url``.

    Raises ``EgressBlocked`` if wikidata.org is not in the allowlist.
    """
    params = (
        f"action=wbsearchentities"
        f"&search={_url_encode(query)}"
        f"&language={language}"
        f"&limit={min(limit, 50)}"
        f"&format=json"
        f"&uselang={language}"
    )
    url = f"{_API_BASE}?{params}"
    resp = ctx.fetch(url)
    try:
        data = json.loads(resp.content)
    except Exception:
        return []

    results: list[dict] = []
    for item in data.get("search", []):
        results.append({
            "id": item.get("id", ""),
            "label": item.get("label", ""),
            "description": item.get("description", ""),
            "url": item.get("url", f"https://www.wikidata.org/wiki/{item.get('id', '')}"),
            "match": item.get("match", {}),
        })
    return results


def fetch_entity(
    ctx: SkillContext,
    qid: str,
    *,
    language: str = "en",
) -> dict | None:
    """Fetch a Wikidata entity by Q-id and return the raw entity dict.

    Uses ``wbgetentities`` with ``props=labels|descriptions|aliases|claims``.
    Returns ``None`` when the entity is missing or the response is malformed.

    Raises ``EgressBlocked`` if wikidata.org is not in the allowlist.
    """
    params = (
        f"action=wbgetentities"
        f"&ids={_url_encode(qid)}"
        f"&languages={language}"
        f"&props=labels|descriptions|aliases|claims"
        f"&format=json"
    )
    url = f"{_API_BASE}?{params}"
    resp = ctx.fetch(url)
    try:
        data = json.loads(resp.content)
    except Exception:
        return None

    entities = data.get("entities", {})
    entity = entities.get(qid)
    if entity is None or entity.get("missing") is not None:
        return None
    return entity


def get_properties(
    ctx: SkillContext,
    qid: str,
    *,
    language: str = "en",
) -> dict[str, object]:
    """Return a flat ``{prop_id: value}`` dict for entity ``qid``.

    Fetches the entity (wbgetentities) and parses its claims.
    Returns an empty dict on error or if the entity does not exist.

    Raises ``EgressBlocked`` if wikidata.org is not in the allowlist.
    """
    entity = fetch_entity(ctx, qid, language=language)
    if entity is None:
        return {}
    return parse_entity_claims(entity)


def resolve_identifier(
    ctx: SkillContext,
    query: str,
    *,
    language: str = "en",
) -> dict[str, object]:
    """Resolve a person/entity name → cross-source identifiers.

    Searches for the entity, fetches the top result, and returns a dict
    containing ORCID, VIAF, IMDb, ISNI, and any other identifier properties
    found.  Includes ``qid``, ``label``, and ``description`` for context.

    Returns an empty dict when no entity is found or EgressBlocked.

    Raises ``EgressBlocked`` if wikidata.org is not in the allowlist.
    """
    hits = search_entity(ctx, query, limit=3, language=language)
    if not hits:
        return {}
    top = hits[0]
    qid = top.get("id", "")
    if not qid:
        return {}

    entity = fetch_entity(ctx, qid, language=language)
    if entity is None:
        return {}

    claims = parse_entity_claims(entity)
    identifiers = extract_identifier_props(claims)

    result: dict[str, object] = {
        "qid": qid,
        "label": entity_label(entity, language),
        "description": entity_description(entity, language),
        "url": f"https://www.wikidata.org/wiki/{qid}",
    }
    result.update(identifiers)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _entity_to_document(
    ctx: SkillContext,
    qid: str,
    entity: dict,
    hit: dict,
) -> Document | None:
    """Convert a Wikidata entity into a Document via ctx.make_document."""
    label = entity_label(entity)
    description = entity_description(entity)
    aliases = entity_aliases(entity)

    claims = parse_entity_claims(entity)
    identifiers = extract_identifier_props(claims)

    # Build human-readable text body
    lines: list[str] = []
    lines.append(f"Entity: {label}")
    if description:
        lines.append(f"Description: {description}")
    if aliases:
        lines.append(f"Also known as: {', '.join(a for a in aliases if a)}")
    if identifiers:
        lines.append("")
        lines.append("Cross-source identifiers:")
        for id_name, id_val in identifiers.items():
            lines.append(f"  {id_name}: {id_val}")
    if claims:
        lines.append("")
        lines.append(f"Properties ({len(claims)} total):")
        # Show a sample of non-identifier claims (up to 10)
        for i, (prop_id, val) in enumerate(claims.items()):
            if i >= 10:
                break
            lines.append(f"  {prop_id}: {val}")

    text = "\n".join(lines)
    if not text.strip():
        return None

    return ctx.make_document(
        doc_id=f"wikidata:{qid}",
        text=text,
        metadata={
            "source": "wikidata",
            "qid": qid,
            "label": label,
            "description": description,
            "url": f"https://www.wikidata.org/wiki/{qid}",
            "identifiers": identifiers,
            "type": "entity",
        },
    )


def _is_egress_blocked(exc: BaseException) -> bool:
    """Return True if exc is (or wraps) an EgressBlocked error."""
    # We cannot import EgressBlocked here without importing from lighthouse_ai.net,
    # which is NOT forbidden (it's a lighthouse module, not httpx/requests/urllib).
    # But to stay strictly within the import constraint (skill.py imports only
    # ctx + stdlib json), we detect by class name instead.
    cls = type(exc)
    if cls.__name__ == "EgressBlocked":
        return True
    # Also check cause/context in case it's wrapped
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    if cause is not None:
        return type(cause).__name__ == "EgressBlocked"
    return False


def _url_encode(text: str) -> str:
    """Percent-encode a string for a URL query parameter (stdlib only)."""
    safe = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789"
        "-_.~"
    )
    encoded: list[str] = []
    for ch in text.encode("utf-8"):
        c = chr(ch)
        if c in safe:
            encoded.append(c)
        elif c == " ":
            encoded.append("+")
        else:
            encoded.append(f"%{ch:02X}")
    return "".join(encoded)
