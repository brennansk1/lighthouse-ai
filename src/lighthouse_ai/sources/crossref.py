"""Crossref source adapter — query the public Crossref works API (JSON), no auth.

Crossref indexes DOI-registered scholarly works across publishers. Records that
carry a peer-reviewed type (journal-article, proceedings-article, book-chapter)
are graded "A"; everything else (preprints, datasets, reports, components) is
graded "B" so downstream ranking can prefer reviewed sources.

Crossref abstracts, when present, are embedded as JATS XML inside the ``abstract``
string, so we strip the tags to recover plain prose. A client is injectable so
the request is mockable under respx without touching the network.
"""

from __future__ import annotations

import re

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

_API = "https://api.crossref.org/works"
_HEADERS = {"User-Agent": "Lighthouse/0.1 (mailto:research@lighthouse.local)"}
# Public Crossref API host this adapter contacts; authorized because the user
# invoked the Crossref source. Mirrors allowed_domains in the crossref skill
# manifest so the skill rail and the adapter agree.
_ALLOWED_HOSTS = frozenset({"api.crossref.org"})

# Types we consider peer-reviewed for grading purposes.
_GRADE_A_TYPES = {"journal-article", "proceedings-article", "book-chapter"}

_TAG = re.compile(r"<[^>]+>")


def _strip_jats(abstract: str | None) -> str:
    """Remove JATS XML tags from a Crossref abstract and normalise whitespace.

    Crossref does not give a parsed abstract, only a JATS-tagged string (e.g.
    ``<jats:p>...</jats:p>``); stripping tags is sufficient for ingestion since
    the chunker only needs prose, not structure.
    """
    if not abstract:
        return ""
    return " ".join(_TAG.sub(" ", abstract).split())


def _first_str(values: list | None) -> str:
    """Crossref returns ``title``/``container-title`` as arrays; take the first."""
    if not values:
        return ""
    return " ".join(str(values[0]).split())


def _published_date(item: dict) -> str:
    """Build an ISO-ish date from Crossref's date-parts structure.

    Crossref encodes dates as ``{"date-parts": [[year, month, day]]}`` with
    trailing parts optional, so we join whatever components are present.
    """
    for key in ("published", "published-print", "published-online", "issued"):
        block = item.get(key) or {}
        parts = (block.get("date-parts") or [[]])[0]
        if parts:
            return "-".join(str(p) for p in parts)
    return ""


def _parse(data: dict) -> list[Document]:
    items = (data.get("message") or {}).get("items", [])
    out: list[Document] = []
    for item in items:
        title = _first_str(item.get("title"))
        if not title:
            continue
        abstract = _strip_jats(item.get("abstract"))
        doi = item.get("DOI") or ""
        url = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
        grade = "A" if item.get("type") in _GRADE_A_TYPES else "B"
        out.append(Document(
            id=f"crossref:{doi}" if doi else f"crossref:{title[:40]}",
            text=f"{title}. {abstract}" if abstract else title,
            metadata={"source": "crossref", "url": url, "grade": grade,
                      "published_date": _published_date(item), "title": title},
        ))
    return out


def search_crossref(query: str, *, max_results: int = 5,
                    client: httpx.Client | None = None,
                    timeout: float = 30.0) -> list[Document]:
    """Search Crossref works and return up to ``max_results`` Documents.

    Pass ``client`` to reuse a connection (and to make the request mockable in
    tests); otherwise a temporary client is opened and closed for this call.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        r = guarded_get(_API, allowed_domains=_ALLOWED_HOSTS,
                        headers=_HEADERS, client=client, params={
            "query": query, "rows": max_results})
        r.raise_for_status()
        return _parse(r.json())
    finally:
        if owns_client:
            client.close()
