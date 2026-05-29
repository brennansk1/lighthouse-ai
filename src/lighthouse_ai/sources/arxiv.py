"""arXiv source adapter — query the public arXiv API (Atom), no auth.

Returns :class:`lighthouse_ai.rag.chunker.Document` objects (title + abstract)
ready to ingest into the research corpus. Respect arXiv's 3-second rate limit
when calling in a loop (the caller paces; we do one request per search).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from ..rag.chunker import Document

_API = "https://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _parse(payload: bytes) -> list[Document]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []
    out: list[Document] = []
    for entry in root.findall("atom:entry", _NS):
        arxiv_id = (entry.findtext("atom:id", default="", namespaces=_NS) or "").strip()
        title = " ".join((entry.findtext("atom:title", default="", namespaces=_NS)
                          or "").split())
        summary = " ".join((entry.findtext("atom:summary", default="", namespaces=_NS)
                            or "").split())
        published = entry.findtext("atom:published", default="", namespaces=_NS)
        if not title:
            continue
        out.append(Document(
            id=arxiv_id or f"arxiv:{title[:40]}",
            text=f"{title}. {summary}",
            metadata={"source": "arxiv", "url": arxiv_id, "grade": "A",
                      "published_date": published, "title": title},
        ))
    return out


def search_arxiv(query: str, *, max_results: int = 5,
                 timeout: float = 30.0) -> list[Document]:
    """Search arXiv and return up to ``max_results`` papers as Documents."""
    params = {"search_query": f"all:{query}", "start": 0,
              "max_results": max_results,
              "sortBy": "relevance", "sortOrder": "descending"}
    with httpx.Client(timeout=timeout, follow_redirects=True) as c:
        r = c.get(_API, params=params, headers={"User-Agent": "Lighthouse/0.1"})
    r.raise_for_status()
    return _parse(r.content)
