"""Offline tests for the Wikidata skill (SL2).

Placed in the project-level tests/ directory (not inside the skill folder) so
that the registry's import guard — which scans every .py file under the skill
directory — does not flag ``import httpx`` / ``import respx`` used here only
for mocking.

All network I/O is mocked via respx; no actual Wikidata requests are made.
Live tests (LIGHTHOUSE_REAL_BACKEND=1) are gated separately.

Test coverage
-------------
- manifest loads with correct fields (id, category, tier, signed, output_shape, …)
- import guard passes (no forbidden imports in the skill source tree)
- run() returns Documents tagged skill_id="wikidata" when fetch succeeds
- run() degrades to [] (no crash) on EgressBlocked
- search_entity tool parses canned JSON correctly
- fetch_entity tool parses canned JSON, returns None for missing entities
- get_properties tool returns a flat dict of claims
- resolve_identifier tool returns cross-source identifiers dict
- entity parser: parse_entity_claims, extract_identifier_props, entity_label
"""

from __future__ import annotations

import json
import os

import httpx
import pytest
import respx

from lighthouse_ai.net import EgressBlocked
from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.skills import load_skill, run_skill
from lighthouse_ai.skills.capabilities import build_context

# ---------------------------------------------------------------------------
# Canned API responses
# ---------------------------------------------------------------------------

SEARCH_JSON = json.dumps(
    {
        "searchinfo": {"search": "Albert Einstein"},
        "search": [
            {
                "id": "Q937",
                "title": "Q937",
                "pageid": 701,
                "repository": "wikidata",
                "url": "//www.wikidata.org/wiki/Q937",
                "concepturi": "http://www.wikidata.org/entity/Q937",
                "label": "Albert Einstein",
                "description": "German-born theoretical physicist (1879–1955)",
                "match": {"type": "label", "language": "en", "text": "Albert Einstein"},
                "aliases": ["Einstein"],
            }
        ],
        "success": 1,
    }
)

SEARCH_EMPTY_JSON = json.dumps(
    {
        "searchinfo": {"search": "xyzzy_nonexistent_99999"},
        "search": [],
        "success": 1,
    }
)

ENTITY_JSON = json.dumps(
    {
        "entities": {
            "Q937": {
                "type": "item",
                "id": "Q937",
                "labels": {
                    "en": {"language": "en", "value": "Albert Einstein"},
                },
                "descriptions": {
                    "en": {
                        "language": "en",
                        "value": "German-born theoretical physicist (1879–1955)",
                    },
                },
                "aliases": {
                    "en": [{"language": "en", "value": "Einstein"}],
                },
                "claims": {
                    "P496": [
                        {
                            "rank": "normal",
                            "mainsnak": {
                                "snaktype": "value",
                                "property": "P496",
                                "datavalue": {
                                    "value": "0000-0000-0000-0001",
                                    "type": "string",
                                },
                            },
                        }
                    ],
                    "P214": [
                        {
                            "rank": "normal",
                            "mainsnak": {
                                "snaktype": "value",
                                "property": "P214",
                                "datavalue": {
                                    "value": "75121530",
                                    "type": "string",
                                },
                            },
                        }
                    ],
                    "P213": [
                        {
                            "rank": "normal",
                            "mainsnak": {
                                "snaktype": "value",
                                "property": "P213",
                                "datavalue": {
                                    "value": "0000 0001 2097 2672",
                                    "type": "string",
                                },
                            },
                        }
                    ],
                    "P569": [
                        {
                            "rank": "normal",
                            "mainsnak": {
                                "snaktype": "value",
                                "property": "P569",
                                "datavalue": {
                                    "value": {
                                        "time": "+1879-03-14T00:00:00Z",
                                        "precision": 11,
                                        "calendarmodel": "http://www.wikidata.org/entity/Q1985727",
                                    },
                                    "type": "time",
                                },
                            },
                        }
                    ],
                    "P31": [
                        {
                            "rank": "normal",
                            "mainsnak": {
                                "snaktype": "value",
                                "property": "P31",
                                "datavalue": {
                                    "value": {
                                        "entity-type": "item",
                                        "numeric-id": 5,
                                        "id": "Q5",
                                    },
                                    "type": "wikibase-entityid",
                                },
                            },
                        }
                    ],
                },
            }
        },
        "success": 1,
    }
)

ENTITY_MISSING_JSON = json.dumps(
    {
        "entities": {
            "Q99999999": {
                "id": "Q99999999",
                "missing": "",
            }
        },
        "success": 1,
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Platform allowlist that includes wikidata.org so tests that mock the
# network can actually reach ctx.fetch (EgressBlocked is raised before
# the request if the domain is not allowlisted).
_WIKIDATA_ALLOWLIST: frozenset[str] = frozenset({"wikidata.org", "query.wikidata.org"})


def _make_client() -> httpx.Client:
    """Return a real httpx.Client; respx intercepts at the transport level."""
    return httpx.Client()


def _load_wikidata(tmp_path):
    """Load the in-tree wikidata skill and build a broker."""
    skill = load_skill("wikidata")
    broker = build_default_broker(tmp_path)
    return skill, broker


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def test_manifest_loads():
    skill = load_skill("wikidata")
    m = skill.manifest
    assert m.id == "wikidata"
    assert m.category == "reference"
    assert m.tier == "A"
    assert m.output_shape == "graph"
    assert m.default_grade == "B"
    assert m.signed is True
    assert m.watchable is False
    assert "wikidata.org" in m.allowed_domains
    assert "query.wikidata.org" in m.allowed_domains
    assert "investigate" in m.modes_natural_fit
    assert "ask" in m.modes_natural_fit
    assert "identifier_resolution" in m.question_types
    assert "factual_lookup" in m.question_types


def test_manifest_modes_weak_fit():
    skill = load_skill("wikidata")
    m = skill.manifest
    assert "survey" in m.modes_weak_fit
    assert "reconstruct" in m.modes_weak_fit


def test_manifest_output_shape_is_graph():
    skill = load_skill("wikidata")
    assert skill.manifest.output_shape == "graph"


# ---------------------------------------------------------------------------
# Import guard (no forbidden modules in skill source)
# ---------------------------------------------------------------------------


def test_import_guard_passes():
    """The skill must not import httpx, requests, urllib, etc. directly."""
    skill = load_skill("wikidata")
    assert skill.manifest.id == "wikidata"


# ---------------------------------------------------------------------------
# run() — documents tagged skill_id="wikidata"
# ---------------------------------------------------------------------------


@respx.mock
def test_run_returns_tagged_documents(tmp_path):
    """run() should return Documents with skill_id='wikidata'."""
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbsearchentities.*").mock(
        return_value=httpx.Response(200, content=SEARCH_JSON.encode())
    )
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbgetentities.*").mock(
        return_value=httpx.Response(200, content=ENTITY_JSON.encode())
    )

    skill, broker = _load_wikidata(tmp_path)
    result = run_skill(
        skill,
        "Albert Einstein",
        broker=broker,
        client=_make_client(),
        platform_allowlist=_WIKIDATA_ALLOWLIST,
    )
    assert result.ok, f"run_skill failed: {result.error}"
    assert len(result.documents) > 0
    for doc in result.documents:
        assert doc.metadata.get("skill_id") == "wikidata", doc.metadata
        assert doc.metadata.get("source") == "wikidata"
        assert doc.metadata.get("grade") == "B"


@respx.mock
def test_run_document_has_qid_and_url(tmp_path):
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbsearchentities.*").mock(
        return_value=httpx.Response(200, content=SEARCH_JSON.encode())
    )
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbgetentities.*").mock(
        return_value=httpx.Response(200, content=ENTITY_JSON.encode())
    )

    skill, broker = _load_wikidata(tmp_path)
    result = run_skill(
        skill,
        "Albert Einstein",
        broker=broker,
        client=_make_client(),
        platform_allowlist=_WIKIDATA_ALLOWLIST,
    )
    assert result.ok
    for doc in result.documents:
        assert doc.metadata.get("qid") == "Q937"
        url = doc.metadata.get("url", "")
        assert url.startswith("https://www.wikidata.org/wiki/"), (
            f"Expected Wikidata URL, got: {url!r}"
        )


@respx.mock
def test_run_document_has_identifiers(tmp_path):
    """Documents should carry a populated identifiers dict."""
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbsearchentities.*").mock(
        return_value=httpx.Response(200, content=SEARCH_JSON.encode())
    )
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbgetentities.*").mock(
        return_value=httpx.Response(200, content=ENTITY_JSON.encode())
    )

    skill, broker = _load_wikidata(tmp_path)
    result = run_skill(
        skill,
        "Albert Einstein",
        broker=broker,
        client=_make_client(),
        platform_allowlist=_WIKIDATA_ALLOWLIST,
    )
    assert result.ok
    doc = result.documents[0]
    ids = doc.metadata.get("identifiers", {})
    assert "ORCID" in ids or "VIAF" in ids or "ISNI" in ids, (
        f"Expected identifier fields, got: {ids}"
    )


@respx.mock
def test_run_empty_search_returns_no_documents(tmp_path):
    """When search returns no results, run() should return an empty list."""
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbsearchentities.*").mock(
        return_value=httpx.Response(200, content=SEARCH_EMPTY_JSON.encode())
    )

    skill, broker = _load_wikidata(tmp_path)
    result = run_skill(
        skill,
        "xyzzy_nonexistent_99999",
        broker=broker,
        client=_make_client(),
        platform_allowlist=_WIKIDATA_ALLOWLIST,
    )
    assert result.ok
    assert result.documents == []
    assert result.thin


@respx.mock
def test_run_signed_skill_no_community_tag(tmp_path):
    """Since wikidata is signed=True, documents must NOT have community=True."""
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbsearchentities.*").mock(
        return_value=httpx.Response(200, content=SEARCH_JSON.encode())
    )
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbgetentities.*").mock(
        return_value=httpx.Response(200, content=ENTITY_JSON.encode())
    )

    skill, broker = _load_wikidata(tmp_path)
    result = run_skill(
        skill,
        "Albert Einstein",
        broker=broker,
        client=_make_client(),
        platform_allowlist=_WIKIDATA_ALLOWLIST,
    )
    assert result.ok
    for doc in result.documents:
        assert "community" not in doc.metadata, (
            f"Signed skill must not emit community tag: {doc.metadata}"
        )


# ---------------------------------------------------------------------------
# EgressBlocked degradation
# ---------------------------------------------------------------------------


def test_run_egress_blocked_returns_empty_list(tmp_path):
    """run() must return [] (not crash) when EgressBlocked is raised."""
    skill, broker = _load_wikidata(tmp_path)
    ctx = build_context(
        skill.manifest,
        broker=broker,
        # Use the default allowlist (which does NOT include wikidata.org)
        platform_allowlist=frozenset(),  # empty allowlist → everything blocked
        client=_make_client(),
    )

    from lighthouse_ai.skills.library.wikidata.skill import run as wikidata_run

    # With empty effective_domains, ctx.fetch raises EgressBlocked.
    # run() should catch it and return [].
    result = wikidata_run(ctx, "Albert Einstein", max_results=3)
    assert result == [], f"Expected [] on EgressBlocked, got: {result}"


def test_run_egress_blocked_by_name_detection(tmp_path):
    """Verify the _is_egress_blocked helper identifies EgressBlocked by name."""
    from lighthouse_ai.skills.library.wikidata.skill import _is_egress_blocked

    exc = EgressBlocked("host 'www.wikidata.org' not in egress allowlist")
    assert _is_egress_blocked(exc) is True

    # Regular exceptions are not EgressBlocked
    assert _is_egress_blocked(ValueError("nope")) is False
    assert _is_egress_blocked(RuntimeError("timeout")) is False


def test_run_egress_blocked_wrapped_exception(tmp_path):
    """_is_egress_blocked should also detect EgressBlocked as __cause__."""
    from lighthouse_ai.skills.library.wikidata.skill import _is_egress_blocked

    inner = EgressBlocked("blocked")
    outer = RuntimeError("fetch failed")
    outer.__cause__ = inner
    assert _is_egress_blocked(outer) is True


# ---------------------------------------------------------------------------
# search_entity tool
# ---------------------------------------------------------------------------


@respx.mock
def test_search_entity_returns_hits(tmp_path):
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbsearchentities.*").mock(
        return_value=httpx.Response(200, content=SEARCH_JSON.encode())
    )

    skill, broker = _load_wikidata(tmp_path)
    ctx = build_context(
        skill.manifest, broker=broker, client=_make_client(), platform_allowlist=_WIKIDATA_ALLOWLIST
    )

    from lighthouse_ai.skills.library.wikidata.skill import search_entity

    hits = search_entity(ctx, "Albert Einstein", limit=5)
    assert len(hits) == 1
    assert hits[0]["id"] == "Q937"
    assert hits[0]["label"] == "Albert Einstein"
    assert "German-born" in hits[0]["description"]


@respx.mock
def test_search_entity_empty_result(tmp_path):
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbsearchentities.*").mock(
        return_value=httpx.Response(200, content=SEARCH_EMPTY_JSON.encode())
    )

    skill, broker = _load_wikidata(tmp_path)
    ctx = build_context(
        skill.manifest, broker=broker, client=_make_client(), platform_allowlist=_WIKIDATA_ALLOWLIST
    )

    from lighthouse_ai.skills.library.wikidata.skill import search_entity

    hits = search_entity(ctx, "xyzzy_nonexistent_99999", limit=5)
    assert hits == []


# ---------------------------------------------------------------------------
# fetch_entity tool
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_entity_returns_entity(tmp_path):
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbgetentities.*").mock(
        return_value=httpx.Response(200, content=ENTITY_JSON.encode())
    )

    skill, broker = _load_wikidata(tmp_path)
    ctx = build_context(
        skill.manifest, broker=broker, client=_make_client(), platform_allowlist=_WIKIDATA_ALLOWLIST
    )

    from lighthouse_ai.skills.library.wikidata.skill import fetch_entity

    entity = fetch_entity(ctx, "Q937")
    assert entity is not None
    assert entity["id"] == "Q937"
    assert "claims" in entity


@respx.mock
def test_fetch_entity_missing_returns_none(tmp_path):
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbgetentities.*").mock(
        return_value=httpx.Response(200, content=ENTITY_MISSING_JSON.encode())
    )

    skill, broker = _load_wikidata(tmp_path)
    ctx = build_context(
        skill.manifest, broker=broker, client=_make_client(), platform_allowlist=_WIKIDATA_ALLOWLIST
    )

    from lighthouse_ai.skills.library.wikidata.skill import fetch_entity

    entity = fetch_entity(ctx, "Q99999999")
    assert entity is None


# ---------------------------------------------------------------------------
# get_properties tool
# ---------------------------------------------------------------------------


@respx.mock
def test_get_properties_returns_claims_dict(tmp_path):
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbgetentities.*").mock(
        return_value=httpx.Response(200, content=ENTITY_JSON.encode())
    )

    skill, broker = _load_wikidata(tmp_path)
    ctx = build_context(
        skill.manifest, broker=broker, client=_make_client(), platform_allowlist=_WIKIDATA_ALLOWLIST
    )

    from lighthouse_ai.skills.library.wikidata.skill import get_properties

    props = get_properties(ctx, "Q937")
    assert isinstance(props, dict)
    # P496 = ORCID, should be present
    assert "P496" in props
    assert props["P496"] == "0000-0000-0000-0001"
    # P569 = date of birth (time type)
    assert "P569" in props
    assert "1879" in str(props["P569"])
    # P31 = instance of (entityid type → Q5 = human)
    assert "P31" in props
    assert props["P31"] == "Q5"


# ---------------------------------------------------------------------------
# resolve_identifier tool
# ---------------------------------------------------------------------------


@respx.mock
def test_resolve_identifier_returns_identifiers(tmp_path):
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbsearchentities.*").mock(
        return_value=httpx.Response(200, content=SEARCH_JSON.encode())
    )
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbgetentities.*").mock(
        return_value=httpx.Response(200, content=ENTITY_JSON.encode())
    )

    skill, broker = _load_wikidata(tmp_path)
    ctx = build_context(
        skill.manifest, broker=broker, client=_make_client(), platform_allowlist=_WIKIDATA_ALLOWLIST
    )

    from lighthouse_ai.skills.library.wikidata.skill import resolve_identifier

    ids = resolve_identifier(ctx, "Albert Einstein")
    assert ids.get("qid") == "Q937"
    assert ids.get("label") == "Albert Einstein"
    assert "ORCID" in ids or "VIAF" in ids, f"Expected identifier fields: {ids}"


@respx.mock
def test_resolve_identifier_empty_search_returns_empty(tmp_path):
    respx.get(url__regex=r"https://www\.wikidata\.org/w/api\.php\?action=wbsearchentities.*").mock(
        return_value=httpx.Response(200, content=SEARCH_EMPTY_JSON.encode())
    )

    skill, broker = _load_wikidata(tmp_path)
    ctx = build_context(
        skill.manifest, broker=broker, client=_make_client(), platform_allowlist=_WIKIDATA_ALLOWLIST
    )

    from lighthouse_ai.skills.library.wikidata.skill import resolve_identifier

    ids = resolve_identifier(ctx, "xyzzy_nonexistent_99999")
    assert ids == {}


# ---------------------------------------------------------------------------
# Entity parser (pure Python, no network)
# ---------------------------------------------------------------------------


def test_parse_entity_claims_string_type():
    from lighthouse_ai.skills.library.wikidata.parsers.entity import parse_entity_claims

    entity = {
        "claims": {
            "P496": [
                {
                    "rank": "normal",
                    "mainsnak": {
                        "snaktype": "value",
                        "property": "P496",
                        "datavalue": {"value": "0000-0001-2345-6789", "type": "string"},
                    },
                }
            ]
        }
    }
    claims = parse_entity_claims(entity)
    assert claims["P496"] == "0000-0001-2345-6789"


def test_parse_entity_claims_entityid_type():
    from lighthouse_ai.skills.library.wikidata.parsers.entity import parse_entity_claims

    entity = {
        "claims": {
            "P31": [
                {
                    "rank": "normal",
                    "mainsnak": {
                        "snaktype": "value",
                        "property": "P31",
                        "datavalue": {
                            "value": {"entity-type": "item", "numeric-id": 5, "id": "Q5"},
                            "type": "wikibase-entityid",
                        },
                    },
                }
            ]
        }
    }
    claims = parse_entity_claims(entity)
    assert claims["P31"] == "Q5"


def test_parse_entity_claims_time_type():
    from lighthouse_ai.skills.library.wikidata.parsers.entity import parse_entity_claims

    entity = {
        "claims": {
            "P569": [
                {
                    "rank": "normal",
                    "mainsnak": {
                        "snaktype": "value",
                        "property": "P569",
                        "datavalue": {
                            "value": {
                                "time": "+1879-03-14T00:00:00Z",
                                "precision": 11,
                                "calendarmodel": "http://www.wikidata.org/entity/Q1985727",
                            },
                            "type": "time",
                        },
                    },
                }
            ]
        }
    }
    claims = parse_entity_claims(entity)
    assert "1879" in claims["P569"]
    assert "03-14" in claims["P569"]


def test_parse_entity_claims_skips_deprecated():
    from lighthouse_ai.skills.library.wikidata.parsers.entity import parse_entity_claims

    entity = {
        "claims": {
            "P496": [
                {
                    "rank": "deprecated",
                    "mainsnak": {
                        "snaktype": "value",
                        "property": "P496",
                        "datavalue": {"value": "old-orcid", "type": "string"},
                    },
                },
                {
                    "rank": "preferred",
                    "mainsnak": {
                        "snaktype": "value",
                        "property": "P496",
                        "datavalue": {"value": "new-orcid", "type": "string"},
                    },
                },
            ]
        }
    }
    claims = parse_entity_claims(entity)
    assert claims["P496"] == "new-orcid"


def test_parse_entity_claims_multi_valued():
    from lighthouse_ai.skills.library.wikidata.parsers.entity import parse_entity_claims

    entity = {
        "claims": {
            "P106": [
                {
                    "rank": "normal",
                    "mainsnak": {
                        "snaktype": "value",
                        "property": "P106",
                        "datavalue": {
                            "value": {"entity-type": "item", "numeric-id": 169470, "id": "Q169470"},
                            "type": "wikibase-entityid",
                        },
                    },
                },
                {
                    "rank": "normal",
                    "mainsnak": {
                        "snaktype": "value",
                        "property": "P106",
                        "datavalue": {
                            "value": {"entity-type": "item", "numeric-id": 40348, "id": "Q40348"},
                            "type": "wikibase-entityid",
                        },
                    },
                },
            ]
        }
    }
    claims = parse_entity_claims(entity)
    assert isinstance(claims["P106"], list)
    assert len(claims["P106"]) == 2


def test_extract_identifier_props():
    from lighthouse_ai.skills.library.wikidata.parsers.entity import extract_identifier_props

    claims = {
        "P496": "0000-0001-2345-6789",  # ORCID
        "P214": "75121530",  # VIAF
        "P345": "nm0000001",  # IMDb
        "P31": "Q5",  # instance of (not an identifier)
    }
    ids = extract_identifier_props(claims)
    assert ids.get("ORCID") == "0000-0001-2345-6789"
    assert ids.get("VIAF") == "75121530"
    assert ids.get("IMDb") == "nm0000001"
    # P31 is not in IDENTIFIER_PROPS
    assert "Q5" not in ids.values()


def test_entity_label_en():
    from lighthouse_ai.skills.library.wikidata.parsers.entity import entity_label

    entity = {
        "labels": {
            "en": {"language": "en", "value": "Albert Einstein"},
            "de": {"language": "de", "value": "Albert Einstein"},
        }
    }
    assert entity_label(entity) == "Albert Einstein"


def test_entity_label_fallback():
    from lighthouse_ai.skills.library.wikidata.parsers.entity import entity_label

    # No English label — fall back to first available
    entity = {
        "labels": {
            "de": {"language": "de", "value": "Albert Einstein"},
        }
    }
    label = entity_label(entity)
    assert label == "Albert Einstein"


def test_entity_label_empty():
    from lighthouse_ai.skills.library.wikidata.parsers.entity import entity_label

    assert entity_label({}) == ""
    assert entity_label({"labels": {}}) == ""


def test_entity_description():
    from lighthouse_ai.skills.library.wikidata.parsers.entity import entity_description

    entity = {
        "descriptions": {
            "en": {"language": "en", "value": "German-born theoretical physicist"},
        }
    }
    assert entity_description(entity) == "German-born theoretical physicist"


def test_entity_aliases():
    from lighthouse_ai.skills.library.wikidata.parsers.entity import entity_aliases

    entity = {
        "aliases": {
            "en": [
                {"language": "en", "value": "Einstein"},
                {"language": "en", "value": "A. Einstein"},
            ]
        }
    }
    aliases = entity_aliases(entity)
    assert "Einstein" in aliases
    assert "A. Einstein" in aliases


# ---------------------------------------------------------------------------
# URL encoder (unit test — no network)
# ---------------------------------------------------------------------------


def test_url_encode_spaces():
    from lighthouse_ai.skills.library.wikidata.skill import _url_encode

    assert _url_encode("Albert Einstein") == "Albert+Einstein"


def test_url_encode_safe_chars():
    from lighthouse_ai.skills.library.wikidata.skill import _url_encode

    assert _url_encode("Q937") == "Q937"
    assert _url_encode("abc-123_xyz") == "abc-123_xyz"


def test_url_encode_unicode():
    from lighthouse_ai.skills.library.wikidata.skill import _url_encode

    encoded = _url_encode("Ångström")
    assert "%" in encoded  # non-ASCII should be percent-encoded


# ---------------------------------------------------------------------------
# Live-network gate
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.getenv("LIGHTHOUSE_REAL_BACKEND"),
    reason="Live network test; set LIGHTHOUSE_REAL_BACKEND=1 to enable",
)
def test_live_wikidata_run(tmp_path):
    """End-to-end smoke test against the real Wikidata API.

    Requires that wikidata.org is in the platform allowlist (lighthouse trust add wikidata.org).
    """
    skill, broker = _load_wikidata(tmp_path)
    result = run_skill(skill, "Albert Einstein", broker=broker)
    assert result.ok
    assert len(result.documents) > 0
    doc = result.documents[0]
    assert doc.metadata.get("skill_id") == "wikidata"
    assert doc.metadata.get("qid", "").startswith("Q")
