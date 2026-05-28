"""OpenAlex source adapter — query the public OpenAlex works API (JSON), no auth.

Returns :class:`Document` objects (title + reconstructed abstract). OpenAlex
stores abstracts as an inverted index; we reconstruct the text.
"""

from __future__ import annotations

import httpx

from ..rag.chunker import Document

_API = "https://api.openalex.org/works"


def _reconstruct_abstract(inv: dict | None) -> str:
    """OpenAlex gives abstract_inverted_index {word: [positions]} — rebuild it."""
    if not inv:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _i, w in positions)


def _parse(data: object) -> list[Document]:
    if not isinstance(data, dict):
        return []
    out: list[Document] = []
    for w in data.get("results", []):
        title = (w.get("title") or "").strip()
        if not title:
            continue
        abstract = _reconstruct_abstract(w.get("abstract_inverted_index"))
        out.append(Document(
            id=w.get("id", f"openalex:{title[:40]}"),
            text=f"{title}. {abstract}",
            metadata={"source": "openalex", "url": w.get("id"), "grade": "A",
                      "published_date": w.get("publication_date"),
                      "cited_by": w.get("cited_by_count", 0), "title": title},
        ))
    return out


def search_openalex(query: str, *, max_results: int = 5,
                    timeout: float = 30.0, mailto: str | None = None) -> list[Document]:
    """Search OpenAlex works. ``mailto`` joins the polite pool (recommended)."""
    params = {"search": query, "per_page": max_results,
              "sort": "relevance_score:desc"}
    if mailto:
        params["mailto"] = mailto
    with httpx.Client(timeout=timeout) as c:
        r = c.get(_API, params=params, headers={"User-Agent": "Lighthouse/0.1"})
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError:
        return []
    return _parse(data)
