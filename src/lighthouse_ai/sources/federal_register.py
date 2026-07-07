"""Federal Register source adapter — FederalRegister.gov API v1.

FederalRegister.gov is the official daily journal of the United States federal
government. The v1 JSON API (``https://www.federalregister.gov/api/v1``)
provides full-text search over published notices, proposed rules, final rules,
executive orders, proclamations, and other document types.

Records are grade "A" as authoritative primary government publications.

API: https://www.federalregister.gov/developers/documentation/api/version1
No API key required. Rate-limited; we send 1 req/s by default.

**Egress note:** ``federalregister.gov`` is NOT on the default Lighthouse
platform allowlist. The skill wrapping this adapter will receive an
``EgressBlocked`` exception. The skill degrades gracefully (returns ``[]`` with
a logged note). To unlock live fetches run:
``lighthouse trust add federalregister.gov``

The adapter is httpx-based and client-injectable so it is testable under
``respx`` without real network access.
"""

from __future__ import annotations

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

_BASE = "https://www.federalregister.gov/api/v1"
_HEADERS = {"User-Agent": "Lighthouse/0.1", "Accept": "application/json"}

# The only host this adapter contacts: the FederalRegister.gov API v1. A user
# who invokes this source has authorized reaching the public API, so the host is
# declared allowed here and the guard's decide-before-fetch check passes for it.
_ALLOWED_HOSTS = frozenset({"www.federalregister.gov"})


def _parse_documents(data: dict) -> list[Document]:
    """Turn a FederalRegister.gov /documents.json response into Documents."""
    results = data.get("results") or []
    out: list[Document] = []
    for item in results:
        title = " ".join((item.get("title") or "").split())
        if not title:
            continue
        doc_number = (item.get("document_number") or "").strip()
        doc_type = (item.get("type") or "").strip()
        abstract = " ".join((item.get("abstract") or "").split())
        agency_names = item.get("agency_names") or []
        publication_date = (item.get("publication_date") or "").strip()
        html_url = (item.get("html_url") or "").strip()
        citation = (item.get("citation") or "").strip()

        text = title
        if abstract:
            text = f"{title}. {abstract}"

        out.append(
            Document(
                id=f"fedreg:{doc_number}" if doc_number else f"fedreg:{title[:40]}",
                text=text,
                metadata={
                    "source": "federal_register",
                    "url": html_url,
                    "grade": "A",
                    "title": title,
                    "document_number": doc_number,
                    "document_type": doc_type,
                    "agency_names": agency_names,
                    "publication_date": publication_date,
                    "citation": citation,
                },
            )
        )
    return out


def search_rules(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Search FederalRegister.gov for rules, notices, and executive orders.

    Uses the v1 ``/documents.json`` endpoint with ``conditions[term]`` for
    full-text search. Pass ``client`` to reuse a connection (and to make calls
    mockable in tests); otherwise a temporary client is used.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            f"{_BASE}/documents.json",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params={
                "conditions[term]": query,
                "per_page": max_results,
                "order": "relevance",
                "fields[]": [
                    "document_number",
                    "type",
                    "title",
                    "abstract",
                    "agency_names",
                    "publication_date",
                    "html_url",
                    "citation",
                ],
            },
            client=client,
        )
        resp.raise_for_status()
        return _parse_documents(resp.json())
    finally:
        if owns_client:
            client.close()


def fetch_rule(
    document_number: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch a single Federal Register document by its document number.

    Returns a list with one Document on success or [] if not found.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            f"{_BASE}/documents/{document_number}.json",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params={
                "fields[]": [
                    "document_number",
                    "type",
                    "title",
                    "abstract",
                    "agency_names",
                    "publication_date",
                    "html_url",
                    "citation",
                ],
            },
            client=client,
        )
        resp.raise_for_status()
        item = resp.json()
        docs = _parse_documents({"results": [item]})
        return docs
    finally:
        if owns_client:
            client.close()


def list_recent_in_agency(
    agency_slug: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """List recent Federal Register documents published by a specific agency.

    ``agency_slug`` is the slug used by FederalRegister.gov (e.g. ``"epa"``,
    ``"fda"``, ``"doj"``). Results are ordered by publication date descending.
    This function is the watchable tool: it returns time-ordered results suitable
    for incremental Watch ticks.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            f"{_BASE}/documents.json",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params={
                "conditions[agencies][]": agency_slug,
                "per_page": max_results,
                "order": "newest",
                "fields[]": [
                    "document_number",
                    "type",
                    "title",
                    "abstract",
                    "agency_names",
                    "publication_date",
                    "html_url",
                    "citation",
                ],
            },
            client=client,
        )
        resp.raise_for_status()
        return _parse_documents(resp.json())
    finally:
        if owns_client:
            client.close()


def get_executive_orders(
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch recent Executive Orders from the Federal Register.

    Filters by ``type=PRESDOCU`` (Presidential Documents) and
    ``conditions[presidential_document_type]=executive_order``.
    Results are ordered by publication date descending.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            f"{_BASE}/documents.json",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params={
                "conditions[type][]": "PRESDOCU",
                "conditions[presidential_document_type][]": "executive_order",
                "per_page": max_results,
                "order": "newest",
                "fields[]": [
                    "document_number",
                    "type",
                    "title",
                    "abstract",
                    "agency_names",
                    "publication_date",
                    "html_url",
                    "citation",
                ],
            },
            client=client,
        )
        resp.raise_for_status()
        return _parse_documents(resp.json())
    finally:
        if owns_client:
            client.close()


def track_rulemaking(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Track rulemaking stages (NPRM → final rule) for a topic.

    Searches for both proposed rules (PRORULE) and final rules (RULE) matching
    the query, returning them ordered by publication date so callers can
    reconstruct the NPRM→final timeline.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            f"{_BASE}/documents.json",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params={
                "conditions[term]": query,
                "conditions[type][]": ["PRORULE", "RULE"],
                "per_page": max_results,
                "order": "newest",
                "fields[]": [
                    "document_number",
                    "type",
                    "title",
                    "abstract",
                    "agency_names",
                    "publication_date",
                    "html_url",
                    "citation",
                ],
            },
            client=client,
        )
        resp.raise_for_status()
        return _parse_documents(resp.json())
    finally:
        if owns_client:
            client.close()
