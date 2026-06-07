"""SEC EDGAR source adapter — query the EDGAR full-text search API (JSON).

Uses the EDGAR EFTS (Electronic Full-Text Search) REST endpoint at
``efts.sec.gov``. This is the same engine that powers the EDGAR search UI at
https://efts.sec.gov/LATEST/search-index and requires no API key; it is
documented informally by the SEC but is a stable, public interface.

**User-Agent requirement**: SEC EDGAR's fair-use policy requires every automated
request to include a descriptive ``User-Agent`` header with a contact address so
that the SEC can reach you if your traffic is causing problems. Requests without
a meaningful User-Agent may be rate-limited or blocked. See:
https://www.sec.gov/os/accessing-edgar-data

The adapter sets ``User-Agent: Lighthouse/0.1 (mailto:research@lighthouse.local)``
by default.  Callers may override this by passing a custom client configured with
appropriate headers.

Records are graded "B" because EDGAR filings are primary-source documents
(10-K, 10-Q, 8-K, S-1, etc.) that have not been independently peer-reviewed.
"""

from __future__ import annotations

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

_API = "https://efts.sec.gov/LATEST/search-index"
_HEADERS = {
    "User-Agent": "Lighthouse/0.1 (mailto:research@lighthouse.local)",
    "Accept": "application/json",
}
# Public SEC EDGAR hosts this adapter contacts; authorized because the user
# invoked the SEC EDGAR source. The full-text search API lives on the
# ``efts.sec.gov`` subdomain, which matches the allowlisted ``sec.gov`` via the
# egress guard's subdomain rule. Mirrors allowed_domains in the sec_edgar skill
# manifest so the skill rail and the adapter agree.
_ALLOWED_HOSTS = frozenset({"sec.gov", "www.sec.gov"})


def _parse(data: dict) -> list[Document]:
    out: list[Document] = []
    hits = (data.get("hits") or {}).get("hits", [])
    for hit in hits:
        src = hit.get("_source") or {}
        file_date = src.get("file_date") or ""
        entity_name = src.get("entity_name") or ""
        form_type = src.get("form_type") or ""
        display_names = src.get("display_names") or []
        # Build a human-readable title from available fields.
        if entity_name and form_type:
            title = f"{entity_name} — {form_type}"
        elif entity_name:
            title = entity_name
        elif form_type:
            title = form_type
        else:
            title = hit.get("_id", "")
        if not title:
            continue
        # The EDGAR filing URL is assembled from the accession number.
        accession = src.get("accession_no") or hit.get("_id") or ""
        # Accession numbers look like "0001234567-24-000001"; the filing index
        # page uses the accession number without dashes.
        if accession:
            acc_nodash = accession.replace("-", "")
            cik = str(src.get("cik") or "").zfill(10)
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"
            )
        else:
            url = ""
        # Snippet text from full-text search results.
        highlights = hit.get("highlight") or {}
        snippet_parts = highlights.get("file_text", []) or []
        snippet = " … ".join(snippet_parts)
        text = f"{title}. {snippet}" if snippet else title
        out.append(Document(
            id=f"sec:{accession}" if accession else f"sec:{title[:40]}",
            text=text,
            metadata={
                "source": "sec_edgar",
                "url": url,
                "grade": "B",
                "published_date": file_date,
                "title": title,
                "form_type": form_type,
                "entity_name": entity_name,
                "display_names": display_names,
            },
        ))
    return out


def search_sec_edgar(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Search SEC EDGAR full-text and return up to ``max_results`` filings as Documents.

    Pass ``client`` to reuse a connection (and to make the request mockable in
    tests); otherwise a temporary client is opened and closed for this call.

    **User-Agent**: SEC requires a descriptive User-Agent (see module docstring).
    If you pass a custom ``client`` ensure it is configured with an appropriate
    User-Agent or the request may be blocked.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        r = guarded_get(
            _API,
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params={"q": query, "dateRange": "custom", "_source": "true",
                    "from": 0, "hits.hits.total.value": max_results,
                    "hits.hits._source": "true",
                    "hits.hits.highlight": "true",
                    "category": "form-type"},
            client=client,
        )
        r.raise_for_status()
        return _parse(r.json())
    finally:
        if owns_client:
            client.close()
