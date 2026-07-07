"""Wikidata entity JSON → properties dict parser.

Converts the raw Wikidata wbgetentities API response for one entity into a
flat, human-readable ``dict[str, object]`` suitable for downstream use or for
constructing a Document body.

Design notes
------------
* Wikidata snak values are typed (string, wikibase-entityid, time, quantity,
  monolingualtext, globecoordinate, …).  We collapse to plain Python types so
  downstream code does not need to know Wikidata's internal representation.
* For entity-id values (P-props that reference another Q-item) we return the
  Q-id string.  The caller can resolve it further with fetch_entity if needed.
* Multi-valued properties become lists; single-valued ones become the bare value.
* Only ``mainsnak`` values are parsed (qualifiers and references are dropped in
  this v1 implementation — the goal is "enough context for a research question",
  not a complete RDF dump).
* Unknown snak types are returned as their raw ``value`` dict (so nothing is
  silently lost).

This module is pure Python with no network access.

Usage::

    from lighthouse_ai.skills.library.wikidata.parsers.entity import (
        parse_entity_claims,
        extract_identifier_props,
        IDENTIFIER_PROPS,
    )

    claims = parse_entity_claims(entity_data)
    ids = extract_identifier_props(claims)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Well-known Wikidata property IDs for cross-source identifiers.
# These are the ones resolve_identifier exposes to the planner.
# ---------------------------------------------------------------------------

IDENTIFIER_PROPS: dict[str, str] = {
    "P496": "ORCID",
    "P214": "VIAF",
    "P345": "IMDb",
    "P213": "ISNI",
    "P18": "image",  # Commons image filename — useful for entity confirmation
    "P21": "sex_or_gender",
    "P569": "date_of_birth",
    "P570": "date_of_death",
    "P27": "country_of_citizenship",
    "P106": "occupation",
    "P19": "place_of_birth",
    "P856": "official_website",
    "P646": "Freebase_ID",
    "P698": "PubMed_ID",
    "P356": "DOI",
    "P1085": "LibraryThing_ID",
    "P244": "Library_of_Congress_identifier",
    "P245": "ULAN_identifier",
    "P227": "GND_identifier",
    "P349": "NDL_identifier",
    "P268": "BnF_identifier",
    "P269": "IdRef_identifier",
    "P906": "SELIBR_identifier",
    "P950": "BNE_identifier",
    "P1006": "NTA_identifier",
}


def _snak_to_value(snak: dict) -> object:
    """Convert a Wikidata snak to a plain Python value.

    Handles the most common datavalue types:

    * ``string``            → str
    * ``wikibase-entityid`` → "Q<n>" or "P<n>" string
    * ``time``              → ISO-8601 string (year precision: "1879", full: "1879-03-14T00:00:00Z")
    * ``quantity``          → str like "1.80 metre" or just the amount string
    * ``monolingualtext``   → the text string (language tag dropped)
    * ``globecoordinate``   → dict {lat, lon}
    * everything else       → the raw value dict
    """
    dv = snak.get("datavalue", {})
    dv_type = dv.get("type", "")
    val = dv.get("value", "")

    if dv_type == "string":
        return str(val)
    if dv_type == "wikibase-entityid":
        if isinstance(val, dict):
            etype = val.get("entity-type", "item")
            num = val.get("numeric-id", "")
            prefix = "Q" if etype == "item" else "P"
            return f"{prefix}{num}"
        return str(val)
    if dv_type == "time":
        if isinstance(val, dict):
            raw = val.get("time", "")
            # Wikidata time format: "+1879-03-14T00:00:00Z"
            # Strip leading sign and trailing time if it's midnight.
            ts = raw.lstrip("+-")
            if ts.endswith("T00:00:00Z"):
                ts = ts[: ts.index("T")]
            return ts
        return str(val)
    if dv_type == "quantity":
        if isinstance(val, dict):
            amount = val.get("amount", "")
            unit = val.get("unit", "1")
            # unit is a URL like http://www.wikidata.org/entity/Q11573
            # strip to just the Q-id
            if "/" in unit:
                unit = unit.rsplit("/", 1)[-1]
            if unit == "1":
                return str(amount).lstrip("+")
            return f"{str(amount).lstrip('+')} {unit}"
        return str(val)
    if dv_type == "monolingualtext":
        if isinstance(val, dict):
            return str(val.get("text", ""))
        return str(val)
    if dv_type == "globecoordinate":
        if isinstance(val, dict):
            return {"lat": val.get("latitude"), "lon": val.get("longitude")}
        return val
    # Unknown type: return raw
    return val


def parse_entity_claims(entity: dict) -> dict[str, object]:
    """Parse Wikidata entity claims into a flat ``{prop_id: value_or_list}`` dict.

    Parameters
    ----------
    entity:
        One entity dict as returned by ``wbgetentities`` (the value under the
        ``entities`` → ``Q<id>`` key).

    Returns
    -------
    dict[str, object]
        Property IDs (e.g. ``"P31"``) → plain Python value or list of values.
        Multi-valued properties become lists; single-valued ones are bare values.
    """
    claims = entity.get("claims", {})
    result: dict[str, object] = {}
    for prop_id, statements in claims.items():
        values: list[object] = []
        for stmt in statements:
            if stmt.get("rank") == "deprecated":
                continue
            mainsnak = stmt.get("mainsnak", {})
            if mainsnak.get("snaktype") != "value":
                continue
            v = _snak_to_value(mainsnak)
            values.append(v)
        if not values:
            continue
        result[prop_id] = values[0] if len(values) == 1 else values
    return result


def extract_identifier_props(claims: dict[str, object]) -> dict[str, object]:
    """Return a filtered dict of cross-source identifier claims.

    Parameters
    ----------
    claims:
        Output of :func:`parse_entity_claims`.

    Returns
    -------
    dict[str, object]
        ``{human_label: value}`` for each identifier property found in
        :data:`IDENTIFIER_PROPS` that is present in ``claims``.
    """
    ids: dict[str, object] = {}
    for prop_id, label in IDENTIFIER_PROPS.items():
        val = claims.get(prop_id)
        if val is not None:
            ids[label] = val
    return ids


def entity_label(entity: dict, lang: str = "en") -> str:
    """Return the entity's label in ``lang``, falling back to any available language."""
    labels = entity.get("labels", {})
    if lang in labels:
        return labels[lang].get("value", "")
    # fall back to first available
    for v in labels.values():
        return v.get("value", "")
    return ""


def entity_description(entity: dict, lang: str = "en") -> str:
    """Return the entity's description in ``lang``, falling back to any available."""
    descs = entity.get("descriptions", {})
    if lang in descs:
        return descs[lang].get("value", "")
    for v in descs.values():
        return v.get("value", "")
    return ""


def entity_aliases(entity: dict, lang: str = "en") -> list[str]:
    """Return alias strings for the entity in ``lang``."""
    aliases = entity.get("aliases", {})
    return [a.get("value", "") for a in aliases.get(lang, [])]
