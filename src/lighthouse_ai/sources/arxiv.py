"""arXiv source adapter — query the public arXiv API (Atom), no auth.

Returns :class:`lighthouse_ai.rag.chunker.Document` objects (title + abstract)
ready to ingest into the research corpus. Respect arXiv's 3-second rate limit
when calling in a loop (the caller paces; we do one request per search).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

_API = "https://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom"}
# Public arXiv API hosts this adapter contacts; authorized because the user
# invoked the arXiv source. Mirrors allowed_domains in the arxiv skill manifest
# so the skill rail and the adapter agree.
_ALLOWED_HOSTS = frozenset({"export.arxiv.org", "arxiv.org"})


def _parse(payload: bytes) -> list[Document]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []
    out: list[Document] = []
    for entry in root.findall("atom:entry", _NS):
        arxiv_id = (entry.findtext("atom:id", default="", namespaces=_NS) or "").strip()
        title = " ".join((entry.findtext("atom:title", default="", namespaces=_NS) or "").split())
        summary = " ".join(
            (entry.findtext("atom:summary", default="", namespaces=_NS) or "").split()
        )
        published = entry.findtext("atom:published", default="", namespaces=_NS)
        if not title:
            continue
        out.append(
            Document(
                id=arxiv_id or f"arxiv:{title[:40]}",
                text=f"{title}. {summary}",
                metadata={
                    "source": "arxiv",
                    "url": arxiv_id,
                    "grade": "A",
                    "published_date": published,
                    "title": title,
                },
            )
        )
    return out


def search_arxiv(
    query: str, *, max_results: int = 5, client: httpx.Client | None = None, timeout: float = 30.0
) -> list[Document]:
    """Search arXiv and return up to ``max_results`` papers as Documents.

    Pass ``client`` to reuse a connection (and to make the request mockable in
    tests); otherwise a temporary client is used.
    """
    # Only a bare keyword query gets wrapped in ``all:``. A query that already
    # targets an arXiv field (cat:, au:, ti:, abs:, id:, …) is passed verbatim —
    # wrapping it ("all:cat:cs.LG …") makes arXiv reject the request with 400.
    _q = query.strip()
    _field_prefixes = ("all:", "cat:", "au:", "ti:", "abs:", "id:", "co:", "jr:", "rn:")
    _search_query = _q if _q.lower().startswith(_field_prefixes) else f"all:{query}"
    params: dict[str, str | int] = {
        "search_query": _search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        r = guarded_get(
            _API,
            allowed_domains=_ALLOWED_HOSTS,
            params=params,
            headers={"User-Agent": "Lighthouse/0.1"},
            client=client,
        )
        r.raise_for_status()
        return _parse(r.content)
    finally:
        if owns_client:
            client.close()
