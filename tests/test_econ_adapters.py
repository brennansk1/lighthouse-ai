"""Offline tests for SL8 economic-data source adapters.

Each adapter is exercised directly (not through a skill) using respx HTTP
mocking. No real network is touched. No datetime.now() at import.

Adapters tested:
  * fred — search_series, fetch_series, list_releases, get_revisions, compare_series
  * bea  — search_dataset, fetch_table, list_nipa_tables, get_industry_account
  * bls  — search_series (catalog), fetch_series, list_releases, compare_geographies, get_occupation_data
  * world_bank — search_indicator, fetch_indicator, list_indicators_by_topic, compare_countries, get_country_metadata
  * oecd — search_dataset (catalog), fetch_dataset, compare_countries, list_recent_releases
  * census — search_dataset, fetch_acs_table, fetch_decennial, query_geographic
"""

from __future__ import annotations

import httpx
import pytest
import respx

from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.sources.bea import (
    fetch_table as bea_fetch_table,
)
from lighthouse_ai.sources.bea import (
    get_industry_account as bea_industry,
)
from lighthouse_ai.sources.bea import (
    list_nipa_tables as bea_nipa_tables,
)
from lighthouse_ai.sources.bea import (
    search_dataset as bea_search,
)
from lighthouse_ai.sources.bls import (
    compare_geographies as bls_compare_geo,
)
from lighthouse_ai.sources.bls import (
    fetch_series as bls_fetch,
)
from lighthouse_ai.sources.bls import (
    get_occupation_data as bls_occupation,
)
from lighthouse_ai.sources.bls import (
    list_releases as bls_releases,
)
from lighthouse_ai.sources.bls import (
    search_series as bls_search,
)
from lighthouse_ai.sources.census import (
    fetch_acs_table as census_acs,
)
from lighthouse_ai.sources.census import (
    fetch_decennial as census_dec,
)
from lighthouse_ai.sources.census import (
    query_geographic as census_geo,
)
from lighthouse_ai.sources.census import (
    search_dataset as census_search,
)
from lighthouse_ai.sources.fred import (
    compare_series as fred_compare,
)
from lighthouse_ai.sources.fred import (
    fetch_series as fred_fetch,
)
from lighthouse_ai.sources.fred import (
    get_revisions as fred_revisions,
)
from lighthouse_ai.sources.fred import (
    list_releases as fred_releases,
)

# ---------------------------------------------------------------------------
# Import all six adapters
# ---------------------------------------------------------------------------
from lighthouse_ai.sources.fred import (
    search_series as fred_search,
)
from lighthouse_ai.sources.oecd import (
    compare_countries as oecd_compare,
)
from lighthouse_ai.sources.oecd import (
    fetch_dataset as oecd_fetch,
)
from lighthouse_ai.sources.oecd import (
    list_recent_releases as oecd_recent,
)
from lighthouse_ai.sources.oecd import (
    search_dataset as oecd_search,
)
from lighthouse_ai.sources.world_bank import (
    fetch_indicator as wb_fetch,
)
from lighthouse_ai.sources.world_bank import (
    get_country_metadata as wb_country_meta,
)
from lighthouse_ai.sources.world_bank import (
    list_indicators_by_topic as wb_list_topic,
)
from lighthouse_ai.sources.world_bank import (
    search_indicator as wb_search,
)


@pytest.fixture
def mocked_http():
    with respx.mock(assert_all_called=False) as m:
        yield m


# ===========================================================================
# FRED adapter tests
# ===========================================================================

FRED_SEARCH_JSON = {
    "seriess": [
        {
            "id": "UNRATE",
            "title": "Unemployment Rate",
            "frequency": "Monthly",
            "units": "Percent",
            "seasonal_adjustment": "Seasonally Adjusted",
            "observation_start": "1948-01-01",
            "observation_end": "2025-01-01",
            "notes": "The unemployment rate represents the number of unemployed as a percentage.",
        }
    ]
}

FRED_OBS_JSON = {
    "observations": [
        {"date": "2024-11-01", "value": "4.2"},
        {"date": "2024-12-01", "value": "4.1"},
    ]
}

FRED_RELEASES_JSON = {
    "releases": [
        {
            "id": 10,
            "name": "Employment Situation",
            "press_release": True,
            "link": "https://www.bls.gov/news.release/empsit.nr0.htm",
        },
        {"id": 11, "name": "GDP", "press_release": True, "link": ""},
    ]
}

FRED_VINTAGES_JSON = {"vintage_dates": ["2024-01-26", "2024-04-25", "2024-07-25", "2024-09-26"]}

FRED_SERIES_JSON = {
    "seriess": [
        {
            "id": "GDPC1",
            "title": "Real Gross Domestic Product",
            "units": "Billions of Chained 2017 Dollars",
            "frequency": "Quarterly",
            "observation_end": "2024-07-01",
        }
    ]
}


def test_fred_search_returns_documents(mocked_http):
    mocked_http.get("https://api.stlouisfed.org/fred/series/search").respond(
        200, json=FRED_SEARCH_JSON
    )
    docs = fred_search("unemployment")
    assert len(docs) == 1
    assert isinstance(docs[0], Document)


def test_fred_search_extracts_series_id(mocked_http):
    mocked_http.get("https://api.stlouisfed.org/fred/series/search").respond(
        200, json=FRED_SEARCH_JSON
    )
    doc = fred_search("unemployment")[0]
    assert doc.metadata["series_id"] == "UNRATE"
    assert doc.id == "fred:UNRATE"


def test_fred_search_metadata_grade(mocked_http):
    mocked_http.get("https://api.stlouisfed.org/fred/series/search").respond(
        200, json=FRED_SEARCH_JSON
    )
    doc = fred_search("unemployment")[0]
    assert doc.metadata["source"] == "fred"
    assert doc.metadata["grade"] == "A"


def test_fred_search_empty(mocked_http):
    mocked_http.get("https://api.stlouisfed.org/fred/series/search").respond(
        200, json={"seriess": []}
    )
    assert fred_search("zzznomatch") == []


def test_fred_search_respects_max_results(mocked_http):
    route = mocked_http.get("https://api.stlouisfed.org/fred/series/search").respond(
        200, json=FRED_SEARCH_JSON
    )
    fred_search("unemployment", max_results=3)
    assert route.calls.last.request.url.params["limit"] == "3"


def test_fred_search_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.stlouisfed.org/fred/series/search").respond(400)
    with pytest.raises(httpx.HTTPStatusError):
        fred_search("x")


def test_fred_fetch_returns_document(mocked_http):
    mocked_http.get("https://api.stlouisfed.org/fred/series/observations").respond(
        200, json=FRED_OBS_JSON
    )
    docs = fred_fetch("UNRATE")
    assert len(docs) == 1
    assert "2024-12-01: 4.1" in docs[0].text


def test_fred_fetch_empty_observations(mocked_http):
    mocked_http.get("https://api.stlouisfed.org/fred/series/observations").respond(
        200, json={"observations": []}
    )
    assert fred_fetch("UNRATE") == []


def test_fred_releases_returns_documents(mocked_http):
    mocked_http.get("https://api.stlouisfed.org/fred/releases").respond(
        200, json=FRED_RELEASES_JSON
    )
    docs = fred_releases()
    assert len(docs) == 2
    assert docs[0].metadata["release_id"] == "10"
    assert "Employment Situation" in docs[0].text


def test_fred_revisions_returns_document(mocked_http):
    mocked_http.get("https://api.stlouisfed.org/fred/series/vintagedates").respond(
        200, json=FRED_VINTAGES_JSON
    )
    docs = fred_revisions("GDP")
    assert len(docs) == 1
    assert docs[0].metadata["vintage_count"] == 4
    assert docs[0].metadata["latest_vintage"] == "2024-09-26"


def test_fred_compare_series_returns_documents(mocked_http):
    mocked_http.get("https://api.stlouisfed.org/fred/series").respond(200, json=FRED_SERIES_JSON)
    docs = fred_compare(["GDPC1"])
    assert len(docs) == 1
    assert docs[0].metadata["series_id"] == "GDPC1"


def test_fred_uses_injected_client(mocked_http):
    mocked_http.get("https://api.stlouisfed.org/fred/series/search").respond(
        200, json=FRED_SEARCH_JSON
    )
    with httpx.Client() as client:
        docs = fred_search("unemployment", client=client)
        assert len(docs) == 1
        assert not client.is_closed


# ===========================================================================
# BEA adapter tests
# ===========================================================================

BEA_DATASET_JSON = {
    "BEAAPI": {
        "Results": {
            "Dataset": [
                {
                    "DatasetName": "NIPA",
                    "DatasetDescription": "National Income and Product Accounts",
                },
                {"DatasetName": "Regional", "DatasetDescription": "Regional Economic Accounts"},
                {"DatasetName": "GDPbyIndustry", "DatasetDescription": "GDP by Industry"},
            ]
        }
    }
}

BEA_NIPA_DATA_JSON = {
    "BEAAPI": {
        "Results": {
            "Data": [
                {
                    "LineDescription": "Gross domestic product",
                    "TimePeriod": "2024Q1",
                    "DataValue": "2.5",
                },
                {
                    "LineDescription": "Gross domestic product",
                    "TimePeriod": "2024Q2",
                    "DataValue": "3.0",
                },
            ]
        }
    }
}

BEA_PARAM_JSON = {
    "BEAAPI": {
        "Results": {
            "ParamValue": [
                {"TableName": "T10101", "Desc": "Percent Change From Preceding Period in Real GDP"},
                {"TableName": "T10102", "Desc": "Contributions to Percent Change in Real GDP"},
            ]
        }
    }
}

BEA_INDUSTRY_JSON = {
    "BEAAPI": {
        "Results": {
            "Data": [
                {
                    "IndustryDescription": "Manufacturing",
                    "Year": "2023",
                    "DataValue": "2154.2",
                }
            ]
        }
    }
}


def test_bea_search_returns_documents(mocked_http):
    mocked_http.get("https://apps.bea.gov/api/data").respond(200, json=BEA_DATASET_JSON)
    docs = bea_search("national accounts")
    assert len(docs) >= 1
    assert isinstance(docs[0], Document)


def test_bea_search_filters_by_query(mocked_http):
    mocked_http.get("https://apps.bea.gov/api/data").respond(200, json=BEA_DATASET_JSON)
    docs = bea_search("GDP industry")
    names = [d.metadata["dataset_name"] for d in docs]
    assert "GDPbyIndustry" in names or "NIPA" in names


def test_bea_search_metadata_grade(mocked_http):
    mocked_http.get("https://apps.bea.gov/api/data").respond(200, json=BEA_DATASET_JSON)
    docs = bea_search("national")
    assert docs[0].metadata["source"] == "bea"
    assert docs[0].metadata["grade"] == "A"


def test_bea_fetch_table_returns_documents(mocked_http):
    mocked_http.get("https://apps.bea.gov/api/data").respond(200, json=BEA_NIPA_DATA_JSON)
    docs = bea_fetch_table("T10101")
    assert len(docs) >= 1
    assert "Gross domestic product" in docs[0].metadata["line_description"]


def test_bea_list_nipa_tables(mocked_http):
    mocked_http.get("https://apps.bea.gov/api/data").respond(200, json=BEA_PARAM_JSON)
    docs = bea_nipa_tables()
    assert len(docs) >= 1
    assert docs[0].metadata["table_name"] == "T10101"


def test_bea_get_industry_account(mocked_http):
    mocked_http.get("https://apps.bea.gov/api/data").respond(200, json=BEA_INDUSTRY_JSON)
    docs = bea_industry("ALL")
    assert len(docs) >= 1
    assert "Manufacturing" in docs[0].text


def test_bea_raises_on_http_error(mocked_http):
    mocked_http.get("https://apps.bea.gov/api/data").respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        bea_search("x")


def test_bea_uses_injected_client(mocked_http):
    mocked_http.get("https://apps.bea.gov/api/data").respond(200, json=BEA_DATASET_JSON)
    with httpx.Client() as client:
        docs = bea_search("gdp", client=client)
        assert isinstance(docs, list)
        assert not client.is_closed


# ===========================================================================
# BLS adapter tests
# ===========================================================================

BLS_SERIES_JSON = {
    "status": "REQUEST_SUCCEEDED",
    "Results": {
        "series": [
            {
                "seriesID": "LNS14000000",
                "catalog": {"series_title": "Unemployment Rate"},
                "data": [
                    {"year": "2024", "period": "M12", "value": "4.1", "footnotes": []},
                    {"year": "2024", "period": "M11", "value": "4.2", "footnotes": []},
                ],
            }
        ]
    },
}

BLS_SURVEYS_JSON = {
    "status": "REQUEST_SUCCEEDED",
    "Results": {
        "survey": [
            {"survey_abbreviation": "CES", "survey_name": "Current Employment Statistics"},
            {"survey_abbreviation": "CPI", "survey_name": "Consumer Price Index"},
        ]
    },
}


def test_bls_search_catalog_returns_documents():
    """BLS search_series uses a local catalog, no network needed."""
    docs = bls_search("unemployment rate")
    assert len(docs) >= 1
    assert any(d.metadata["series_id"] == "LNS14000000" for d in docs)


def test_bls_search_catalog_empty_query():
    docs = bls_search("zzznomatch")
    assert docs == []


def test_bls_search_catalog_max_results():
    docs = bls_search("employment", max_results=2)
    assert len(docs) <= 2


def test_bls_fetch_returns_document(mocked_http):
    mocked_http.post("https://api.bls.gov/publicAPI/v2/timeseries/data/").respond(
        200, json=BLS_SERIES_JSON
    )
    docs = bls_fetch(["LNS14000000"])
    assert len(docs) == 1
    assert docs[0].metadata["series_id"] == "LNS14000000"
    assert docs[0].metadata["source"] == "bls"


def test_bls_fetch_metadata_grade(mocked_http):
    mocked_http.post("https://api.bls.gov/publicAPI/v2/timeseries/data/").respond(
        200, json=BLS_SERIES_JSON
    )
    doc = bls_fetch(["LNS14000000"])[0]
    assert doc.metadata["grade"] == "A"
    assert "LNS14000000" in doc.id


def test_bls_fetch_empty_data(mocked_http):
    mocked_http.post("https://api.bls.gov/publicAPI/v2/timeseries/data/").respond(
        200, json={"status": "REQUEST_SUCCEEDED", "Results": {"series": []}}
    )
    assert bls_fetch(["UNKNOWN"]) == []


def test_bls_list_releases(mocked_http):
    mocked_http.get("https://api.bls.gov/publicAPI/v2/surveys").respond(200, json=BLS_SURVEYS_JSON)
    docs = bls_releases()
    assert len(docs) == 2
    assert docs[0].metadata["survey_abbreviation"] == "CES"


def test_bls_compare_geographies_delegates_to_fetch(mocked_http):
    mocked_http.post("https://api.bls.gov/publicAPI/v2/timeseries/data/").respond(
        200, json=BLS_SERIES_JSON
    )
    docs = bls_compare_geo(["LNS14000000"])
    assert len(docs) == 1


def test_bls_occupation_data_catalog():
    """BLS occupation data uses a local catalog."""
    docs = bls_occupation("software developer")
    assert len(docs) >= 1
    assert any("Software" in d.metadata["title"] for d in docs)


def test_bls_fetch_raises_on_http_error(mocked_http):
    mocked_http.post("https://api.bls.gov/publicAPI/v2/timeseries/data/").respond(503)
    with pytest.raises(httpx.HTTPStatusError):
        bls_fetch(["LNS14000000"])


def test_bls_fetch_uses_injected_client(mocked_http):
    mocked_http.post("https://api.bls.gov/publicAPI/v2/timeseries/data/").respond(
        200, json=BLS_SERIES_JSON
    )
    with httpx.Client() as client:
        docs = bls_fetch(["LNS14000000"], client=client)
        assert len(docs) == 1
        assert not client.is_closed


# ===========================================================================
# World Bank adapter tests
# ===========================================================================

WB_INDICATOR_JSON = [
    {"page": 1, "pages": 1, "per_page": 100, "total": 2},
    [
        {
            "id": "NY.GDP.MKTP.CD",
            "name": "GDP (current US$)",
            "sourceNote": "GDP at purchaser's prices is the sum of gross value added.",
        },
        {
            "id": "NY.GDP.PCAP.CD",
            "name": "GDP per capita (current US$)",
            "sourceNote": "GDP per capita is gross domestic product divided by midyear population.",
        },
    ],
]

WB_DATA_JSON = [
    {"page": 1, "pages": 1, "per_page": 50, "total": 3},
    [
        {
            "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
            "country": {"id": "US", "value": "United States"},
            "countryiso3code": "USA",
            "date": "2023",
            "value": 27360989000000,
        },
        {
            "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
            "country": {"id": "US", "value": "United States"},
            "countryiso3code": "USA",
            "date": "2022",
            "value": 25744100000000,
        },
    ],
]

WB_COUNTRY_JSON = [
    {"page": 1, "pages": 1, "per_page": 50, "total": 1},
    [
        {
            "id": "USA",
            "iso2Code": "US",
            "name": "United States",
            "region": {"id": "NAC", "value": "North America"},
            "incomeLevel": {"id": "HIC", "value": "High income"},
            "capitalCity": "Washington D.C.",
        }
    ],
]


def test_wb_search_returns_documents(mocked_http):
    mocked_http.get("https://api.worldbank.org/v2/indicator").respond(200, json=WB_INDICATOR_JSON)
    docs = wb_search("GDP")
    assert len(docs) >= 1
    assert isinstance(docs[0], Document)


def test_wb_search_extracts_indicator_id(mocked_http):
    mocked_http.get("https://api.worldbank.org/v2/indicator").respond(200, json=WB_INDICATOR_JSON)
    docs = wb_search("GDP")
    ids = [d.metadata["indicator_id"] for d in docs]
    assert "NY.GDP.MKTP.CD" in ids


def test_wb_search_metadata_grade(mocked_http):
    mocked_http.get("https://api.worldbank.org/v2/indicator").respond(200, json=WB_INDICATOR_JSON)
    doc = wb_search("GDP")[0]
    assert doc.metadata["source"] == "world_bank"
    assert doc.metadata["grade"] == "A"


def test_wb_search_empty(mocked_http):
    mocked_http.get("https://api.worldbank.org/v2/indicator").respond(
        200, json=[{"page": 1, "pages": 1, "per_page": 100, "total": 0}, []]
    )
    assert wb_search("zzznomatch") == []


def test_wb_fetch_indicator_returns_document(mocked_http):
    mocked_http.get("https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.CD").respond(
        200, json=WB_DATA_JSON
    )
    docs = wb_fetch("NY.GDP.MKTP.CD", "USA")
    assert len(docs) == 1
    assert docs[0].metadata["country_code"] == "USA"
    assert "United States" in docs[0].text


def test_wb_fetch_empty_data(mocked_http):
    mocked_http.get("https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.CD").respond(
        200, json=[{"page": 1, "pages": 1, "per_page": 50, "total": 0}, []]
    )
    assert wb_fetch("NY.GDP.MKTP.CD", "USA") == []


def test_wb_list_topic_returns_documents(mocked_http):
    mocked_http.get("https://api.worldbank.org/v2/topic/3/indicator").respond(
        200, json=WB_INDICATOR_JSON
    )
    docs = wb_list_topic(3)
    assert len(docs) >= 1


def test_wb_country_metadata(mocked_http):
    mocked_http.get("https://api.worldbank.org/v2/country/USA").respond(200, json=WB_COUNTRY_JSON)
    docs = wb_country_meta("USA")
    assert len(docs) == 1
    assert docs[0].metadata["country_code"] == "USA"
    assert "High income" in docs[0].text


def test_wb_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.worldbank.org/v2/indicator").respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        wb_search("gdp")


def test_wb_uses_injected_client(mocked_http):
    mocked_http.get("https://api.worldbank.org/v2/indicator").respond(200, json=WB_INDICATOR_JSON)
    with httpx.Client() as client:
        docs = wb_search("gdp", client=client)
        assert isinstance(docs, list)
        assert not client.is_closed


# ===========================================================================
# OECD adapter tests
# ===========================================================================

OECD_SDMX_JSON = {
    "data": {
        "dataSets": [
            {
                "series": {
                    "0:0:0": {
                        "observations": {
                            "0": [2.5, 0],
                            "1": [3.1, 0],
                        }
                    }
                }
            }
        ],
        "structure": {
            "dimensions": {
                "series": [
                    {
                        "id": "REF_AREA",
                        "values": [{"name": "United States"}],
                    },
                    {
                        "id": "MEASURE",
                        "values": [{"name": "GDP growth rate"}],
                    },
                    {
                        "id": "UNIT_MEASURE",
                        "values": [{"name": "Percent"}],
                    },
                ],
                "observation": [
                    {
                        "id": "TIME_PERIOD",
                        "values": [{"id": "2022"}, {"id": "2023"}],
                    }
                ],
            }
        },
    }
}


def test_oecd_search_catalog_returns_documents():
    """OECD search uses a local catalog — no network needed."""
    docs = oecd_search("labour productivity")
    assert len(docs) >= 1
    assert isinstance(docs[0], Document)


def test_oecd_search_catalog_metadata_grade():
    docs = oecd_search("GDP")
    assert docs[0].metadata["source"] == "oecd"
    assert docs[0].metadata["grade"] == "A"


def test_oecd_search_catalog_no_match():
    docs = oecd_search("zzznomatch_xyz_abc")
    assert docs == []


def test_oecd_search_catalog_empty_query():
    """Empty query returns all catalog entries."""
    docs = oecd_search("")
    assert len(docs) >= 5


def test_oecd_fetch_dataset(mocked_http):
    dataset_id = "OECD.SDD.NAD,DSD_NAMAIN1@DF_TABLE1_EXPENDITURE,1.0"
    mocked_http.get(f"https://sdmx.oecd.org/public/rest/data/{dataset_id}/all").respond(
        200, json=OECD_SDMX_JSON
    )
    docs = oecd_fetch(dataset_id)
    assert len(docs) >= 1
    assert docs[0].metadata["source"] == "oecd"


def test_oecd_fetch_multidim_observation_keys(mocked_http):
    """SDMX observation keys can be multi-dimensional ('0:0') — must not crash."""
    dataset_id = "OECD.SDD.NAD,DSD_NAMAIN1@DF_TABLE1_EXPENDITURE,1.0"
    multidim_json = {
        "data": {
            "dataSets": [
                {
                    "series": {
                        "0:0": {
                            "observations": {
                                "0:0": [2.5, 0],
                                "1:0": [3.1, 0],
                            }
                        }
                    }
                }
            ],
            "structure": {
                "dimensions": {
                    "series": [
                        {"id": "REF_AREA", "values": [{"name": "United States"}]},
                        {"id": "MEASURE", "values": [{"name": "GDP"}]},
                    ],
                    "observation": [
                        {
                            "id": "TIME_PERIOD",
                            "values": [{"id": "2022"}, {"id": "2023"}],
                        }
                    ],
                }
            },
        }
    }
    mocked_http.get(f"https://sdmx.oecd.org/public/rest/data/{dataset_id}/all").respond(
        200, json=multidim_json
    )
    docs = oecd_fetch(dataset_id)
    assert len(docs) >= 1
    # The first numeric component indexes the time dimension labels.
    assert "2022" in docs[0].text
    assert "2023" in docs[0].text


def test_oecd_fetch_raises_on_http_error(mocked_http):
    dataset_id = "OECD.SDD.NAD,DSD_NAMAIN1@DF_TABLE1_EXPENDITURE,1.0"
    mocked_http.get(f"https://sdmx.oecd.org/public/rest/data/{dataset_id}/all").respond(404)
    with pytest.raises(httpx.HTTPStatusError):
        oecd_fetch(dataset_id)


def test_oecd_compare_countries(mocked_http):
    dataset_id = "OECD.SDD.NAD,DSD_NAMAIN1@DF_TABLE1_EXPENDITURE,1.0"
    mocked_http.get(f"https://sdmx.oecd.org/public/rest/data/{dataset_id}/USA+DEU..").respond(
        200, json=OECD_SDMX_JSON
    )
    docs = oecd_compare(dataset_id, ["USA", "DEU"])
    assert isinstance(docs, list)


def test_oecd_list_recent_releases():
    """list_recent_releases uses local catalog — no network."""
    docs = oecd_recent(max_results=3)
    assert len(docs) == 3
    assert all(d.metadata["source"] == "oecd" for d in docs)


def test_oecd_fetch_uses_injected_client(mocked_http):
    dataset_id = "OECD.SDD.NAD,DSD_NAMAIN1@DF_TABLE1_EXPENDITURE,1.0"
    mocked_http.get(f"https://sdmx.oecd.org/public/rest/data/{dataset_id}/all").respond(
        200, json=OECD_SDMX_JSON
    )
    with httpx.Client() as client:
        docs = oecd_fetch(dataset_id, client=client)
        assert isinstance(docs, list)
        assert not client.is_closed


# ===========================================================================
# Census adapter tests
# ===========================================================================

CENSUS_DATASETS_JSON = {
    "dataset": [
        {
            "title": "American Community Survey 5-Year Data",
            "description": "ACS 5-year estimates for all geographies",
            "c_vintage": 2022,
            "c_dataset": ["acs", "acs5"],
            "distribution": [{"accessURL": "https://api.census.gov/data/2022/acs/acs5"}],
        },
        {
            "title": "Decennial Census 2020",
            "description": "2020 Census redistricting data",
            "c_vintage": 2020,
            "c_dataset": ["dec", "dhc"],
            "distribution": [{"accessURL": "https://api.census.gov/data/2020/dec/dhc"}],
        },
    ]
}

CENSUS_ACS_JSON = [
    ["NAME", "B01003_001E", "B19013_001E", "state"],
    ["California", "39538223", "84097", "06"],
    ["New York", "20201249", "72108", "36"],
]

CENSUS_DEC_JSON = [
    ["NAME", "P1_001N", "state"],
    ["Texas", "29145505", "48"],
]


def test_census_search_returns_documents(mocked_http):
    mocked_http.get("https://api.census.gov/data.json").respond(200, json=CENSUS_DATASETS_JSON)
    docs = census_search("American Community Survey")
    assert len(docs) >= 1
    assert isinstance(docs[0], Document)


def test_census_search_filters_by_query(mocked_http):
    mocked_http.get("https://api.census.gov/data.json").respond(200, json=CENSUS_DATASETS_JSON)
    docs = census_search("decennial 2020")
    titles = [d.metadata["title"] for d in docs]
    assert any("Decennial" in t or "decennial" in t.lower() for t in titles)


def test_census_search_metadata_grade(mocked_http):
    mocked_http.get("https://api.census.gov/data.json").respond(200, json=CENSUS_DATASETS_JSON)
    docs = census_search("census")
    assert docs[0].metadata["source"] == "census"
    assert docs[0].metadata["grade"] == "A"


def test_census_fetch_acs_returns_documents(mocked_http):
    mocked_http.get("https://api.census.gov/data/2022/acs/acs5").respond(200, json=CENSUS_ACS_JSON)
    docs = census_acs(["B01003_001E", "B19013_001E"], year=2022, geography="state")
    assert len(docs) == 2
    assert any("California" in d.metadata["geo_label"] for d in docs)


def test_census_fetch_acs_metadata(mocked_http):
    mocked_http.get("https://api.census.gov/data/2022/acs/acs5").respond(200, json=CENSUS_ACS_JSON)
    docs = census_acs(["B01003_001E"], year=2022, geography="state")
    doc = docs[0]
    assert doc.metadata["source"] == "census"
    assert doc.metadata["grade"] == "A"
    assert doc.metadata["geography"] == "state"


def test_census_fetch_decennial(mocked_http):
    mocked_http.get("https://api.census.gov/data/2020/dec/dhc").respond(200, json=CENSUS_DEC_JSON)
    docs = census_dec(["P1_001N"], year=2020, geography="state")
    assert len(docs) == 1
    assert "Texas" in docs[0].metadata["geo_label"]


def test_census_query_geographic_catalog():
    """Geographic lookup uses a local catalog."""
    docs = census_geo("California")
    assert len(docs) >= 1
    assert any(d.metadata["state_name"] == "California" for d in docs)


def test_census_query_geographic_empty_query():
    """Empty query returns all catalog entries."""
    docs = census_geo("")
    assert len(docs) >= 5


def test_census_query_geographic_no_match():
    docs = census_geo("zzznomatch")
    assert docs == []


def test_census_search_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.census.gov/data.json").respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        census_search("acs")


def test_census_acs_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.census.gov/data/2022/acs/acs5").respond(400)
    with pytest.raises(httpx.HTTPStatusError):
        census_acs(["B01003_001E"])


def test_census_uses_injected_client(mocked_http):
    mocked_http.get("https://api.census.gov/data.json").respond(200, json=CENSUS_DATASETS_JSON)
    with httpx.Client() as client:
        docs = census_search("acs", client=client)
        assert isinstance(docs, list)
        assert not client.is_closed
