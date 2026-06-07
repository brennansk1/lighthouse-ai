"""Tests for the Semantic Scholar, SEC EDGAR, and CourtListener source adapters.

All HTTP is respx-mocked; no real network is touched. Each adapter follows the
same injectable-client pattern as crossref.py and pubmed.py, so the fixtures
use respx.mock and pass an httpx.Client into each adapter function.

Live integration tests are gated behind the LIGHTHOUSE_REAL_BACKEND environment
variable — they are skipped in CI and local unit-test runs.
"""

from __future__ import annotations

import os

import httpx
import pytest
import respx

from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.sources.courtlistener import search_courtlistener
from lighthouse_ai.sources.sec_edgar import search_sec_edgar
from lighthouse_ai.sources.semantic_scholar import search_semantic_scholar

# ---------------------------------------------------------------------------
# Fixtures: canned JSON payloads
# ---------------------------------------------------------------------------

# --- Semantic Scholar ---

S2_JSON = {
    "data": [
        {
            "paperId": "abc123",
            "title": "Attention Is All You Need",
            "abstract": "We propose a model architecture based solely on attention mechanisms.",
            "year": 2017,
            "citationCount": 50000,
            "url": "https://www.semanticscholar.org/paper/abc123",
        },
        {
            "paperId": "def456",
            "title": "BERT: Pre-training of Deep Bidirectional Transformers",
            "abstract": "We introduce BERT.",
            "year": 2019,
            "citationCount": 40000,
            "url": "https://www.semanticscholar.org/paper/def456",
        },
    ]
}

S2_EMPTY_JSON: dict = {"data": []}

S2_NOTITLE_JSON = {
    "data": [
        {"paperId": "zzz999", "title": "", "abstract": "Orphan abstract.", "year": 2020,
         "citationCount": 0, "url": "https://www.semanticscholar.org/paper/zzz999"},
    ]
}

# --- SEC EDGAR ---

SEC_JSON = {
    "hits": {
        "hits": [
            {
                "_id": "0001234567-24-000001",
                "_source": {
                    "accession_no": "0001234567-24-000001",
                    "entity_name": "Acme Corp",
                    "form_type": "10-K",
                    "file_date": "2024-03-15",
                    "cik": "1234567",
                    "display_names": ["Acme Corp (CIK 0001234567)"],
                },
                "highlight": {"file_text": ["revenue increased significantly"]},
            },
            {
                "_id": "0007654321-24-000002",
                "_source": {
                    "accession_no": "0007654321-24-000002",
                    "entity_name": "Widgets Inc",
                    "form_type": "8-K",
                    "file_date": "2024-01-10",
                    "cik": "7654321",
                    "display_names": [],
                },
                "highlight": {},
            },
        ]
    }
}

SEC_EMPTY_JSON: dict = {"hits": {"hits": []}}

SEC_NOTITLE_JSON: dict = {
    "hits": {
        "hits": [
            {
                "_id": "",
                "_source": {
                    "accession_no": "",
                    "entity_name": "",
                    "form_type": "",
                    "file_date": "",
                    "cik": "",
                    "display_names": [],
                },
                "highlight": {},
            }
        ]
    }
}

# --- CourtListener ---

CL_JSON = {
    "results": [
        {
            "cluster_id": 99001,
            "caseName": "Brown v. Board of Education",
            "snippet": "Separate educational facilities are inherently unequal.",
            "absolute_url": "/opinion/99001/brown-v-board-of-education/",
            "dateFiled": "1954-05-17",
            "court": "scotus",
        },
        {
            "cluster_id": 99002,
            "caseName": "Marbury v. Madison",
            "snippet": "It is emphatically the province of the judicial department.",
            "absolute_url": "/opinion/99002/marbury-v-madison/",
            "dateFiled": "1803-02-24",
            "court": "scotus",
        },
    ]
}

CL_EMPTY_JSON: dict = {"results": []}

CL_NOCASE_JSON: dict = {
    "results": [
        {"cluster_id": 11111, "caseName": "", "case_name": "",
         "snippet": "Orphan snippet."},
    ]
}

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mocked_http():
    with respx.mock(assert_all_called=False) as m:
        yield m


# ---------------------------------------------------------------------------
# Helper route builders (mirror the pattern in test_specialty_sources.py)
# ---------------------------------------------------------------------------

def _s2_ok(m, payload=S2_JSON):
    m.get("https://api.semanticscholar.org/graph/v1/paper/search").respond(
        200, json=payload
    )


def _sec_ok(m, payload=SEC_JSON):
    m.get("https://efts.sec.gov/LATEST/search-index").respond(200, json=payload)


def _cl_ok(m, payload=CL_JSON):
    m.get("https://www.courtlistener.com/api/rest/v4/search/").respond(
        200, json=payload
    )


# ===========================================================================
# Semantic Scholar
# ===========================================================================


def test_s2_returns_documents(mocked_http):
    _s2_ok(mocked_http)
    docs = search_semantic_scholar("transformers")
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)


def test_s2_title_and_abstract_in_text(mocked_http):
    _s2_ok(mocked_http)
    doc = search_semantic_scholar("transformers")[0]
    assert "Attention Is All You Need" in doc.text
    assert "attention mechanisms" in doc.text


def test_s2_metadata_source_and_grade(mocked_http):
    _s2_ok(mocked_http)
    doc = search_semantic_scholar("transformers")[0]
    assert doc.metadata["source"] == "semantic_scholar"
    assert doc.metadata["grade"] == "A"


def test_s2_metadata_title(mocked_http):
    _s2_ok(mocked_http)
    doc = search_semantic_scholar("transformers")[0]
    assert doc.metadata["title"] == "Attention Is All You Need"


def test_s2_metadata_url(mocked_http):
    _s2_ok(mocked_http)
    doc = search_semantic_scholar("transformers")[0]
    assert doc.metadata["url"] == "https://www.semanticscholar.org/paper/abc123"


def test_s2_metadata_published_date(mocked_http):
    _s2_ok(mocked_http)
    doc = search_semantic_scholar("transformers")[0]
    assert doc.metadata["published_date"] == "2017"


def test_s2_metadata_citation_count(mocked_http):
    _s2_ok(mocked_http)
    doc = search_semantic_scholar("transformers")[0]
    assert doc.metadata["citation_count"] == 50000


def test_s2_document_id_uses_paper_id(mocked_http):
    _s2_ok(mocked_http)
    doc = search_semantic_scholar("transformers")[0]
    assert doc.id == "s2:abc123"


def test_s2_empty_results(mocked_http):
    _s2_ok(mocked_http, S2_EMPTY_JSON)
    assert search_semantic_scholar("nothing") == []


def test_s2_skips_items_without_title(mocked_http):
    _s2_ok(mocked_http, S2_NOTITLE_JSON)
    assert search_semantic_scholar("x") == []


def test_s2_respects_max_results(mocked_http):
    route = mocked_http.get(
        "https://api.semanticscholar.org/graph/v1/paper/search"
    ).respond(200, json=S2_JSON)
    search_semantic_scholar("transformers", max_results=7)
    assert route.calls.last.request.url.params["limit"] == "7"


def test_s2_raises_on_http_error(mocked_http):
    mocked_http.get(
        "https://api.semanticscholar.org/graph/v1/paper/search"
    ).respond(429)
    with pytest.raises(httpx.HTTPStatusError):
        search_semantic_scholar("x")


def test_s2_uses_injected_client(mocked_http):
    _s2_ok(mocked_http)
    with httpx.Client() as client:
        docs = search_semantic_scholar("transformers", client=client)
        assert len(docs) == 2
        # Injected client must remain open after the call.
        assert not client.is_closed


def test_s2_api_key_sent_as_header(mocked_http):
    route = mocked_http.get(
        "https://api.semanticscholar.org/graph/v1/paper/search"
    ).respond(200, json=S2_JSON)
    search_semantic_scholar("transformers", api_key="mykey")
    assert route.calls.last.request.headers.get("x-api-key") == "mykey"


def test_s2_no_api_key_no_header(mocked_http):
    route = mocked_http.get(
        "https://api.semanticscholar.org/graph/v1/paper/search"
    ).respond(200, json=S2_JSON)
    search_semantic_scholar("transformers")
    assert "x-api-key" not in route.calls.last.request.headers


# ===========================================================================
# SEC EDGAR
# ===========================================================================


def test_sec_returns_documents(mocked_http):
    _sec_ok(mocked_http)
    docs = search_sec_edgar("revenue")
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)


def test_sec_title_from_entity_and_form_type(mocked_http):
    _sec_ok(mocked_http)
    doc = search_sec_edgar("revenue")[0]
    assert doc.metadata["title"] == "Acme Corp — 10-K"


def test_sec_metadata_source_and_grade(mocked_http):
    _sec_ok(mocked_http)
    doc = search_sec_edgar("revenue")[0]
    assert doc.metadata["source"] == "sec_edgar"
    assert doc.metadata["grade"] == "B"


def test_sec_metadata_published_date(mocked_http):
    _sec_ok(mocked_http)
    doc = search_sec_edgar("revenue")[0]
    assert doc.metadata["published_date"] == "2024-03-15"


def test_sec_metadata_form_type(mocked_http):
    _sec_ok(mocked_http)
    doc = search_sec_edgar("revenue")[0]
    assert doc.metadata["form_type"] == "10-K"


def test_sec_metadata_entity_name(mocked_http):
    _sec_ok(mocked_http)
    doc = search_sec_edgar("revenue")[0]
    assert doc.metadata["entity_name"] == "Acme Corp"


def test_sec_document_id_uses_accession(mocked_http):
    _sec_ok(mocked_http)
    doc = search_sec_edgar("revenue")[0]
    assert doc.id == "sec:0001234567-24-000001"


def test_sec_url_assembled_from_accession(mocked_http):
    _sec_ok(mocked_http)
    doc = search_sec_edgar("revenue")[0]
    # CIK 1234567 zero-padded to 10 digits, accession dashes stripped.
    assert "0001234567" in doc.metadata["url"]
    assert "000123456724000001" in doc.metadata["url"]


def test_sec_snippet_included_in_text(mocked_http):
    _sec_ok(mocked_http)
    doc = search_sec_edgar("revenue")[0]
    assert "revenue increased significantly" in doc.text


def test_sec_text_without_snippet_is_title_only(mocked_http):
    _sec_ok(mocked_http)
    doc = search_sec_edgar("revenue")[1]
    assert doc.text == "Widgets Inc — 8-K"


def test_sec_empty_results(mocked_http):
    _sec_ok(mocked_http, SEC_EMPTY_JSON)
    assert search_sec_edgar("nothing") == []


def test_sec_skips_items_without_title(mocked_http):
    _sec_ok(mocked_http, SEC_NOTITLE_JSON)
    assert search_sec_edgar("x") == []


def test_sec_raises_on_http_error(mocked_http):
    mocked_http.get("https://efts.sec.gov/LATEST/search-index").respond(503)
    with pytest.raises(httpx.HTTPStatusError):
        search_sec_edgar("x")


def test_sec_uses_injected_client(mocked_http):
    _sec_ok(mocked_http)
    with httpx.Client() as client:
        docs = search_sec_edgar("revenue", client=client)
        assert len(docs) == 2
        assert not client.is_closed


def test_sec_respects_max_results(mocked_http):
    route = mocked_http.get(
        "https://efts.sec.gov/LATEST/search-index"
    ).respond(200, json=SEC_JSON)
    search_sec_edgar("revenue", max_results=3)
    # The adapter passes max_results via hits.hits.total.value param.
    assert route.calls.last.request.url.params["hits.hits.total.value"] == "3"


# ===========================================================================
# CourtListener
# ===========================================================================


def test_cl_returns_documents(mocked_http):
    _cl_ok(mocked_http)
    docs = search_courtlistener("equal protection")
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)


def test_cl_title_is_case_name(mocked_http):
    _cl_ok(mocked_http)
    doc = search_courtlistener("equal protection")[0]
    assert doc.metadata["title"] == "Brown v. Board of Education"


def test_cl_metadata_source_and_grade(mocked_http):
    _cl_ok(mocked_http)
    doc = search_courtlistener("equal protection")[0]
    assert doc.metadata["source"] == "courtlistener"
    assert doc.metadata["grade"] == "B"


def test_cl_metadata_published_date(mocked_http):
    _cl_ok(mocked_http)
    doc = search_courtlistener("equal protection")[0]
    assert doc.metadata["published_date"] == "1954-05-17"


def test_cl_metadata_court(mocked_http):
    _cl_ok(mocked_http)
    doc = search_courtlistener("equal protection")[0]
    assert doc.metadata["court"] == "scotus"


def test_cl_snippet_in_text(mocked_http):
    _cl_ok(mocked_http)
    doc = search_courtlistener("equal protection")[0]
    assert "inherently unequal" in doc.text


def test_cl_url_is_absolute(mocked_http):
    _cl_ok(mocked_http)
    doc = search_courtlistener("equal protection")[0]
    assert doc.metadata["url"].startswith("https://www.courtlistener.com")
    assert "99001" in doc.metadata["url"]


def test_cl_document_id_uses_cluster_id(mocked_http):
    _cl_ok(mocked_http)
    doc = search_courtlistener("equal protection")[0]
    assert doc.id == "cl:99001"


def test_cl_empty_results(mocked_http):
    _cl_ok(mocked_http, CL_EMPTY_JSON)
    assert search_courtlistener("nothing") == []


def test_cl_skips_results_without_case_name(mocked_http):
    _cl_ok(mocked_http, CL_NOCASE_JSON)
    assert search_courtlistener("x") == []


def test_cl_respects_max_results(mocked_http):
    route = mocked_http.get(
        "https://www.courtlistener.com/api/rest/v4/search/"
    ).respond(200, json=CL_JSON)
    search_courtlistener("equal protection", max_results=10)
    assert route.calls.last.request.url.params["page_size"] == "10"


def test_cl_raises_on_http_error(mocked_http):
    mocked_http.get(
        "https://www.courtlistener.com/api/rest/v4/search/"
    ).respond(403)
    with pytest.raises(httpx.HTTPStatusError):
        search_courtlistener("x")


def test_cl_uses_injected_client(mocked_http):
    _cl_ok(mocked_http)
    with httpx.Client() as client:
        docs = search_courtlistener("equal protection", client=client)
        assert len(docs) == 2
        assert not client.is_closed


def test_cl_api_key_sent_as_token_header(mocked_http):
    route = mocked_http.get(
        "https://www.courtlistener.com/api/rest/v4/search/"
    ).respond(200, json=CL_JSON)
    search_courtlistener("equal protection", api_key="mytoken")
    assert route.calls.last.request.headers.get("authorization") == "Token mytoken"


def test_cl_no_api_key_no_auth_header(mocked_http):
    route = mocked_http.get(
        "https://www.courtlistener.com/api/rest/v4/search/"
    ).respond(200, json=CL_JSON)
    search_courtlistener("equal protection")
    assert "authorization" not in route.calls.last.request.headers


# ===========================================================================
# Live integration tests — skipped unless LIGHTHOUSE_REAL_BACKEND=1
# ===========================================================================

REAL = pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="set LIGHTHOUSE_REAL_BACKEND=1 to run live network tests",
)


@REAL
def test_live_semantic_scholar():
    import httpx
    try:
        docs = search_semantic_scholar("transformer neural network", max_results=3)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            pytest.skip(
                "Semantic Scholar rate-limited the keyless request (429) — "
                "environmental, not a code failure"
            )
        raise
    assert len(docs) >= 1
    assert all(d.metadata["source"] == "semantic_scholar" for d in docs)
    assert all(d.metadata["grade"] == "A" for d in docs)


@REAL
def test_live_sec_edgar():
    docs = search_sec_edgar("annual report", max_results=3)
    assert len(docs) >= 1
    assert all(d.metadata["source"] == "sec_edgar" for d in docs)
    assert all(d.metadata["grade"] == "B" for d in docs)


@REAL
def test_live_courtlistener():
    docs = search_courtlistener("first amendment", max_results=3)
    assert len(docs) >= 1
    assert all(d.metadata["source"] == "courtlistener" for d in docs)
    assert all(d.metadata["grade"] == "B" for d in docs)
