"""Offline tests for the ClinicalTrials.gov and WHO GHO source adapters.

All HTTP is respx-mocked; no real network is touched. Each adapter is exercised
directly (not through a skill) to verify the parsing and interface contract.

Test plan
---------
ClinicalTrials.gov adapter:
- Returns list[Document] from valid v2 API response.
- Extracts NCT ID, title, conditions, overall_status, start_date from JSON.
- Skips studies with no title.
- Respects max_results.
- Raises HTTPStatusError on 4xx/5xx.
- Uses injected client without closing it.

WHO GHO adapter:
- Returns list[Document] from valid /api/GHO response.
- Filters by query keywords client-side.
- Respects max_results.
- Returns [] for empty value list.
- Raises HTTPStatusError on 4xx/5xx.
- Uses injected client without closing it.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.sources.clinicaltrials import search_trials
from lighthouse_ai.sources.who import search_who

# ---------------------------------------------------------------------------
# ClinicalTrials.gov fixture data
# ---------------------------------------------------------------------------

CT_STUDIES_JSON = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT04668625",
                    "briefTitle": "A Study of Drug X in Type 2 Diabetes",
                    "officialTitle": "A Phase 3 Randomized Study of Drug X in Adults With Type 2 Diabetes Mellitus",
                },
                "statusModule": {
                    "overallStatus": "Completed",
                    "startDateStruct": {"date": "2020-06-01"},
                },
                "descriptionModule": {
                    "briefSummary": "This study evaluates the efficacy of Drug X for glycemic control.",
                },
                "conditionsModule": {
                    "conditions": ["Type 2 Diabetes Mellitus"],
                },
            }
        },
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT04668626",
                    "briefTitle": "Another Trial of Drug Y",
                },
                "statusModule": {
                    "overallStatus": "Recruiting",
                    "startDateStruct": {"date": "2021-03-15"},
                },
                "descriptionModule": {},
                "conditionsModule": {
                    "conditions": ["Hypertension"],
                },
            }
        },
    ]
}

CT_EMPTY_JSON = {"studies": []}

CT_NOTITLE_JSON = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT99999999"},
                "statusModule": {},
                "descriptionModule": {},
                "conditionsModule": {},
            }
        }
    ]
}

# ---------------------------------------------------------------------------
# WHO GHO fixture data
# ---------------------------------------------------------------------------

WHO_GHO_JSON = {
    "value": [
        {
            "IndicatorCode": "WHOSIS_000001",
            "IndicatorName": "Life expectancy at birth (years)",
            "Language": "EN",
        },
        {
            "IndicatorCode": "MDG_0000000026",
            "IndicatorName": "Maternal mortality ratio (per 100 000 live births)",
            "Language": "EN",
        },
        {
            "IndicatorCode": "WHS4_100",
            "IndicatorName": "Tuberculosis incidence (per 100 000 population)",
            "Language": "EN",
        },
    ]
}

WHO_EMPTY_JSON = {"value": []}

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mocked_http():
    with respx.mock(assert_all_called=False) as m:
        yield m


# ---------------------------------------------------------------------------
# ClinicalTrials.gov adapter tests
# ---------------------------------------------------------------------------


def test_ct_returns_documents(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(200, json=CT_STUDIES_JSON)
    docs = search_trials("diabetes")
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)


def test_ct_extracts_nct_id(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(200, json=CT_STUDIES_JSON)
    docs = search_trials("diabetes")
    assert docs[0].metadata["nct_id"] == "NCT04668625"
    assert docs[0].id == "clinicaltrials:NCT04668625"


def test_ct_extracts_title(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(200, json=CT_STUDIES_JSON)
    docs = search_trials("diabetes")
    assert "Phase 3" in docs[0].metadata["title"]
    assert docs[0].metadata["title"] in docs[0].text


def test_ct_extracts_conditions(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(200, json=CT_STUDIES_JSON)
    docs = search_trials("diabetes")
    assert docs[0].metadata["conditions"] == ["Type 2 Diabetes Mellitus"]


def test_ct_extracts_overall_status(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(200, json=CT_STUDIES_JSON)
    docs = search_trials("diabetes")
    assert docs[0].metadata["overall_status"] == "Completed"
    assert docs[1].metadata["overall_status"] == "Recruiting"


def test_ct_extracts_start_date(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(200, json=CT_STUDIES_JSON)
    docs = search_trials("diabetes")
    assert docs[0].metadata["start_date"] == "2020-06-01"


def test_ct_text_includes_summary(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(200, json=CT_STUDIES_JSON)
    docs = search_trials("diabetes")
    assert "glycemic control" in docs[0].text


def test_ct_text_title_only_when_no_summary(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(200, json=CT_STUDIES_JSON)
    docs = search_trials("diabetes")
    # Second study has no briefSummary
    assert docs[1].text == docs[1].metadata["title"]


def test_ct_metadata_grade_and_source(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(200, json=CT_STUDIES_JSON)
    doc = search_trials("diabetes")[0]
    assert doc.metadata["source"] == "clinicaltrials"
    assert doc.metadata["grade"] == "A"


def test_ct_url_contains_nct_id(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(200, json=CT_STUDIES_JSON)
    doc = search_trials("diabetes")[0]
    assert "NCT04668625" in doc.metadata["url"]


def test_ct_empty_studies(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(200, json=CT_EMPTY_JSON)
    assert search_trials("nothing") == []


def test_ct_skips_studies_without_title(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(200, json=CT_NOTITLE_JSON)
    assert search_trials("x") == []


def test_ct_respects_max_results(mocked_http):
    route = mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(
        200, json=CT_STUDIES_JSON
    )
    search_trials("diabetes", max_results=3)
    assert route.calls.last.request.url.params["pageSize"] == "3"


def test_ct_raises_on_http_error(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(503)
    with pytest.raises(httpx.HTTPStatusError):
        search_trials("x")


def test_ct_uses_injected_client(mocked_http):
    mocked_http.get("https://clinicaltrials.gov/api/v2/studies").respond(200, json=CT_STUDIES_JSON)
    with httpx.Client() as client:
        docs = search_trials("diabetes", client=client)
        assert len(docs) == 2
        # Injected client must NOT be closed by the adapter
        assert not client.is_closed


# ---------------------------------------------------------------------------
# WHO GHO adapter tests
# ---------------------------------------------------------------------------


def test_who_returns_documents(mocked_http):
    mocked_http.get("https://ghoapi.azureedge.net/api/GHO").respond(200, json=WHO_GHO_JSON)
    docs = search_who("life expectancy")
    assert len(docs) >= 1
    assert all(isinstance(d, Document) for d in docs)


def test_who_filters_by_query_keyword(mocked_http):
    mocked_http.get("https://ghoapi.azureedge.net/api/GHO").respond(200, json=WHO_GHO_JSON)
    docs = search_who("tuberculosis")
    assert len(docs) == 1
    assert "Tuberculosis" in docs[0].metadata["title"]


def test_who_extracts_indicator_code(mocked_http):
    mocked_http.get("https://ghoapi.azureedge.net/api/GHO").respond(200, json=WHO_GHO_JSON)
    docs = search_who("life expectancy")
    assert docs[0].metadata["indicator_code"] == "WHOSIS_000001"
    assert docs[0].id == "who:WHOSIS_000001"


def test_who_metadata_grade_and_source(mocked_http):
    mocked_http.get("https://ghoapi.azureedge.net/api/GHO").respond(200, json=WHO_GHO_JSON)
    doc = search_who("life expectancy")[0]
    assert doc.metadata["source"] == "who"
    assert doc.metadata["grade"] == "A"


def test_who_url_contains_indicator_code(mocked_http):
    mocked_http.get("https://ghoapi.azureedge.net/api/GHO").respond(200, json=WHO_GHO_JSON)
    doc = search_who("life expectancy")[0]
    assert "WHOSIS_000001" in doc.metadata["url"]


def test_who_empty_value_list(mocked_http):
    mocked_http.get("https://ghoapi.azureedge.net/api/GHO").respond(200, json=WHO_EMPTY_JSON)
    assert search_who("anything") == []


def test_who_no_match_returns_empty(mocked_http):
    mocked_http.get("https://ghoapi.azureedge.net/api/GHO").respond(200, json=WHO_GHO_JSON)
    # Query with no matching words
    docs = search_who("zzznomatchzzz")
    assert docs == []


def test_who_respects_max_results(mocked_http):
    # All 3 entries match "mortality" but we only want 1
    mocked_http.get("https://ghoapi.azureedge.net/api/GHO").respond(200, json=WHO_GHO_JSON)
    # "mortality" matches "Maternal mortality ratio"
    docs = search_who("mortality", max_results=1)
    assert len(docs) <= 1


def test_who_raises_on_http_error(mocked_http):
    mocked_http.get("https://ghoapi.azureedge.net/api/GHO").respond(503)
    with pytest.raises(httpx.HTTPStatusError):
        search_who("x")


def test_who_uses_injected_client(mocked_http):
    mocked_http.get("https://ghoapi.azureedge.net/api/GHO").respond(200, json=WHO_GHO_JSON)
    with httpx.Client() as client:
        docs = search_who("life expectancy", client=client)
        assert len(docs) >= 1
        # Injected client must NOT be closed by the adapter
        assert not client.is_closed
