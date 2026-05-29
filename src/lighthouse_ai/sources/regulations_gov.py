"""regulations.gov source adapter — Regulations.gov API v4.

Regulations.gov is the unified U.S. federal portal for public participation in
rulemaking. It hosts dockets (the administrative record for a rulemaking) and
comments (public submissions on proposed rules). The v4 JSON API at
``https://api.regulations.gov/v4`` requires a free API key from
https://open.gsa.gov/api/regulationsgov/.

Records are grade "A" as primary official government documents (dockets) or
grade "B" for public comments (unverified third-party submissions).

API: https://open.gsa.gov/api/regulationsgov/
Key required (free). Rate limit: 1,000 requests per hour unauthenticated,
higher with key. We default to 1 req/s.

**Egress note:** ``api.regulations.gov`` is NOT on the default Lighthouse
platform allowlist. The skill wrapping this adapter will receive an
``EgressBlocked`` exception. The skill degrades gracefully (returns ``[]`` with
a logged note). To unlock live fetches run:
``lighthouse trust add api.regulations.gov``

The adapter is httpx-based and client-injectable for respx testability.
"""

from __future__ import annotations

import httpx

from ..rag.chunker import Document

_BASE = "https://api.regulations.gov/v4"
_HEADERS = {"User-Agent": "Lighthouse/0.1", "Accept": "application/json"}


def _build_headers(api_key: str | None) -> dict[str, str]:
    h = dict(_HEADERS)
    if api_key:
        h["X-Api-Key"] = api_key
    return h


def _parse_dockets(data: dict) -> list[Document]:
    """Parse a /dockets response into Documents."""
    items = (data.get("data") or [])
    out: list[Document] = []
    for item in items:
        attrs = item.get("attributes") or {}
        docket_id = (item.get("id") or "").strip()
        title = " ".join((attrs.get("title") or "").split())
        if not title:
            continue
        docket_type = (attrs.get("docketType") or "").strip()
        agency_id = (attrs.get("agencyId") or "").strip()
        last_modified = (attrs.get("lastModifiedDate") or "").strip()
        url = f"https://www.regulations.gov/docket/{docket_id}" if docket_id else ""

        out.append(Document(
            id=f"regs:{docket_id}" if docket_id else f"regs:{title[:40]}",
            text=title,
            metadata={
                "source": "regulations_gov",
                "url": url,
                "grade": "A",
                "title": title,
                "docket_id": docket_id,
                "docket_type": docket_type,
                "agency_id": agency_id,
                "last_modified": last_modified,
            },
        ))
    return out


def _parse_documents(data: dict) -> list[Document]:
    """Parse a /documents response into Documents."""
    items = (data.get("data") or [])
    out: list[Document] = []
    for item in items:
        attrs = item.get("attributes") or {}
        doc_id = (item.get("id") or "").strip()
        title = " ".join((attrs.get("title") or "").split())
        if not title:
            continue
        doc_type = (attrs.get("documentType") or "").strip()
        agency_id = (attrs.get("agencyId") or "").strip()
        posted_date = (attrs.get("postedDate") or "").strip()
        docket_id = (attrs.get("docketId") or "").strip()
        url = f"https://www.regulations.gov/document/{doc_id}" if doc_id else ""

        out.append(Document(
            id=f"regs:doc:{doc_id}" if doc_id else f"regs:doc:{title[:40]}",
            text=title,
            metadata={
                "source": "regulations_gov",
                "url": url,
                "grade": "A",
                "title": title,
                "document_id": doc_id,
                "document_type": doc_type,
                "agency_id": agency_id,
                "posted_date": posted_date,
                "docket_id": docket_id,
            },
        ))
    return out


def _parse_comments(data: dict) -> list[Document]:
    """Parse a /comments response into Documents."""
    items = (data.get("data") or [])
    out: list[Document] = []
    for item in items:
        attrs = item.get("attributes") or {}
        comment_id = (item.get("id") or "").strip()
        title = " ".join((attrs.get("title") or "").split())
        if not title:
            continue
        comment_text = " ".join((attrs.get("comment") or "").split())
        posted_date = (attrs.get("postedDate") or "").strip()
        docket_id = (attrs.get("docketId") or "").strip()
        url = f"https://www.regulations.gov/comment/{comment_id}" if comment_id else ""

        text = title
        if comment_text:
            text = f"{title}. {comment_text[:500]}"

        out.append(Document(
            id=f"regs:comment:{comment_id}" if comment_id else f"regs:comment:{title[:40]}",
            text=text,
            metadata={
                "source": "regulations_gov",
                "url": url,
                "grade": "B",  # public comments are unverified third-party
                "title": title,
                "comment_id": comment_id,
                "posted_date": posted_date,
                "docket_id": docket_id,
            },
        ))
    return out


def search_dockets(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Search regulations.gov dockets by keyword.

    Uses the v4 ``/dockets`` endpoint with ``filter[searchTerm]``. Returns
    docket-level records (the administrative record container, not individual
    comments).

    Pass ``client`` to reuse a connection (mockable in tests); otherwise a
    temporary client is used. Pass ``api_key`` for the registered API key.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/dockets",
            headers=_build_headers(api_key),
            params={
                "filter[searchTerm]": query,
                "page[size]": max_results,
                "sort": "lastModifiedDate,DESC",
            },
        )
        resp.raise_for_status()
        return _parse_dockets(resp.json())
    finally:
        if owns_client:
            client.close()


def fetch_docket(
    docket_id: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch a single docket by its ID.

    Returns a list with one Document on success or [] if not found.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/dockets/{docket_id}",
            headers=_build_headers(api_key),
        )
        resp.raise_for_status()
        item = resp.json().get("data") or {}
        if not item:
            return []
        return _parse_dockets({"data": [item]})
    finally:
        if owns_client:
            client.close()


def list_comments(
    docket_id: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """List public comments filed on a specific docket.

    Comments are grade "B" — they are unverified public submissions.
    Ordered by posted date descending. This function is a watchable tool:
    new comments on active dockets can be tracked incrementally.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/comments",
            headers=_build_headers(api_key),
            params={
                "filter[commentOnId]": docket_id,
                "page[size]": max_results,
                "sort": "postedDate,DESC",
            },
        )
        resp.raise_for_status()
        return _parse_comments(resp.json())
    finally:
        if owns_client:
            client.close()


def track_docket_activity(
    docket_id: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Track recent document activity (not comments) in a docket.

    Returns documents (notices, proposed rules, final rules) filed in the
    docket, ordered by posted date descending. This is the watchable tool
    for monitoring when the agency advances a rulemaking.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/documents",
            headers=_build_headers(api_key),
            params={
                "filter[docketId]": docket_id,
                "page[size]": max_results,
                "sort": "postedDate,DESC",
            },
        )
        resp.raise_for_status()
        return _parse_documents(resp.json())
    finally:
        if owns_client:
            client.close()
