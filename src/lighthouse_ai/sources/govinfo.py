"""GovInfo source adapter — GovInfo.gov API (api.govinfo.gov).

GovInfo is the U.S. Government Publishing Office (GPO) official repository of
government publications. The API provides programmatic access to collections
including:
  - CFR (Code of Federal Regulations)
  - USCODE (United States Code)
  - CREC (Congressional Record)
  - GAOREPORTS (GAO Reports)
  - PLAW (Public Laws)
  - and many more.

API base: https://api.govinfo.gov
Key required (free): https://api.govinfo.gov/docs/

Records are grade "A" as authoritative primary legal and statutory documents.

**Egress note:** ``api.govinfo.gov`` is NOT on the default Lighthouse platform
allowlist. The skill wrapping this adapter will receive an ``EgressBlocked``
exception. The skill degrades gracefully (returns ``[]`` with a logged note).
To unlock live fetches run: ``lighthouse trust add api.govinfo.gov``

The adapter is httpx-based and client-injectable for respx testability.
"""

from __future__ import annotations

import httpx

from ..rag.chunker import Document

_BASE = "https://api.govinfo.gov"
_HEADERS = {"User-Agent": "Lighthouse/0.1", "Accept": "application/json"}


def _build_params(api_key: str | None, extra: dict) -> dict:
    params = dict(extra)
    if api_key:
        params["api_key"] = api_key
    return params


def _parse_search_results(data: dict) -> list[Document]:
    """Parse a /search response into Documents."""
    packages = (data.get("packages") or [])
    out: list[Document] = []
    for pkg in packages:
        title = " ".join((pkg.get("title") or "").split())
        if not title:
            continue
        package_id = (pkg.get("packageId") or "").strip()
        collection_code = (pkg.get("collectionCode") or "").strip()
        date_issued = (pkg.get("dateIssued") or "").strip()
        gov_url = (pkg.get("packageLink") or "").strip()
        doc_class = (pkg.get("docClass") or "").strip()

        out.append(Document(
            id=f"govinfo:{package_id}" if package_id else f"govinfo:{title[:40]}",
            text=title,
            metadata={
                "source": "govinfo",
                "url": gov_url,
                "grade": "A",
                "title": title,
                "package_id": package_id,
                "collection_code": collection_code,
                "date_issued": date_issued,
                "doc_class": doc_class,
            },
        ))
    return out


def search_collection(
    query: str,
    *,
    collection: str | None = None,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Search GovInfo across all collections or within a specific one.

    ``collection`` is an optional collection code (e.g. ``"CFR"``, ``"USCODE"``,
    ``"CREC"``, ``"GAOREPORTS"``). When omitted, searches all collections.

    Pass ``client`` to reuse a connection (mockable in tests).
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        params: dict = {
            "query": query,
            "pageSize": max_results,
            "offsetMark": "*",
        }
        if collection:
            params["collection"] = collection
        resp = client.get(
            f"{_BASE}/search",
            headers=_HEADERS,
            params=_build_params(api_key, params),
        )
        resp.raise_for_status()
        return _parse_search_results(resp.json())
    finally:
        if owns_client:
            client.close()


def fetch_document(
    package_id: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch a single GovInfo package by its package ID.

    Returns a list with one Document on success or [] if not found.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/packages/{package_id}/summary",
            headers=_HEADERS,
            params=_build_params(api_key, {}),
        )
        resp.raise_for_status()
        data = resp.json()
        title = " ".join((data.get("title") or "").split())
        if not title:
            return []
        collection_code = (data.get("collectionCode") or "").strip()
        date_issued = (data.get("dateIssued") or "").strip()
        gov_url = (data.get("packageLink") or "").strip()
        doc_class = (data.get("docClass") or "").strip()
        return [Document(
            id=f"govinfo:{package_id}",
            text=title,
            metadata={
                "source": "govinfo",
                "url": gov_url,
                "grade": "A",
                "title": title,
                "package_id": package_id,
                "collection_code": collection_code,
                "date_issued": date_issued,
                "doc_class": doc_class,
            },
        )]
    finally:
        if owns_client:
            client.close()


def get_cfr_section(
    title_number: int,
    part: str,
    *,
    year: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch a Code of Federal Regulations section.

    Searches GovInfo for CFR documents matching a specific title and part.
    ``title_number`` is the CFR title (e.g. ``40`` for EPA regulations).
    ``part`` is the part number within that title (e.g. ``"50"``).
    ``year`` optionally filters to a specific CFR edition year.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    query = f"CFR title {title_number} part {part}"
    if year:
        query = f"{query} {year}"
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/search",
            headers=_HEADERS,
            params=_build_params(api_key, {
                "query": query,
                "collection": "CFR",
                "pageSize": 5,
                "offsetMark": "*",
            }),
        )
        resp.raise_for_status()
        return _parse_search_results(resp.json())
    finally:
        if owns_client:
            client.close()


def get_uscode_section(
    title_number: int,
    section: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch a United States Code section.

    ``title_number`` is the U.S.C. title (e.g. ``42`` for public health/welfare).
    ``section`` is the section number within the title (e.g. ``"7401"``).

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    query = f"USC title {title_number} section {section}"
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/search",
            headers=_HEADERS,
            params=_build_params(api_key, {
                "query": query,
                "collection": "USCODE",
                "pageSize": 5,
                "offsetMark": "*",
            }),
        )
        resp.raise_for_status()
        return _parse_search_results(resp.json())
    finally:
        if owns_client:
            client.close()


def list_recent_in_collection(
    collection: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """List recently published documents in a GovInfo collection.

    ``collection`` must be a valid GovInfo collection code (e.g. ``"CREC"`` for
    Congressional Record, ``"GAOREPORTS"`` for GAO Reports, ``"CFR"`` for the
    Code of Federal Regulations). Results are ordered by date descending.

    This function is the watchable tool: it returns time-ordered results
    suitable for incremental Watch ticks.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/collections/{collection}",
            headers=_HEADERS,
            params=_build_params(api_key, {
                "pageSize": max_results,
                "offsetMark": "*",
            }),
        )
        resp.raise_for_status()
        data = resp.json()
        # /collections endpoint returns packages array
        packages = data.get("packages") or []
        out: list[Document] = []
        for pkg in packages:
            title = " ".join((pkg.get("title") or "").split())
            if not title:
                continue
            package_id = (pkg.get("packageId") or "").strip()
            date_issued = (pkg.get("dateIssued") or "").strip()
            gov_url = (pkg.get("packageLink") or "").strip()
            doc_class = (pkg.get("docClass") or "").strip()
            out.append(Document(
                id=f"govinfo:{package_id}" if package_id else f"govinfo:{title[:40]}",
                text=title,
                metadata={
                    "source": "govinfo",
                    "url": gov_url,
                    "grade": "A",
                    "title": title,
                    "package_id": package_id,
                    "collection_code": collection,
                    "date_issued": date_issued,
                    "doc_class": doc_class,
                },
            ))
        return out
    finally:
        if owns_client:
            client.close()
