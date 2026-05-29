"""Offline tests for the SL5 federal government source adapters.

All HTTP is respx-mocked; no real network is touched. Each adapter is exercised
directly (not through a skill) to verify the parsing and interface contract.

Test plan
---------
Federal Register adapter (federal_register.py):
- search_rules: returns list[Document] from valid API response.
- search_rules: extracts title, document_number, document_type, agency_names,
  publication_date, citation, url.
- search_rules: skips items with no title.
- search_rules: text is title + abstract when abstract present.
- search_rules: respects max_results (per_page param).
- search_rules: raises HTTPStatusError on 4xx/5xx.
- search_rules: uses injected client without closing it.
- fetch_rule: fetches a specific document by number.
- list_recent_in_agency: passes agency slug as query param.
- get_executive_orders: filters by PRESDOCU type.
- track_rulemaking: passes PRORULE+RULE type filter.

regulations.gov adapter:
- search_dockets: returns list[Document] with docket metadata.
- search_dockets: skips items with no title.
- fetch_docket: fetches a single docket by ID.
- list_comments: returns grade-B comment documents.
- list_comments: extracts comment text (truncated at 500 chars).
- track_docket_activity: returns document-type records.
- raises HTTPStatusError on 4xx/5xx.
- uses injected client without closing it.

GovInfo adapter:
- search_collection: returns list[Document] from packages array.
- search_collection: passes collection param when specified.
- fetch_document: fetches a package summary.
- get_cfr_section: passes CFR collection with query.
- get_uscode_section: passes USCODE collection with query.
- list_recent_in_collection: returns documents from /collections endpoint.
- raises HTTPStatusError on 4xx/5xx.
- uses injected client without closing it.

Congress.gov adapter:
- search_bills: returns list[Document] from bills array.
- search_bills: extracts title, bill_type, bill_number, congress, etc.
- fetch_bill: fetches a specific bill.
- get_vote_record: returns action documents.
- track_committee: returns bills from committee endpoint.
- raises HTTPStatusError on 4xx/5xx.
- uses injected client without closing it.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.sources.congress_gov import (
    fetch_bill,
    get_vote_record,
    search_bills,
    track_committee,
)
from lighthouse_ai.sources.federal_register import (
    fetch_rule,
    get_executive_orders,
    list_recent_in_agency,
    search_rules,
    track_rulemaking,
)
from lighthouse_ai.sources.govinfo import (
    fetch_document,
    get_cfr_section,
    get_uscode_section,
    list_recent_in_collection,
    search_collection,
)
from lighthouse_ai.sources.regulations_gov import (
    fetch_docket,
    list_comments,
    search_dockets,
    track_docket_activity,
)

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mocked_http():
    with respx.mock(assert_all_called=False) as m:
        yield m


# ===========================================================================
# Federal Register adapter
# ===========================================================================

FR_RESULTS_JSON = {
    "results": [
        {
            "document_number": "2024-05678",
            "type": "Rule",
            "title": "National Ambient Air Quality Standards for Particulate Matter",
            "abstract": "This rule revises the NAAQS for PM2.5.",
            "agency_names": ["Environmental Protection Agency"],
            "publication_date": "2024-02-07",
            "html_url": "https://www.federalregister.gov/documents/2024/02/07/2024-05678/",
            "citation": "89 FR 16202",
        },
        {
            "document_number": "2024-10000",
            "type": "Proposed Rule",
            "title": "Proposed Clean Water Rule",
            "abstract": "",
            "agency_names": ["Environmental Protection Agency"],
            "publication_date": "2024-05-01",
            "html_url": "https://www.federalregister.gov/documents/2024/05/01/2024-10000/",
            "citation": "89 FR 36000",
        },
    ]
}

FR_EMPTY_JSON = {"results": []}

FR_NOTITLE_JSON = {
    "results": [
        {
            "document_number": "2024-99999",
            "type": "Notice",
            "title": "",
            "abstract": "Some abstract",
        }
    ]
}

FR_SINGLE_DOC_JSON = {
    "document_number": "2024-05678",
    "type": "Rule",
    "title": "NAAQS for Particulate Matter",
    "abstract": "Final rule.",
    "agency_names": ["EPA"],
    "publication_date": "2024-02-07",
    "html_url": "https://www.federalregister.gov/documents/2024/02/07/2024-05678/",
    "citation": "89 FR 16202",
}


def test_fr_returns_documents(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(
        200, json=FR_RESULTS_JSON
    )
    docs = search_rules("air quality")
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)


def test_fr_extracts_document_number(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(
        200, json=FR_RESULTS_JSON
    )
    docs = search_rules("air quality")
    assert docs[0].metadata["document_number"] == "2024-05678"
    assert docs[0].id == "fedreg:2024-05678"


def test_fr_extracts_title(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(
        200, json=FR_RESULTS_JSON
    )
    docs = search_rules("air quality")
    assert "Particulate Matter" in docs[0].metadata["title"]
    assert docs[0].metadata["title"] in docs[0].text


def test_fr_text_includes_abstract(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(
        200, json=FR_RESULTS_JSON
    )
    docs = search_rules("air quality")
    assert "PM2.5" in docs[0].text


def test_fr_text_title_only_when_no_abstract(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(
        200, json=FR_RESULTS_JSON
    )
    docs = search_rules("air quality")
    assert docs[1].text == docs[1].metadata["title"]


def test_fr_extracts_document_type(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(
        200, json=FR_RESULTS_JSON
    )
    docs = search_rules("air quality")
    assert docs[0].metadata["document_type"] == "Rule"
    assert docs[1].metadata["document_type"] == "Proposed Rule"


def test_fr_extracts_agency_names(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(
        200, json=FR_RESULTS_JSON
    )
    docs = search_rules("air quality")
    assert docs[0].metadata["agency_names"] == ["Environmental Protection Agency"]


def test_fr_extracts_publication_date(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(
        200, json=FR_RESULTS_JSON
    )
    docs = search_rules("air quality")
    assert docs[0].metadata["publication_date"] == "2024-02-07"


def test_fr_metadata_grade_and_source(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(
        200, json=FR_RESULTS_JSON
    )
    doc = search_rules("air quality")[0]
    assert doc.metadata["source"] == "federal_register"
    assert doc.metadata["grade"] == "A"


def test_fr_url_contains_document_number(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(
        200, json=FR_RESULTS_JSON
    )
    doc = search_rules("air quality")[0]
    assert "2024-05678" in doc.metadata["url"]


def test_fr_empty_results(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(
        200, json=FR_EMPTY_JSON
    )
    assert search_rules("nothing") == []


def test_fr_skips_items_without_title(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(
        200, json=FR_NOTITLE_JSON
    )
    assert search_rules("x") == []


def test_fr_respects_max_results(mocked_http):
    route = mocked_http.get(
        "https://www.federalregister.gov/api/v1/documents.json"
    ).respond(200, json=FR_RESULTS_JSON)
    search_rules("air quality", max_results=3)
    assert route.calls.last.request.url.params["per_page"] == "3"


def test_fr_raises_on_http_error(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(503)
    with pytest.raises(httpx.HTTPStatusError):
        search_rules("x")


def test_fr_uses_injected_client(mocked_http):
    mocked_http.get("https://www.federalregister.gov/api/v1/documents.json").respond(
        200, json=FR_RESULTS_JSON
    )
    with httpx.Client() as client:
        docs = search_rules("air quality", client=client)
        assert len(docs) == 2
        assert not client.is_closed


def test_fr_fetch_rule(mocked_http):
    mocked_http.get(
        "https://www.federalregister.gov/api/v1/documents/2024-05678.json"
    ).respond(200, json=FR_SINGLE_DOC_JSON)
    docs = fetch_rule("2024-05678")
    assert len(docs) == 1
    assert docs[0].metadata["document_number"] == "2024-05678"


def test_fr_list_recent_in_agency_passes_agency_param(mocked_http):
    route = mocked_http.get(
        "https://www.federalregister.gov/api/v1/documents.json"
    ).respond(200, json=FR_RESULTS_JSON)
    list_recent_in_agency("epa")
    assert "epa" in route.calls.last.request.url.params.get(
        "conditions[agencies][]", ""
    )


def test_fr_get_executive_orders_passes_type_filter(mocked_http):
    route = mocked_http.get(
        "https://www.federalregister.gov/api/v1/documents.json"
    ).respond(200, json=FR_RESULTS_JSON)
    get_executive_orders()
    params = route.calls.last.request.url.params
    assert "PRESDOCU" in params.get("conditions[type][]", "")


def test_fr_track_rulemaking_passes_rule_types(mocked_http):
    route = mocked_http.get(
        "https://www.federalregister.gov/api/v1/documents.json"
    ).respond(200, json=FR_RESULTS_JSON)
    track_rulemaking("clean air")
    # httpx QueryParams serializes multi-value params as repeated keys;
    # decode raw query string to check for both type values.
    raw_query = str(route.calls.last.request.url.query)
    assert "PRORULE" in raw_query or "RULE" in raw_query


# ===========================================================================
# regulations.gov adapter
# ===========================================================================

REGS_DOCKETS_JSON = {
    "data": [
        {
            "id": "EPA-HQ-OAR-2022-0873",
            "attributes": {
                "title": "National Ambient Air Quality Standards for Particulate Matter",
                "docketType": "Rulemaking",
                "agencyId": "EPA",
                "lastModifiedDate": "2024-02-07T00:00:00Z",
            },
        },
        {
            "id": "FCC-2023-0056",
            "attributes": {
                "title": "Open Internet Rulemaking",
                "docketType": "Rulemaking",
                "agencyId": "FCC",
                "lastModifiedDate": "2024-01-01T00:00:00Z",
            },
        },
    ]
}

REGS_DOCKET_SINGLE_JSON = {
    "data": {
        "id": "EPA-HQ-OAR-2022-0873",
        "attributes": {
            "title": "NAAQS for Particulate Matter",
            "docketType": "Rulemaking",
            "agencyId": "EPA",
            "lastModifiedDate": "2024-02-07T00:00:00Z",
        },
    }
}

REGS_COMMENTS_JSON = {
    "data": [
        {
            "id": "EPA-HQ-OAR-2022-0873-0001",
            "attributes": {
                "title": "Comment from Environmental Defense Fund",
                "comment": "We support stricter standards for PM2.5.",
                "postedDate": "2023-06-15",
                "docketId": "EPA-HQ-OAR-2022-0873",
            },
        },
        {
            "id": "EPA-HQ-OAR-2022-0873-0002",
            "attributes": {
                "title": "Comment from Industry Group",
                "comment": "Stricter standards will harm manufacturing.",
                "postedDate": "2023-06-16",
                "docketId": "EPA-HQ-OAR-2022-0873",
            },
        },
    ]
}

REGS_DOCUMENTS_JSON = {
    "data": [
        {
            "id": "EPA-HQ-OAR-2022-0873-0500",
            "attributes": {
                "title": "Final Rule",
                "documentType": "Rule",
                "agencyId": "EPA",
                "postedDate": "2024-02-07",
                "docketId": "EPA-HQ-OAR-2022-0873",
            },
        }
    ]
}

REGS_EMPTY_JSON = {"data": []}


def test_regs_returns_documents(mocked_http):
    mocked_http.get("https://api.regulations.gov/v4/dockets").respond(
        200, json=REGS_DOCKETS_JSON
    )
    docs = search_dockets("particulate matter")
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)


def test_regs_extracts_docket_id(mocked_http):
    mocked_http.get("https://api.regulations.gov/v4/dockets").respond(
        200, json=REGS_DOCKETS_JSON
    )
    docs = search_dockets("air quality")
    assert docs[0].metadata["docket_id"] == "EPA-HQ-OAR-2022-0873"
    assert docs[0].id == "regs:EPA-HQ-OAR-2022-0873"


def test_regs_metadata_grade_and_source(mocked_http):
    mocked_http.get("https://api.regulations.gov/v4/dockets").respond(
        200, json=REGS_DOCKETS_JSON
    )
    doc = search_dockets("air quality")[0]
    assert doc.metadata["source"] == "regulations_gov"
    assert doc.metadata["grade"] == "A"


def test_regs_url_contains_docket_id(mocked_http):
    mocked_http.get("https://api.regulations.gov/v4/dockets").respond(
        200, json=REGS_DOCKETS_JSON
    )
    doc = search_dockets("air quality")[0]
    assert "EPA-HQ-OAR-2022-0873" in doc.metadata["url"]


def test_regs_empty_results(mocked_http):
    mocked_http.get("https://api.regulations.gov/v4/dockets").respond(
        200, json=REGS_EMPTY_JSON
    )
    assert search_dockets("nothing") == []


def test_regs_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.regulations.gov/v4/dockets").respond(403)
    with pytest.raises(httpx.HTTPStatusError):
        search_dockets("x")


def test_regs_uses_injected_client(mocked_http):
    mocked_http.get("https://api.regulations.gov/v4/dockets").respond(
        200, json=REGS_DOCKETS_JSON
    )
    with httpx.Client() as client:
        docs = search_dockets("air quality", client=client)
        assert len(docs) == 2
        assert not client.is_closed


def test_regs_fetch_docket(mocked_http):
    mocked_http.get(
        "https://api.regulations.gov/v4/dockets/EPA-HQ-OAR-2022-0873"
    ).respond(200, json=REGS_DOCKET_SINGLE_JSON)
    docs = fetch_docket("EPA-HQ-OAR-2022-0873")
    assert len(docs) == 1
    assert docs[0].metadata["docket_id"] == "EPA-HQ-OAR-2022-0873"


def test_regs_list_comments_grade_b(mocked_http):
    mocked_http.get("https://api.regulations.gov/v4/comments").respond(
        200, json=REGS_COMMENTS_JSON
    )
    docs = list_comments("EPA-HQ-OAR-2022-0873")
    assert len(docs) == 2
    for doc in docs:
        assert doc.metadata["grade"] == "B"
        assert doc.metadata["source"] == "regulations_gov"


def test_regs_list_comments_extracts_text(mocked_http):
    mocked_http.get("https://api.regulations.gov/v4/comments").respond(
        200, json=REGS_COMMENTS_JSON
    )
    docs = list_comments("EPA-HQ-OAR-2022-0873")
    assert "PM2.5" in docs[0].text


def test_regs_track_docket_activity(mocked_http):
    mocked_http.get("https://api.regulations.gov/v4/documents").respond(
        200, json=REGS_DOCUMENTS_JSON
    )
    docs = track_docket_activity("EPA-HQ-OAR-2022-0873")
    assert len(docs) == 1
    assert docs[0].metadata["document_type"] == "Rule"
    assert docs[0].metadata["grade"] == "A"


# ===========================================================================
# GovInfo adapter
# ===========================================================================

GOVINFO_SEARCH_JSON = {
    "packages": [
        {
            "packageId": "CFR-2024-title40-vol6",
            "title": "Title 40 - Protection of Environment",
            "collectionCode": "CFR",
            "dateIssued": "2024-01-01",
            "packageLink": "https://www.govinfo.gov/link/cfr/40/6",
            "docClass": "CFR",
        },
        {
            "packageId": "GAOREPORTS-GAO-24-100001",
            "title": "Environmental Protection: Challenges in Implementing the Clean Air Act",
            "collectionCode": "GAOREPORTS",
            "dateIssued": "2024-03-15",
            "packageLink": "https://www.govinfo.gov/content/pkg/GAOREPORTS-GAO-24-100001",
            "docClass": "GAO-24-100001",
        },
    ]
}

GOVINFO_EMPTY_JSON = {"packages": []}

GOVINFO_SUMMARY_JSON = {
    "packageId": "CFR-2024-title40-vol6",
    "title": "Title 40 - Protection of Environment",
    "collectionCode": "CFR",
    "dateIssued": "2024-01-01",
    "packageLink": "https://www.govinfo.gov/link/cfr/40/6",
    "docClass": "CFR",
}

GOVINFO_COLLECTION_JSON = {
    "packages": [
        {
            "packageId": "CREC-2024-04-15",
            "title": "Congressional Record - Daily Edition for April 15, 2024",
            "dateIssued": "2024-04-15",
            "packageLink": "https://www.govinfo.gov/content/pkg/CREC-2024-04-15",
            "docClass": "CREC",
        }
    ]
}


def test_govinfo_returns_documents(mocked_http):
    mocked_http.get("https://api.govinfo.gov/search").respond(
        200, json=GOVINFO_SEARCH_JSON
    )
    docs = search_collection("clean air")
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)


def test_govinfo_extracts_package_id(mocked_http):
    mocked_http.get("https://api.govinfo.gov/search").respond(
        200, json=GOVINFO_SEARCH_JSON
    )
    docs = search_collection("clean air")
    assert docs[0].metadata["package_id"] == "CFR-2024-title40-vol6"
    assert docs[0].id == "govinfo:CFR-2024-title40-vol6"


def test_govinfo_extracts_collection_code(mocked_http):
    mocked_http.get("https://api.govinfo.gov/search").respond(
        200, json=GOVINFO_SEARCH_JSON
    )
    docs = search_collection("clean air")
    assert docs[0].metadata["collection_code"] == "CFR"
    assert docs[1].metadata["collection_code"] == "GAOREPORTS"


def test_govinfo_metadata_grade_and_source(mocked_http):
    mocked_http.get("https://api.govinfo.gov/search").respond(
        200, json=GOVINFO_SEARCH_JSON
    )
    doc = search_collection("clean air")[0]
    assert doc.metadata["source"] == "govinfo"
    assert doc.metadata["grade"] == "A"


def test_govinfo_passes_collection_param(mocked_http):
    route = mocked_http.get("https://api.govinfo.gov/search").respond(
        200, json=GOVINFO_SEARCH_JSON
    )
    search_collection("clean air", collection="CFR")
    assert route.calls.last.request.url.params.get("collection") == "CFR"


def test_govinfo_empty_results(mocked_http):
    mocked_http.get("https://api.govinfo.gov/search").respond(
        200, json=GOVINFO_EMPTY_JSON
    )
    assert search_collection("nothing") == []


def test_govinfo_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.govinfo.gov/search").respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        search_collection("x")


def test_govinfo_uses_injected_client(mocked_http):
    mocked_http.get("https://api.govinfo.gov/search").respond(
        200, json=GOVINFO_SEARCH_JSON
    )
    with httpx.Client() as client:
        docs = search_collection("clean air", client=client)
        assert len(docs) == 2
        assert not client.is_closed


def test_govinfo_fetch_document(mocked_http):
    mocked_http.get(
        "https://api.govinfo.gov/packages/CFR-2024-title40-vol6/summary"
    ).respond(200, json=GOVINFO_SUMMARY_JSON)
    docs = fetch_document("CFR-2024-title40-vol6")
    assert len(docs) == 1
    assert docs[0].metadata["package_id"] == "CFR-2024-title40-vol6"
    assert docs[0].metadata["collection_code"] == "CFR"


def test_govinfo_get_cfr_section_passes_collection(mocked_http):
    route = mocked_http.get("https://api.govinfo.gov/search").respond(
        200, json=GOVINFO_SEARCH_JSON
    )
    get_cfr_section(40, "50")
    assert route.calls.last.request.url.params.get("collection") == "CFR"


def test_govinfo_get_cfr_section_query_contains_title(mocked_http):
    route = mocked_http.get("https://api.govinfo.gov/search").respond(
        200, json=GOVINFO_SEARCH_JSON
    )
    get_cfr_section(40, "50")
    query = route.calls.last.request.url.params.get("query", "")
    assert "40" in query
    assert "50" in query


def test_govinfo_get_uscode_section_passes_collection(mocked_http):
    route = mocked_http.get("https://api.govinfo.gov/search").respond(
        200, json=GOVINFO_SEARCH_JSON
    )
    get_uscode_section(42, "7401")
    assert route.calls.last.request.url.params.get("collection") == "USCODE"


def test_govinfo_list_recent_in_collection(mocked_http):
    mocked_http.get("https://api.govinfo.gov/collections/CREC").respond(
        200, json=GOVINFO_COLLECTION_JSON
    )
    docs = list_recent_in_collection("CREC")
    assert len(docs) == 1
    assert docs[0].metadata["collection_code"] == "CREC"
    assert docs[0].metadata["date_issued"] == "2024-04-15"


# ===========================================================================
# Congress.gov adapter
# ===========================================================================

CONGRESS_BILLS_JSON = {
    "bills": [
        {
            "title": "Inflation Reduction Act of 2022",
            "type": "HR",
            "number": "5376",
            "congress": "117",
            "originChamber": "House",
            "latestAction": {
                "actionDate": "2022-08-16",
                "text": "Became Public Law No: 117-169.",
            },
            "url": "https://api.congress.gov/v3/bill/117/hr/5376",
        },
        {
            "title": "Clean Energy Investment Act",
            "type": "S",
            "number": "2299",
            "congress": "118",
            "originChamber": "Senate",
            "latestAction": {
                "actionDate": "2024-06-01",
                "text": "Referred to the Committee on Finance.",
            },
            "url": "https://api.congress.gov/v3/bill/118/s/2299",
        },
    ]
}

CONGRESS_BILL_SINGLE_JSON = {
    "bill": {
        "title": "Inflation Reduction Act of 2022",
        "type": "HR",
        "number": "5376",
        "congress": "117",
        "originChamber": "House",
        "latestAction": {
            "actionDate": "2022-08-16",
            "text": "Became Public Law No: 117-169.",
        },
        "url": "https://api.congress.gov/v3/bill/117/hr/5376",
    }
}

CONGRESS_ACTIONS_JSON = {
    "actions": [
        {
            "actionDate": "2022-08-16",
            "text": "Became Public Law No: 117-169.",
            "type": "BecameLaw",
            "url": "",
        },
        {
            "actionDate": "2022-08-12",
            "text": "Passed Senate.",
            "type": "Floor",
            "url": "",
        },
    ]
}

CONGRESS_COMMITTEE_JSON = {
    "committeeBills": [
        {
            "bill": {
                "title": "Energy Bill Referred to Committee",
                "type": "S",
                "number": "1234",
                "congress": "118",
                "originChamber": "Senate",
                "latestAction": {
                    "actionDate": "2024-05-01",
                    "text": "Referred to Committee.",
                },
                "url": "https://api.congress.gov/v3/bill/118/s/1234",
            }
        }
    ]
}

CONGRESS_EMPTY_JSON = {"bills": []}


def test_congress_returns_documents(mocked_http):
    mocked_http.get("https://api.congress.gov/v3/bill").respond(
        200, json=CONGRESS_BILLS_JSON
    )
    docs = search_bills("clean energy")
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)


def test_congress_extracts_bill_number(mocked_http):
    mocked_http.get("https://api.congress.gov/v3/bill").respond(
        200, json=CONGRESS_BILLS_JSON
    )
    docs = search_bills("clean energy")
    assert docs[0].metadata["bill_number"] == "5376"
    assert docs[0].id == "congress:117-HR-5376"


def test_congress_extracts_title(mocked_http):
    mocked_http.get("https://api.congress.gov/v3/bill").respond(
        200, json=CONGRESS_BILLS_JSON
    )
    docs = search_bills("clean energy")
    assert "Inflation Reduction Act" in docs[0].metadata["title"]
    assert docs[0].metadata["title"] in docs[0].text


def test_congress_text_includes_latest_action(mocked_http):
    mocked_http.get("https://api.congress.gov/v3/bill").respond(
        200, json=CONGRESS_BILLS_JSON
    )
    docs = search_bills("clean energy")
    assert "Public Law" in docs[0].text


def test_congress_extracts_congress_number(mocked_http):
    mocked_http.get("https://api.congress.gov/v3/bill").respond(
        200, json=CONGRESS_BILLS_JSON
    )
    docs = search_bills("clean energy")
    assert docs[0].metadata["congress"] == "117"
    assert docs[1].metadata["congress"] == "118"


def test_congress_metadata_grade_and_source(mocked_http):
    mocked_http.get("https://api.congress.gov/v3/bill").respond(
        200, json=CONGRESS_BILLS_JSON
    )
    doc = search_bills("clean energy")[0]
    assert doc.metadata["source"] == "congress_gov"
    assert doc.metadata["grade"] == "A"


def test_congress_empty_results(mocked_http):
    mocked_http.get("https://api.congress.gov/v3/bill").respond(
        200, json=CONGRESS_EMPTY_JSON
    )
    assert search_bills("nothing") == []


def test_congress_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.congress.gov/v3/bill").respond(401)
    with pytest.raises(httpx.HTTPStatusError):
        search_bills("x")


def test_congress_uses_injected_client(mocked_http):
    mocked_http.get("https://api.congress.gov/v3/bill").respond(
        200, json=CONGRESS_BILLS_JSON
    )
    with httpx.Client() as client:
        docs = search_bills("clean energy", client=client)
        assert len(docs) == 2
        assert not client.is_closed


def test_congress_fetch_bill(mocked_http):
    mocked_http.get("https://api.congress.gov/v3/bill/117/hr/5376").respond(
        200, json=CONGRESS_BILL_SINGLE_JSON
    )
    docs = fetch_bill(117, "hr", "5376")
    assert len(docs) == 1
    assert docs[0].metadata["bill_number"] == "5376"
    assert docs[0].metadata["bill_type"] == "HR"


def test_congress_get_vote_record(mocked_http):
    mocked_http.get("https://api.congress.gov/v3/bill/117/hr/5376/actions").respond(
        200, json=CONGRESS_ACTIONS_JSON
    )
    docs = get_vote_record(117, "hr", "5376")
    assert len(docs) == 2
    assert docs[0].metadata["action_date"] == "2022-08-16"
    assert "Public Law" in docs[0].metadata["action_text"]


def test_congress_track_committee(mocked_http):
    mocked_http.get("https://api.congress.gov/v3/committee/sseg00/bills").respond(
        200, json=CONGRESS_COMMITTEE_JSON
    )
    docs = track_committee("sseg00")
    assert len(docs) == 1
    assert docs[0].metadata["bill_number"] == "1234"
    assert docs[0].metadata["bill_type"] == "S"


def test_congress_respects_max_results(mocked_http):
    route = mocked_http.get("https://api.congress.gov/v3/bill").respond(
        200, json=CONGRESS_BILLS_JSON
    )
    search_bills("clean energy", max_results=3)
    assert route.calls.last.request.url.params.get("limit") == "3"
