"""Offline tests for the Wikipedia skill.

Placed in the project-level tests/ directory (not inside the skill folder) so
that the registry's import guard — which scans every .py file under the skill
directory — does not flag ``import httpx`` used here only for respx mocking.

All network I/O is mocked via respx; no actual Wikipedia requests are made.
Live tests (LIGHTHOUSE_REAL_BACKEND=1) are gated separately.

Test coverage:
- manifest loads with the correct fields
- import guard passes (no forbidden imports in the skill source tree)
- run() returns Documents tagged skill_id="wikipedia"
- run_watchable() returns Documents for recent revisions
- infobox parser handles a real-looking wikitext fixture
- fetch_page and search tools parse canned JSON correctly
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import httpx
import pytest
import respx

from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.skills import load_skill, run_skill, run_watchable
from lighthouse_ai.skills.capabilities import build_context

# ---------------------------------------------------------------------------
# Fixtures / canned API responses
# ---------------------------------------------------------------------------

SEARCH_JSON = json.dumps({
    "query": {
        "search": [
            {
                "title": "Eiffel Tower",
                "pageid": 9974,
                "snippet": "A wrought-iron lattice tower on the Champ de Mars in Paris.",
            },
            {
                "title": "Eiffel (engineering firm)",
                "pageid": 12345,
                "snippet": "French industrial group named after Gustave Eiffel.",
            },
        ]
    }
})

SUMMARY_JSON = json.dumps({
    "type": "standard",
    "title": "Eiffel Tower",
    "extract": (
        "The Eiffel Tower is a wrought-iron lattice tower on the Champ de Mars in Paris, "
        "France. It is named after the engineer Gustave Eiffel, whose company designed and "
        "built the tower from 1887 to 1889."
    ),
    "description": "Landmark in Paris, France",
    "content_urls": {
        "desktop": {"page": "https://en.wikipedia.org/wiki/Eiffel_Tower"}
    },
})

EXTRACT_JSON = json.dumps({
    "query": {
        "pages": {
            "9974": {
                "pageid": 9974,
                "title": "Eiffel Tower",
                "extract": (
                    "The Eiffel Tower is a wrought-iron lattice tower. "
                    "== History ==\nBuilt 1887–1889 for the World's Fair."
                ),
            }
        }
    }
})

RECENTCHANGES_JSON = json.dumps({
    "query": {
        "recentchanges": [
            {
                "type": "edit",
                "ns": 0,
                "title": "Eiffel Tower",
                "pageid": 9974,
                "revid": 1111111,
                "timestamp": "2024-05-01T10:00:00Z",
                "user": "WikiEditor",
                "comment": "Updated visitor numbers",
            },
            {
                "type": "edit",
                "ns": 0,
                "title": "Berlin Wall",
                "pageid": 5678,
                "revid": 2222222,
                "timestamp": "2024-05-01T09:30:00Z",
                "user": "AnotherEditor",
                "comment": "Fixed date",
            },
        ]
    }
})

WIKITEXT_INFOBOX_JSON = json.dumps({
    "query": {
        "pages": [
            {
                "pageid": 9974,
                "title": "Eiffel Tower",
                "revisions": [
                    {
                        "slots": {
                            "main": {
                                "content": (
                                    "{{Infobox building\n"
                                    "| name = Eiffel Tower\n"
                                    "| image = Tour Eiffel Wikimedia Commons.jpg\n"
                                    "| location = Paris, France\n"
                                    "| built = 1887–1889\n"
                                    "| architect = [[Gustave Eiffel]]\n"
                                    "| height = {{convert|330|m|ft}}\n"
                                    "| floors = 3\n"
                                    "}}\n"
                                    "The Eiffel Tower is a wrought-iron lattice tower."
                                )
                            }
                        }
                    }
                ],
            }
        ]
    }
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client() -> httpx.Client:
    """Return the real httpx.Client; respx intercepts at the transport level."""
    return httpx.Client()


def _load_wikipedia(tmp_path):
    """Load the in-tree wikipedia skill and build a broker."""
    skill = load_skill("wikipedia")
    broker = build_default_broker(tmp_path)
    return skill, broker


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def test_manifest_loads():
    skill = load_skill("wikipedia")
    m = skill.manifest
    assert m.id == "wikipedia"
    assert m.category == "encyclopedia"
    assert m.tier == "A"
    assert m.output_shape == "lookup"
    assert m.default_grade == "C"
    assert m.signed is True
    assert m.watchable is True
    assert "recent_revisions" in m.watchable_tools
    assert "wikipedia.org" in m.allowed_domains
    assert "en.wikipedia.org" in m.allowed_domains
    assert "wikimedia.org" in m.allowed_domains
    assert "ask" in m.modes_natural_fit
    assert "investigate" in m.modes_natural_fit
    assert "reconstruct" in m.modes_natural_fit
    assert "survey" in m.modes_weak_fit
    assert "decide" in m.modes_weak_fit
    assert m.perspective_lens == "popular"
    assert m.temporal_tools is True
    assert "factual_lookup" in m.question_types
    assert "exploratory_survey" in m.question_types
    assert "causal_explanation" in m.question_types


def test_watchable_entrypoint_present():
    skill = load_skill("wikipedia")
    assert skill.watchable_entrypoint is not None
    assert callable(skill.watchable_entrypoint)


# ---------------------------------------------------------------------------
# Import guard (no forbidden modules in skill source)
# ---------------------------------------------------------------------------

def test_import_guard_passes():
    """The skill must not import httpx, requests, urllib, etc. directly.

    load_skill() runs the import guard over every .py in the skill folder;
    success here means the guard found no violations.
    """
    skill = load_skill("wikipedia")
    assert skill.manifest.id == "wikipedia"


# ---------------------------------------------------------------------------
# run() — documents tagged skill_id="wikipedia"
# ---------------------------------------------------------------------------

@respx.mock
def test_run_returns_tagged_documents(tmp_path):
    """run() should return Documents with skill_id="wikipedia"."""
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&list=search.*"
    ).mock(return_value=httpx.Response(200, content=SEARCH_JSON.encode()))
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/api/rest_v1/page/summary/.*"
    ).mock(return_value=httpx.Response(200, content=SUMMARY_JSON.encode()))
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&prop=extracts.*"
    ).mock(return_value=httpx.Response(200, content=EXTRACT_JSON.encode()))

    skill, broker = _load_wikipedia(tmp_path)
    result = run_skill(skill, "Eiffel Tower", broker=broker, client=_make_client())
    assert result.ok, f"run_skill failed: {result.error}"
    assert len(result.documents) > 0
    for doc in result.documents:
        assert doc.metadata.get("skill_id") == "wikipedia", doc.metadata
        assert doc.metadata.get("source") == "wikipedia"
        assert doc.metadata.get("grade") == "C"


@respx.mock
def test_run_document_has_url(tmp_path):
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&list=search.*"
    ).mock(return_value=httpx.Response(200, content=SEARCH_JSON.encode()))
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/api/rest_v1/page/summary/.*"
    ).mock(return_value=httpx.Response(200, content=SUMMARY_JSON.encode()))
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&prop=extracts.*"
    ).mock(return_value=httpx.Response(200, content=EXTRACT_JSON.encode()))

    skill, broker = _load_wikipedia(tmp_path)
    result = run_skill(skill, "Eiffel Tower", broker=broker, client=_make_client())
    assert result.ok
    for doc in result.documents:
        url = doc.metadata.get("url", "")
        assert url.startswith("https://"), f"Expected URL, got: {url!r}"


@respx.mock
def test_run_empty_search_returns_no_documents(tmp_path):
    """When search returns no results, run() should return an empty list."""
    empty = json.dumps({"query": {"search": []}})
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&list=search.*"
    ).mock(return_value=httpx.Response(200, content=empty.encode()))

    skill, broker = _load_wikipedia(tmp_path)
    result = run_skill(skill, "xyzzy_nonexistent_page_99999", broker=broker, client=_make_client())
    assert result.ok
    assert result.documents == []
    assert result.thin


@respx.mock
def test_run_signed_skill_no_community_tag(tmp_path):
    """Since wikipedia is signed=True, documents must NOT have community=True."""
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&list=search.*"
    ).mock(return_value=httpx.Response(200, content=SEARCH_JSON.encode()))
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/api/rest_v1/page/summary/.*"
    ).mock(return_value=httpx.Response(200, content=SUMMARY_JSON.encode()))
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&prop=extracts.*"
    ).mock(return_value=httpx.Response(200, content=EXTRACT_JSON.encode()))

    skill, broker = _load_wikipedia(tmp_path)
    result = run_skill(skill, "Eiffel Tower", broker=broker, client=_make_client())
    assert result.ok
    for doc in result.documents:
        assert "community" not in doc.metadata, (
            f"Signed skill must not emit community tag: {doc.metadata}"
        )


# ---------------------------------------------------------------------------
# run_watchable() — recent revisions
# ---------------------------------------------------------------------------

@respx.mock
def test_run_watchable_returns_revision_documents(tmp_path):
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&list=recentchanges.*"
    ).mock(return_value=httpx.Response(200, content=RECENTCHANGES_JSON.encode()))

    skill, broker = _load_wikipedia(tmp_path)
    result = run_watchable(
        skill, "Eiffel Tower", since=None, broker=broker, client=_make_client()
    )
    assert result.ok, f"run_watchable failed: {result.error}"
    assert len(result.documents) >= 1
    for doc in result.documents:
        assert doc.metadata.get("skill_id") == "wikipedia"
        assert doc.metadata.get("type") == "revision"
        assert doc.metadata.get("source") == "wikipedia"


@respx.mock
def test_run_watchable_since_parameter(tmp_path):
    """since= should be forwarded to the API without raising."""
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&list=recentchanges.*"
    ).mock(return_value=httpx.Response(200, content=RECENTCHANGES_JSON.encode()))

    skill, broker = _load_wikipedia(tmp_path)
    since = datetime(2024, 1, 1, tzinfo=UTC)
    result = run_watchable(
        skill, "Eiffel", since=since, broker=broker, client=_make_client()
    )
    assert result.ok


@respx.mock
def test_run_watchable_no_relevant_results(tmp_path):
    """When no recent changes match the query, return an empty list gracefully."""
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&list=recentchanges.*"
    ).mock(return_value=httpx.Response(200, content=RECENTCHANGES_JSON.encode()))

    skill, broker = _load_wikipedia(tmp_path)
    result = run_watchable(skill, "xyzzy", since=None, broker=broker, client=_make_client())
    assert result.ok
    assert result.documents == []


# ---------------------------------------------------------------------------
# Infobox parser (pure Python, no network)
# ---------------------------------------------------------------------------

def test_infobox_parser_extracts_fields():
    from lighthouse_ai.skills.library.wikipedia.parsers.infobox import parse_infobox

    wikitext = (
        "{{Infobox building\n"
        "| name = Eiffel Tower\n"
        "| location = Paris, France\n"
        "| built = 1887–1889\n"
        "| architect = [[Gustave Eiffel]]\n"
        "| height = 330 m\n"
        "}}\n"
        "The Eiffel Tower is a wrought-iron lattice tower."
    )
    fields = parse_infobox(wikitext)
    assert fields.get("name") == "Eiffel Tower"
    assert fields.get("location") == "Paris, France"
    assert fields.get("built") == "1887–1889"
    assert fields.get("architect") == "Gustave Eiffel"
    assert fields.get("height") == "330 m"


def test_infobox_parser_returns_empty_for_no_infobox():
    from lighthouse_ai.skills.library.wikipedia.parsers.infobox import parse_infobox

    wikitext = "This article has no infobox. Just plain text.\n\n== History ==\nContent here."
    assert parse_infobox(wikitext) == {}


def test_infobox_parser_strips_refs():
    from lighthouse_ai.skills.library.wikipedia.parsers.infobox import parse_infobox

    wikitext = (
        "{{Infobox person\n"
        "| name = Albert Einstein\n"
        "| birth_date = 14 March 1879<ref>{{cite ...}}</ref>\n"
        "| nationality = German-born Swiss-American\n"
        "}}\n"
    )
    fields = parse_infobox(wikitext)
    assert "ref" not in fields.get("birth_date", "")
    assert "1879" in fields.get("birth_date", "")
    assert fields.get("name") == "Albert Einstein"


def test_infobox_parser_handles_nested_templates():
    from lighthouse_ai.skills.library.wikipedia.parsers.infobox import parse_infobox

    wikitext = (
        "{{Infobox building\n"
        "| name = Test Building\n"
        "| height = {{convert|100|m|ft}}\n"
        "| opened = 2000\n"
        "}}\n"
    )
    fields = parse_infobox(wikitext)
    assert fields.get("name") == "Test Building"
    assert fields.get("opened") == "2000"
    assert "height" in fields


def test_infobox_parser_case_insensitive():
    from lighthouse_ai.skills.library.wikipedia.parsers.infobox import parse_infobox

    wikitext = "{{infobox person\n| name = Someone\n| age = 42\n}}\n"
    fields = parse_infobox(wikitext)
    assert fields.get("name") == "Someone"
    assert fields.get("age") == "42"


# ---------------------------------------------------------------------------
# extract_infobox tool (with mocked fetch)
# ---------------------------------------------------------------------------

@respx.mock
def test_extract_infobox_tool(tmp_path):
    """extract_infobox should fetch wikitext and return parsed fields."""
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&prop=revisions.*"
    ).mock(return_value=httpx.Response(200, content=WIKITEXT_INFOBOX_JSON.encode()))

    skill, broker = _load_wikipedia(tmp_path)
    ctx = build_context(skill.manifest, broker=broker, client=_make_client())

    from lighthouse_ai.skills.library.wikipedia.tools.extract_infobox import extract_infobox
    fields = extract_infobox(ctx, "Eiffel Tower")

    assert fields.get("name") == "Eiffel Tower"
    assert fields.get("location") == "Paris, France"
    assert fields.get("built") == "1887–1889"
    assert fields.get("floors") == "3"
    assert fields.get("architect") == "Gustave Eiffel"


# ---------------------------------------------------------------------------
# search tool (unit test with mocked fetch)
# ---------------------------------------------------------------------------

@respx.mock
def test_search_tool_returns_hits(tmp_path):
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&list=search.*"
    ).mock(return_value=httpx.Response(200, content=SEARCH_JSON.encode()))

    skill, broker = _load_wikipedia(tmp_path)
    ctx = build_context(skill.manifest, broker=broker, client=_make_client())

    from lighthouse_ai.skills.library.wikipedia.tools.search import search
    hits = search(ctx, "Eiffel Tower", limit=5)
    assert len(hits) == 2
    assert hits[0]["title"] == "Eiffel Tower"
    assert "en.wikipedia.org/wiki/" in hits[0]["url"]


# ---------------------------------------------------------------------------
# fetch_page tool
# ---------------------------------------------------------------------------

@respx.mock
def test_fetch_page_summary(tmp_path):
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/api/rest_v1/page/summary/.*"
    ).mock(return_value=httpx.Response(200, content=SUMMARY_JSON.encode()))

    skill, broker = _load_wikipedia(tmp_path)
    ctx = build_context(skill.manifest, broker=broker, client=_make_client())

    from lighthouse_ai.skills.library.wikipedia.tools.fetch_page import fetch_page
    doc = fetch_page(ctx, "Eiffel Tower", full_extract=False)
    assert doc is not None
    assert "Eiffel Tower" in doc.text
    assert doc.metadata["source"] == "wikipedia"
    assert doc.metadata["title"] == "Eiffel Tower"


@respx.mock
def test_fetch_page_404_returns_none(tmp_path):
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/api/rest_v1/page/summary/.*"
    ).mock(return_value=httpx.Response(404, content=b'{"type":"not_found"}'))

    skill, broker = _load_wikipedia(tmp_path)
    ctx = build_context(skill.manifest, broker=broker, client=_make_client())

    from lighthouse_ai.skills.library.wikipedia.tools.fetch_page import fetch_page
    doc = fetch_page(ctx, "NonExistentPage99999XYZ", full_extract=False)
    assert doc is None


@respx.mock
def test_fetch_page_full_extract(tmp_path):
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&prop=extracts.*"
    ).mock(return_value=httpx.Response(200, content=EXTRACT_JSON.encode()))

    skill, broker = _load_wikipedia(tmp_path)
    ctx = build_context(skill.manifest, broker=broker, client=_make_client())

    from lighthouse_ai.skills.library.wikipedia.tools.fetch_page import fetch_page
    doc = fetch_page(ctx, "Eiffel Tower", full_extract=True)
    assert doc is not None
    assert "History" in doc.text
    assert doc.metadata["type"] == "extract"


# ---------------------------------------------------------------------------
# walk_category tool
# ---------------------------------------------------------------------------

@respx.mock
def test_walk_category_returns_pages(tmp_path):
    cat_json = json.dumps({
        "query": {
            "categorymembers": [
                {"title": "Solar power", "ns": 0, "pageid": 101},
                {"title": "Wind power", "ns": 0, "pageid": 102},
                {"title": "Category:Solar energy", "ns": 14, "pageid": 200},
            ]
        }
    })
    respx.get(
        url__regex=r"https://en\.wikipedia\.org/w/api\.php\?action=query&list=categorymembers.*"
    ).mock(return_value=httpx.Response(200, content=cat_json.encode()))

    skill, broker = _load_wikipedia(tmp_path)
    ctx = build_context(skill.manifest, broker=broker, client=_make_client())

    from lighthouse_ai.skills.library.wikipedia.tools.walk_category import walk_category
    pages = walk_category(ctx, "Renewable energy", include_subcategories=False)
    titles = [p["title"] for p in pages]
    assert "Solar power" in titles
    assert "Wind power" in titles


# ---------------------------------------------------------------------------
# Live-network gate
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("LIGHTHOUSE_REAL_BACKEND"),
    reason="Live network test; set LIGHTHOUSE_REAL_BACKEND=1 to enable",
)
def test_live_wikipedia_run(tmp_path):
    """End-to-end smoke test against the real Wikipedia API."""
    skill, broker = _load_wikipedia(tmp_path)
    result = run_skill(skill, "Eiffel Tower", broker=broker)
    assert result.ok
    assert len(result.documents) > 0
    doc = result.documents[0]
    assert doc.metadata.get("skill_id") == "wikipedia"
    assert "Eiffel" in doc.text
