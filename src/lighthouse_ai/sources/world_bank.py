"""World Bank Open Data source adapter — World Bank API v2.

The World Bank Open Data API provides access to development indicators for
200+ economies. The base URL is ``https://api.worldbank.org/v2``.
No authentication is required.

Key endpoints used here:
  * ``/indicator?format=json&per_page=N`` — list/search indicators
  * ``/country/{country}/indicator/{indicator}?format=json`` — fetch indicator data
  * ``/country?format=json`` — list countries with metadata
  * ``/topic?format=json`` — list topics for indicator browsing

**Auth:** None required.

**Egress note:** ``api.worldbank.org`` must be on the Lighthouse platform
allowlist. Run ``lighthouse trust add api.worldbank.org`` to enable live fetches.

The adapter is httpx-based and client-injectable for respx testability.
"""

from __future__ import annotations

import httpx

from ..rag.chunker import Document

_BASE = "https://api.worldbank.org/v2"
_HEADERS = {"User-Agent": "Lighthouse/0.1", "Accept": "application/json"}


def _parse_indicator_list(data: list, query: str) -> list[Document]:
    """Parse World Bank indicator list (JSON array, element 1 is the data) into Documents."""
    # World Bank API returns [metadata, data] as a JSON array
    if not isinstance(data, list) or len(data) < 2:
        return []
    items = data[1] or []
    query_lower = query.lower()
    out: list[Document] = []
    for item in items:
        indicator_id = (item.get("id") or "").strip()
        name = " ".join((item.get("name") or "").split())
        source_note = " ".join((item.get("sourceNote") or "").split())
        if not name:
            continue
        # Client-side relevance filter
        combined = f"{name} {source_note}".lower()
        if query_lower and not any(w in combined for w in query_lower.split()):
            continue
        text = name
        if source_note:
            text = f"{name}. {source_note[:300]}"
        url = f"https://data.worldbank.org/indicator/{indicator_id}"
        out.append(Document(
            id=f"worldbank:indicator:{indicator_id}",
            text=text,
            metadata={
                "source": "world_bank",
                "url": url,
                "grade": "A",
                "title": name,
                "indicator_id": indicator_id,
                "source_note": source_note[:200] if source_note else "",
            },
        ))
    return out


def _parse_indicator_data(data: list, country: str, indicator: str) -> list[Document]:
    """Parse World Bank indicator data for a country into Documents."""
    if not isinstance(data, list) or len(data) < 2:
        return []
    items = data[1] or []
    if not items:
        return []
    # Group into one document with recent values
    values = []
    country_name = ""
    indicator_name = ""
    for item in items:
        if not item:
            continue
        year = str(item.get("date") or "").strip()
        value = item.get("value")
        if value is None:
            continue
        country_name = country_name or (item.get("country", {}) or {}).get("value", country)
        indicator_name = indicator_name or (item.get("indicator", {}) or {}).get("value", indicator)
        values.append(f"{year}: {value}")
    if not values:
        return []
    recent = values[:10]
    text = f"{indicator_name} — {country_name}: {'; '.join(recent)}"
    url = f"https://data.worldbank.org/indicator/{indicator}?locations={country}"
    return [Document(
        id=f"worldbank:{indicator}:{country}",
        text=text,
        metadata={
            "source": "world_bank",
            "url": url,
            "grade": "A",
            "title": f"{indicator_name} — {country_name}",
            "indicator_id": indicator,
            "country_code": country,
            "country_name": country_name,
            "observation_count": len(values),
        },
    )]


def search_indicator(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Search World Bank indicators matching ``query``.

    Fetches up to 100 indicators and filters client-side. Returns up to
    ``max_results`` Documents. Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    ``api_key`` is ignored (World Bank requires no auth).
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/indicator",
            headers=_HEADERS,
            params={"format": "json", "per_page": 100, "page": 1},
        )
        resp.raise_for_status()
        docs = _parse_indicator_list(resp.json(), query)
        return docs[:max_results]
    finally:
        if owns_client:
            client.close()


def fetch_indicator(
    indicator: str,
    country: str = "WLD",
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch World Bank indicator data for a country (default: world aggregate).

    ``indicator`` is a World Bank indicator ID (e.g. ``'NY.GDP.MKTP.CD'``).
    ``country`` is an ISO 3166-1 alpha-3 code (e.g. ``'USA'``) or ``'WLD'``.
    Returns Documents with time-series observations.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/country/{country}/indicator/{indicator}",
            headers=_HEADERS,
            params={"format": "json", "per_page": 50, "mrv": 10},
        )
        resp.raise_for_status()
        return _parse_indicator_data(resp.json(), country, indicator)
    finally:
        if owns_client:
            client.close()


def list_indicators_by_topic(
    topic_id: int = 1,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """List World Bank indicators for a topic ID.

    Common topic IDs: 1=Agriculture, 3=Economy, 5=Education, 6=Environment,
    8=Health, 11=Infrastructure, 19=Poverty, 20=Private Sector.
    Returns up to ``max_results`` indicator Documents.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/topic/{topic_id}/indicator",
            headers=_HEADERS,
            params={"format": "json", "per_page": max_results},
        )
        resp.raise_for_status()
        docs = _parse_indicator_list(resp.json(), "")
        return docs[:max_results]
    finally:
        if owns_client:
            client.close()


def compare_countries(
    indicator: str,
    country_codes: list[str],
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch an indicator for multiple countries and return comparison Documents.

    Returns one Document per country. Uses ``fetch_indicator`` for each.
    Raises ``httpx.HTTPStatusError`` on the first failing request.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        out: list[Document] = []
        for country in country_codes[:max_results]:
            docs = fetch_indicator(
                indicator, country,
                max_results=max_results,
                client=client,
                timeout=timeout,
            )
            out.extend(docs)
        return out[:max_results]
    finally:
        if owns_client:
            client.close()


def get_country_metadata(
    country_code: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch metadata for a World Bank country by ISO code.

    Returns a Document with country name, region, income level, capital, and
    ISO codes. Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/country/{country_code}",
            headers=_HEADERS,
            params={"format": "json"},
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or len(data) < 2:
            return []
        items = data[1] or []
        out: list[Document] = []
        for item in items[:max_results]:
            name = (item.get("name") or "").strip()
            region = (item.get("region", {}) or {}).get("value", "")
            income_level = (item.get("incomeLevel", {}) or {}).get("value", "")
            capital = (item.get("capitalCity") or "").strip()
            iso2 = (item.get("iso2Code") or "").strip()
            iso3 = (item.get("id") or "").strip()
            text = (
                f"{name} ({iso3}/{iso2}). "
                f"Region: {region}. Income: {income_level}. Capital: {capital}."
            )
            out.append(Document(
                id=f"worldbank:country:{iso3}",
                text=text,
                metadata={
                    "source": "world_bank",
                    "url": f"https://data.worldbank.org/country/{iso3}",
                    "grade": "A",
                    "title": name,
                    "country_code": iso3,
                    "iso2": iso2,
                    "region": region,
                    "income_level": income_level,
                    "capital": capital,
                },
            ))
        return out
    finally:
        if owns_client:
            client.close()
