"""U.S. Census Bureau source adapter — Census Data API.

The U.S. Census Bureau provides demographic, economic, and geographic data
via its Data API. The base URL is ``https://api.census.gov/data``.

Key datasets used here:
  * ACS 5-Year (``acs/acs5``) — American Community Survey 5-year estimates
  * ACS 1-Year (``acs/acs1``) — American Community Survey 1-year estimates
  * Decennial Census (``dec/sf1``) — Decennial Census Summary File 1
  * Population Estimates (``pep/population``) — annual population estimates

Common geographic levels: ``us``, ``state``, ``county``, ``place``, ``tract``.

**Auth:** A free API key increases quota. Register at
https://api.census.gov/data/key_signup.html. Pass via ``api_key`` parameter
or the ``CENSUS_API_KEY`` environment variable.

**Egress note:** ``api.census.gov`` must be on the Lighthouse platform allowlist.
Run ``lighthouse trust add api.census.gov`` to enable live fetches.

The adapter is httpx-based and client-injectable for respx testability.
"""

from __future__ import annotations

import os

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

_BASE = "https://api.census.gov/data"
_HEADERS = {"User-Agent": "Lighthouse/0.1", "Accept": "application/json"}

# Public Census API hosts this adapter contacts. The user invoked the census
# source explicitly, so these hosts are authorized for egress.
_ALLOWED_HOSTS = frozenset({"api.census.gov", "data.census.gov"})

# Curated ACS variable descriptions (common variables)
_ACS_VARS = {
    "B01003_001E": "Total Population",
    "B19013_001E": "Median Household Income",
    "B17001_002E": "Population Below Poverty Level",
    "B25003_001E": "Total Housing Units",
    "B25003_002E": "Owner-Occupied Housing Units",
    "B25003_003E": "Renter-Occupied Housing Units",
    "B15003_022E": "Bachelor's Degree or Higher",
    "B23025_005E": "Unemployed Civilians",
    "B02001_002E": "White Alone Population",
    "B02001_003E": "Black or African American Alone",
}


def _api_key(api_key: str | None) -> str:
    """Resolve API key from argument or environment variable."""
    return api_key or os.environ.get("CENSUS_API_KEY", "")


def _parse_census_response(
    data: list, dataset: str, variables: list[str], geography: str
) -> list[Document]:
    """Parse Census API tabular response (list-of-lists) into Documents.

    The first row is always the column headers. Subsequent rows are data.
    """
    if not isinstance(data, list) or len(data) < 2:
        return []
    headers = data[0]
    rows = data[1:]
    out: list[Document] = []
    for row in rows:
        if len(row) != len(headers):
            continue
        record = dict(zip(headers, row))
        # Build human-readable label from geo identifiers
        geo_parts = []
        for geo_field in ["NAME", "state", "county", "tract", "us"]:
            if geo_field in record:
                geo_parts.append(record[geo_field])
        geo_label = ", ".join(p for p in geo_parts if p) or geography

        var_lines = []
        for v in variables:
            if v in record:
                desc = _ACS_VARS.get(v, v)
                var_lines.append(f"{desc}: {record[v]}")

        text = (
            f"{dataset} — {geo_label}: {'; '.join(var_lines)}"
            if var_lines
            else f"{dataset} — {geo_label}"
        )
        doc_id = f"census:{dataset}:{geo_label[:40]}"
        out.append(
            Document(
                id=doc_id,
                text=text,
                metadata={
                    "source": "census",
                    "url": "https://data.census.gov/",
                    "grade": "A",
                    "title": f"{dataset} — {geo_label}",
                    "dataset": dataset,
                    "geography": geography,
                    "geo_label": geo_label,
                    **{v: record.get(v, "") for v in variables},
                },
            )
        )
    return out


def search_dataset(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Search Census dataset discovery endpoint for datasets matching ``query``.

    Fetches the dataset list from ``/data.json`` and filters by title/description.
    Returns up to ``max_results`` Documents.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            "https://api.census.gov/data.json",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            client=client,
        )
        resp.raise_for_status()
        data = resp.json()
        datasets = data.get("dataset") or []
        q = query.lower()
        out: list[Document] = []
        for ds in datasets:
            title = " ".join((ds.get("title") or "").split())
            desc = " ".join((ds.get("description") or "").split())
            combined = f"{title} {desc}".lower()
            if q and not any(w in combined for w in q.split()):
                continue
            url = (
                (ds.get("distribution") or [{}])[0].get("accessURL", "https://api.census.gov/data")
                if isinstance(ds.get("distribution"), list)
                else "https://api.census.gov/data"
            )
            vintage = str(ds.get("c_vintage") or "").strip()
            dataset_id = ds.get("c_dataset") or ds.get("identifier") or ""
            if isinstance(dataset_id, list):
                dataset_id = "/".join(dataset_id)
            out.append(
                Document(
                    id=f"census:dataset:{title[:50]}",
                    text=f"{title}. {desc[:200]}" if desc else title,
                    metadata={
                        "source": "census",
                        "url": url,
                        "grade": "A",
                        "title": title,
                        "dataset_id": str(dataset_id),
                        "vintage": vintage,
                    },
                )
            )
            if len(out) >= max_results:
                break
        return out
    finally:
        if owns_client:
            client.close()


def fetch_acs_table(
    variables: list[str],
    *,
    year: int = 2022,
    geography: str = "us",
    geo_id: str = "*",
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch ACS 5-year estimates for given variables and geography.

    ``variables`` — list of Census variable IDs (e.g. ``['B01003_001E', 'B19013_001E']``).
    ``year`` — survey year (default 2022).
    ``geography`` — geographic level: ``'us'``, ``'state'``, ``'county'``, ``'tract'``.
    ``geo_id`` — FIPS code or ``'*'`` for all entities at this level.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    key = _api_key(api_key)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        # Always include NAME for readable geography label
        get_vars = list(dict.fromkeys(["NAME", *variables]))
        params: dict = {
            "get": ",".join(get_vars),
            "for": f"{geography}:{geo_id}",
        }
        if key:
            params["key"] = key
        resp = guarded_get(
            f"{_BASE}/{year}/acs/acs5",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params=params,
            client=client,
        )
        resp.raise_for_status()
        docs = _parse_census_response(resp.json(), f"ACS5/{year}", variables, geography)
        return docs[:max_results]
    finally:
        if owns_client:
            client.close()


def fetch_decennial(
    variables: list[str],
    *,
    year: int = 2020,
    geography: str = "us",
    geo_id: str = "*",
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch decennial census data for given variables and geography.

    Uses ``dec/dhc`` (2020 Demographic and Housing Characteristics) or
    ``dec/sf1`` for 2010 and earlier.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    key = _api_key(api_key)
    dataset = "dec/dhc" if year >= 2020 else "dec/sf1"
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        get_vars = list(dict.fromkeys(["NAME", *variables]))
        params: dict = {
            "get": ",".join(get_vars),
            "for": f"{geography}:{geo_id}",
        }
        if key:
            params["key"] = key
        resp = guarded_get(
            f"{_BASE}/{year}/{dataset}",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params=params,
            client=client,
        )
        resp.raise_for_status()
        docs = _parse_census_response(resp.json(), f"Decennial/{year}", variables, geography)
        return docs[:max_results]
    finally:
        if owns_client:
            client.close()


def query_geographic(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Look up Census geographic identifiers (FIPS codes) matching ``query``.

    Returns curated stub Documents for common geographic entities. For
    production use, combine with ``fetch_acs_table`` using the returned
    FIPS codes.
    """
    _GEO_CATALOG = [
        ("01", "state", "Alabama", "AL"),
        ("06", "state", "California", "CA"),
        ("36", "state", "New York", "NY"),
        ("48", "state", "Texas", "TX"),
        ("12", "state", "Florida", "FL"),
        ("17", "state", "Illinois", "IL"),
        ("42", "state", "Pennsylvania", "PA"),
        ("39", "state", "Ohio", "OH"),
        ("13", "state", "Georgia", "GA"),
        ("37", "state", "North Carolina", "NC"),
    ]
    q = query.lower()
    out: list[Document] = []
    for fips, geo_type, name, abbr in _GEO_CATALOG:
        if not q or any(w in name.lower() or w in abbr.lower() for w in q.split()):
            text = f"{name} ({abbr}) — FIPS {fips}, Census {geo_type}"
            out.append(
                Document(
                    id=f"census:geo:{fips}",
                    text=text,
                    metadata={
                        "source": "census",
                        "url": "https://data.census.gov/",
                        "grade": "A",
                        "title": f"{name} ({abbr})",
                        "fips": fips,
                        "geo_type": geo_type,
                        "state_name": name,
                        "abbreviation": abbr,
                    },
                )
            )
        if len(out) >= max_results:
            break
    return out
