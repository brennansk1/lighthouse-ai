"""CourtListener source adapter — query the CourtListener REST API v4 (JSON).

CourtListener (https://www.courtlistener.com) is a Free Law Project resource
that indexes US federal and state court opinions, PACER documents, oral
arguments, and more. The REST API at
``https://www.courtlistener.com/api/rest/v4/search/`` supports free-text
queries across opinions and other document types.

Records are graded "B" because court opinions are primary legal documents; they
carry authoritative weight but have not been independently peer-reviewed in the
academic sense.

**API key**: CourtListener allows unauthenticated requests at a reduced rate
limit. Passing an ``api_key`` (obtained from
https://www.courtlistener.com/sign-in/) raises the rate limit substantially and
is recommended for production use. The key is forwarded as an
``Authorization: Token <key>`` header.

A client is injectable so the request is mockable under respx without touching
the network.
"""

from __future__ import annotations

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

_API = "https://www.courtlistener.com/api/rest/v4/search/"
_HEADERS = {"User-Agent": "Lighthouse/0.1"}

# The only host this adapter contacts: the CourtListener REST API. A user who
# invokes this source has authorized reaching the public API, so the host is
# declared allowed here and the guard's decide-before-fetch check passes for it.
_ALLOWED_HOSTS = frozenset({"www.courtlistener.com"})


def _parse(data: dict) -> list[Document]:
    out: list[Document] = []
    for result in data.get("results", []):
        case_name = (result.get("caseName") or "").strip()
        # Fall back to case_name if the camelCase variant is absent.
        if not case_name:
            case_name = (result.get("case_name") or "").strip()
        if not case_name:
            continue
        snippet = " ".join((result.get("snippet") or "").split())
        text = f"{case_name}. {snippet}" if snippet else case_name
        # The absolute_url gives a path like /opinion/12345/...; prepend host.
        absolute_url = result.get("absolute_url") or ""
        if absolute_url and not absolute_url.startswith("http"):
            url = f"https://www.courtlistener.com{absolute_url}"
        else:
            url = absolute_url
        cluster_id = result.get("cluster_id") or result.get("id") or ""
        date_filed = result.get("dateFiled") or result.get("date_filed") or ""
        court = result.get("court") or result.get("court_id") or ""
        out.append(Document(
            id=f"cl:{cluster_id}" if cluster_id else f"cl:{case_name[:40]}",
            text=text,
            metadata={
                "source": "courtlistener",
                "url": url,
                "grade": "B",
                "published_date": date_filed,
                "title": case_name,
                "court": court,
            },
        ))
    return out


def search_courtlistener(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Search CourtListener and return up to ``max_results`` opinions as Documents.

    Pass ``client`` to reuse a connection (and to make the request mockable in
    tests); otherwise a temporary client is opened and closed for this call.

    Pass ``api_key`` (a CourtListener REST API token) to raise the rate limit.
    Without a key the API allows limited unauthenticated requests; for production
    use obtain a free key at https://www.courtlistener.com/sign-in/.
    """
    headers = dict(_HEADERS)
    if api_key:
        headers["Authorization"] = f"Token {api_key}"

    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        r = guarded_get(
            _API,
            allowed_domains=_ALLOWED_HOSTS,
            headers=headers,
            params={"q": query, "type": "o", "page_size": max_results,
                    "order_by": "score desc"},
            client=client,
        )
        r.raise_for_status()
        return _parse(r.json())
    finally:
        if owns_client:
            client.close()
