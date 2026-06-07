"""BLS (Bureau of Labor Statistics) source adapter — BLS Public Data API v2.

The U.S. Bureau of Labor Statistics provides data on employment, unemployment,
prices (CPI/PPI), productivity, wages, and occupational statistics.
The API base URL is ``https://api.bls.gov/publicAPI/v2``.

Key endpoints used here:
  * ``/timeseries/data/`` — fetch time-series observations (POST, up to 50 series)
  * ``/surveys`` — list available surveys (CES, CPI, etc.)

Series ID conventions (common examples):
  * CES0000000001 — Total nonfarm employment
  * LNS14000000 — Unemployment rate (seasonally adjusted)
  * CUUR0000SA0 — CPI-U All items (not seasonally adjusted)
  * PRS85006092 — Nonfarm business labor productivity

**Auth:** An API key increases the quota to 500 requests/day (10 without a key).
Register at https://data.bls.gov/registrationEngine/. Pass via ``api_key``
parameter or the ``BLS_API_KEY`` environment variable.

**Egress note:** ``api.bls.gov`` must be on the Lighthouse platform allowlist.
Run ``lighthouse trust add api.bls.gov`` to enable live fetches.

The adapter is httpx-based and client-injectable for respx testability.
"""

from __future__ import annotations

import os

import httpx

from ..net import guarded_get, guarded_request
from ..rag.chunker import Document

_BASE = "https://api.bls.gov/publicAPI/v2"
_ALLOWED_HOSTS = frozenset({"api.bls.gov"})
_HEADERS = {
    "User-Agent": "Lighthouse/0.1",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _api_key(api_key: str | None) -> str:
    """Resolve API key from argument or environment variable."""
    return api_key or os.environ.get("BLS_API_KEY", "")


def _parse_series_data(result: dict) -> list[Document]:
    """Parse BLS timeseries results array into Documents."""
    series_list = result.get("Results", {}).get("series") or []
    out: list[Document] = []
    for s in series_list:
        series_id = (s.get("seriesID") or "").strip()
        data_points = s.get("data") or []
        if not data_points:
            continue
        # Build concise text: last 10 data points
        recent = data_points[:10]
        obs_text = "; ".join(
            f"{d.get('year', '')}-{d.get('period', '')}: {d.get('value', '')}"
            for d in recent
        )
        catalog = s.get("catalog") or {}
        series_title = (catalog.get("series_title") or series_id).strip()
        text = f"BLS {series_title}: {obs_text}"
        url = f"https://data.bls.gov/timeseries/{series_id}"
        out.append(Document(
            id=f"bls:{series_id}",
            text=text,
            metadata={
                "source": "bls",
                "url": url,
                "grade": "A",
                "title": series_title,
                "series_id": series_id,
                "latest_value": data_points[0].get("value", "") if data_points else "",
                "latest_period": f"{data_points[0].get('year', '')}-{data_points[0].get('period', '')}" if data_points else "",
            },
        ))
    return out


def search_series(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Search for well-known BLS series matching ``query`` by returning a curated lookup.

    BLS does not have a free-text series search endpoint; this function maps
    common query terms (employment, unemployment, CPI, PPI, productivity,
    wages) to canonical series IDs and returns matching Document stubs. Use
    ``fetch_series`` to retrieve actual observations.

    Returns up to ``max_results`` Documents. Never raises on empty match.
    """
    # Curated series catalog — maps keyword → (series_id, title, survey)
    _CATALOG = [
        ("LNS14000000", "Unemployment Rate (seasonally adjusted)", "bls:unemployment"),
        ("CES0000000001", "Total Nonfarm Payroll Employment", "bls:employment"),
        ("CUUR0000SA0", "CPI-U All Items (not seasonally adjusted)", "bls:cpi"),
        ("CUUR0000SA0L1E", "CPI-U All Items Less Food and Energy", "bls:cpi"),
        ("WPU00000000", "Producer Price Index — All Commodities", "bls:ppi"),
        ("PRS85006092", "Nonfarm Business Labor Productivity", "bls:productivity"),
        ("CES0500000003", "Average Hourly Earnings — Private", "bls:wages"),
        ("LNS12000000", "Civilian Employment Level", "bls:employment"),
        ("LNS11000000", "Civilian Labor Force", "bls:labor_force"),
        ("LNS13000000", "Number of Unemployed Persons", "bls:unemployment"),
    ]
    q = query.lower()
    out: list[Document] = []
    for series_id, title, tag in _CATALOG:
        if any(w in title.lower() or w in tag for w in q.split()):
            url = f"https://data.bls.gov/timeseries/{series_id}"
            out.append(Document(
                id=f"bls:{series_id}",
                text=f"BLS series: {title} ({series_id})",
                metadata={
                    "source": "bls",
                    "url": url,
                    "grade": "A",
                    "title": title,
                    "series_id": series_id,
                },
            ))
        if len(out) >= max_results:
            break
    return out


def fetch_series(
    series_ids: list[str],
    *,
    start_year: str = "2020",
    end_year: str = "2025",
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch time-series observations for one or more BLS series IDs (POST).

    Returns one Document per series with recent observations. Raises
    ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    key = _api_key(api_key)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        payload: dict = {
            "seriesid": series_ids[:max_results],
            "startyear": start_year,
            "endyear": end_year,
            "catalog": True,
        }
        if key:
            payload["registrationkey"] = key
        resp = guarded_request(
            "POST",
            f"{_BASE}/timeseries/data/",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            json=payload,
            client=client,
        )
        resp.raise_for_status()
        return _parse_series_data(resp.json())
    finally:
        if owns_client:
            client.close()


def list_releases(
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """List BLS surveys (used as a proxy for watchable release calendar).

    Returns Documents describing available BLS surveys (CES, CPI, etc.).
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    key = _api_key(api_key)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        params = {"registrationkey": key} if key else {}
        resp = guarded_get(
            f"{_BASE}/surveys",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params=params,
            client=client,
        )
        resp.raise_for_status()
        result = resp.json()
        surveys = result.get("Results", {}).get("survey") or []
        out: list[Document] = []
        for s in surveys[:max_results]:
            survey_abbr = (s.get("survey_abbreviation") or s.get("survey_abbr") or "").strip()
            survey_name = " ".join((s.get("survey_name") or "").split())
            if not survey_name:
                continue
            out.append(Document(
                id=f"bls:survey:{survey_abbr}" if survey_abbr else f"bls:survey:{survey_name[:30]}",
                text=survey_name,
                metadata={
                    "source": "bls",
                    "url": f"https://www.bls.gov/{survey_abbr.lower()}/" if survey_abbr else "https://www.bls.gov/",
                    "grade": "A",
                    "title": survey_name,
                    "survey_abbreviation": survey_abbr,
                },
            ))
        return out
    finally:
        if owns_client:
            client.close()


def compare_geographies(
    series_ids: list[str],
    *,
    start_year: str = "2020",
    end_year: str = "2025",
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch and compare BLS series across geographies.

    Wraps ``fetch_series`` with a descriptive comparison framing. Returns
    Documents with cross-geography observations. Raises ``httpx.HTTPStatusError``
    on error.
    """
    return fetch_series(
        series_ids,
        start_year=start_year,
        end_year=end_year,
        max_results=max_results,
        client=client,
        timeout=timeout,
        api_key=api_key,
    )


def get_occupation_data(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Return curated BLS Occupational Employment series matching ``query``.

    BLS OES (Occupational Employment and Wage Statistics) data uses series IDs
    of the form ``OEUS{area_code}{industry_code}{data_type_code}``. This
    function provides a curated stub for common occupations. For production use,
    fetch real observations with ``fetch_series``.
    """
    _OCC_CATALOG = [
        ("OEUN000000000000015211", "Software Developers — Median Annual Wage", "software,developer,tech"),
        ("OEUN000000000000029111", "Registered Nurses — Median Annual Wage", "nurse,nursing,healthcare"),
        ("OEUN000000000000011202", "Chief Executives — Median Annual Wage", "ceo,executive,management"),
        ("OEUN000000000000013111", "Management Analysts — Median Annual Wage", "management,analyst,consulting"),
        ("OEUN000000000000053000", "Retail Salespersons — Median Annual Wage", "retail,sales"),
        ("OEUN000000000000151252", "Data Scientists — Median Annual Wage", "data,scientist,analytics,machine learning"),
    ]
    q = query.lower()
    out: list[Document] = []
    for series_id, title, tags in _OCC_CATALOG:
        if any(w in title.lower() or w in tags for w in q.split()):
            url = "https://data.bls.gov/oes/current/oes_nat.htm"
            out.append(Document(
                id=f"bls:{series_id}",
                text=f"BLS OES: {title} ({series_id})",
                metadata={
                    "source": "bls",
                    "url": url,
                    "grade": "A",
                    "title": title,
                    "series_id": series_id,
                    "dataset": "OES",
                },
            ))
        if len(out) >= max_results:
            break
    return out
