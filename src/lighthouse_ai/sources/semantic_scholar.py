"""Semantic Scholar source adapter — query the Semantic Scholar Graph API (JSON).

Returns :class:`lighthouse_ai.rag.chunker.Document` objects (title + abstract)
ready to ingest into the research corpus.

**Rate limit note**: The unauthenticated tier is limited to ~1 request/second.
Callers are responsible for pacing when issuing multiple searches in a loop.
Passing an ``api_key`` (S2 API key) raises the limit to 1 req/second on the
free tier and higher on approved partner tiers; the key is forwarded as the
``x-api-key`` header as documented by Semantic Scholar.

A client is injectable so the request is mockable under respx without touching
the network.
"""

from __future__ import annotations

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

_API = "https://api.semanticscholar.org/graph/v1/paper/search"
_HEADERS = {"User-Agent": "Lighthouse/0.1"}
_FIELDS = "title,abstract,year,citationCount,url"
# Public Semantic Scholar Graph API host this adapter contacts; authorized
# because the user invoked the Semantic Scholar source. Mirrors allowed_domains
# in the semantic_scholar skill manifest so the skill rail and adapter agree.
_ALLOWED_HOSTS = frozenset({"api.semanticscholar.org"})


def _parse(data: dict) -> list[Document]:
    out: list[Document] = []
    for item in data.get("data", []):
        title = (item.get("title") or "").strip()
        if not title:
            continue
        abstract = " ".join((item.get("abstract") or "").split())
        paper_id = item.get("paperId") or ""
        url = item.get("url") or (
            f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else ""
        )
        year = item.get("year")
        published_date = str(year) if year else ""
        out.append(Document(
            id=f"s2:{paper_id}" if paper_id else f"s2:{title[:40]}",
            text=f"{title}. {abstract}" if abstract else title,
            metadata={
                "source": "semantic_scholar",
                "url": url,
                "grade": "A",
                "published_date": published_date,
                "title": title,
                "citation_count": item.get("citationCount", 0),
            },
        ))
    return out


def search_semantic_scholar(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Search Semantic Scholar and return up to ``max_results`` papers as Documents.

    Pass ``client`` to reuse a connection (and to make the request mockable in
    tests); otherwise a temporary client is opened and closed for this call.

    Pass ``api_key`` to authenticate with an S2 API key (x-api-key header).
    Without a key the API enforces ~1 req/s; the caller must pace accordingly.
    """
    headers = dict(_HEADERS)
    if api_key:
        headers["x-api-key"] = api_key

    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        r = guarded_get(
            _API,
            allowed_domains=_ALLOWED_HOSTS,
            headers=headers,
            params={"query": query, "limit": max_results, "fields": _FIELDS},
            client=client,
        )
        r.raise_for_status()
        return _parse(r.json())
    finally:
        if owns_client:
            client.close()
