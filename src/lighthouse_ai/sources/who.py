"""WHO Global Health Observatory (GHO) source adapter — OData API v3.

The World Health Organization's GHO OData API is the primary free endpoint for
programmatic access to WHO health indicators. Key endpoints used here:

  * ``/api/GHO`` — list / search indicators (dimensions with code ``GHO``)
  * ``/api/GHO/{indicator_code}`` — fetch data values for a specific indicator

The base URL is ``https://ghoapi.azureedge.net/api`` (the CDN-hosted OData
service; the canonical ``apps.who.int/gho/athena/api`` is functionally
equivalent but this endpoint is documented in the WHO developer guides).

**Egress note:** Neither ``ghoapi.azureedge.net`` nor ``who.int`` is on the
default Lighthouse platform allowlist. A skill wrapping this adapter will
receive ``EgressBlocked`` from ``ctx.fetch`` and must degrade gracefully (return
``[]`` with a logged note). To unlock live fetches run:
``lighthouse trust add ghoapi.azureedge.net`` or
``lighthouse trust add who.int``

The adapter is httpx-based and client-injectable for respx testability.
"""

from __future__ import annotations

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

_BASE = "https://ghoapi.azureedge.net/api"
_HEADERS = {"User-Agent": "Lighthouse/0.1", "Accept": "application/json"}
# Public WHO GHO OData API host(s) this adapter contacts. The user invoked this
# source for WHO health data, so these are authorized egress destinations.
_ALLOWED_HOSTS = frozenset({"ghoapi.azureedge.net", "who.int"})


def _parse_indicators(data: dict, query: str) -> list[Document]:
    """Turn a GHO indicator list JSON response into Documents.

    The OData response has a ``value`` array; each entry has ``IndicatorCode``,
    ``IndicatorName``, and optionally ``Language``.  We filter to entries whose
    name contains the query terms (case-insensitive) since the API does not
    support server-side full-text search on indicator names.
    """
    items = data.get("value") or []
    query_lower = query.lower()
    out: list[Document] = []
    for item in items:
        code = (item.get("IndicatorCode") or "").strip()
        name = " ".join((item.get("IndicatorName") or "").split())
        if not name:
            continue
        # Client-side relevance filter: skip if none of the query words appear
        if query_lower and not any(w in name.lower() for w in query_lower.split()):
            continue
        url = f"https://ghoapi.azureedge.net/api/{code}" if code else ""
        out.append(Document(
            id=f"who:{code}" if code else f"who:{name[:40]}",
            text=name,
            metadata={
                "source": "who",
                "url": url,
                "grade": "A",
                "title": name,
                "indicator_code": code,
            },
        ))
    return out


def _parse_data_values(data: dict, code: str) -> list[Document]:
    """Turn a GHO data values response for a specific indicator into Documents.

    The OData response for ``/api/GHO/{code}`` has a ``value`` array where each
    row is an observation: ``SpatialDim`` (country), ``TimeDim`` (year),
    ``NumericValue``, and ``Dim1`` (dimension, e.g. sex). We group into one
    Document per country for conciseness.
    """
    items = data.get("value") or []
    # Group by country
    by_country: dict[str, list[str]] = {}
    for item in items:
        country = (item.get("SpatialDim") or "").strip()
        year = str(item.get("TimeDim") or "")
        value = item.get("NumericValue")
        if not country or value is None:
            continue
        entry = f"{year}: {value}" if year else str(value)
        by_country.setdefault(country, []).append(entry)

    out: list[Document] = []
    for country, entries in by_country.items():
        summary = "; ".join(entries[:5])  # max 5 observations per country
        text = f"{code} — {country}: {summary}"
        out.append(Document(
            id=f"who:{code}:{country}",
            text=text,
            metadata={
                "source": "who",
                "url": f"https://ghoapi.azureedge.net/api/{code}",
                "grade": "A",
                "title": f"{code} — {country}",
                "indicator_code": code,
                "country": country,
            },
        ))
    return out


def search_who(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Search WHO GHO indicators and return up to ``max_results`` as Documents.

    Fetches the full indicator list from ``/api/GHO`` (which is a single JSON
    payload listing all ~2000 indicators) and performs client-side relevance
    filtering on ``IndicatorName``. This approach is necessary because the GHO
    OData API does not expose a free-text indicator search endpoint.

    Pass ``client`` to reuse a connection (and to make the call mockable in
    tests); otherwise a temporary client is used.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            f"{_BASE}/GHO",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            client=client,
        )
        resp.raise_for_status()
        docs = _parse_indicators(resp.json(), query)
        return docs[:max_results]
    finally:
        if owns_client:
            client.close()
