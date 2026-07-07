"""OpenAlex source adapter — query the public OpenAlex works API (JSON), no auth.

Returns :class:`Document` objects (title + reconstructed abstract). OpenAlex
stores abstracts as an inverted index; we reconstruct the text.
"""

from __future__ import annotations

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

_API = "https://api.openalex.org/works"
# Public OpenAlex hosts this adapter contacts; authorized because the user
# invoked the OpenAlex source. Mirrors allowed_domains in the openalex skill
# manifest so the skill rail and the adapter agree.
_ALLOWED_HOSTS = frozenset({"api.openalex.org", "openalex.org"})


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


def _parse(data: dict) -> list[Document]:
    out: list[Document] = []
    for w in data.get("results", []):
        title = (w.get("title") or "").strip()
        if not title:
            continue
        abstract = _reconstruct_abstract(w.get("abstract_inverted_index"))
        out.append(
            Document(
                id=w.get("id", f"openalex:{title[:40]}"),
                text=f"{title}. {abstract}",
                metadata={
                    "source": "openalex",
                    "url": w.get("id"),
                    "grade": "A",
                    "published_date": w.get("publication_date"),
                    "cited_by": w.get("cited_by_count", 0),
                    "title": title,
                },
            )
        )
    return out


def search_openalex(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    mailto: str | None = None,
) -> list[Document]:
    """Search OpenAlex works. ``mailto`` joins the polite pool (recommended).

    Pass ``client`` to reuse a connection (and to make the call mockable in
    tests); otherwise a temporary client is used.
    """
    params: dict[str, str | int] = {
        "search": query,
        "per_page": max_results,
        "sort": "relevance_score:desc",
    }
    if mailto:
        params["mailto"] = mailto
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        r = guarded_get(
            _API,
            allowed_domains=_ALLOWED_HOSTS,
            params=params,
            headers={"User-Agent": "Lighthouse/0.1"},
            client=client,
        )
        r.raise_for_status()
        return _parse(r.json())
    finally:
        if owns_client:
            client.close()
