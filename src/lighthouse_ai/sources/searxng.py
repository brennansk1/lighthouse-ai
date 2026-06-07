"""SearXNG meta-search client for mid-loop web retrieval (Sprint 31 CRAG seam).

SearXNG (https://github.com/searxng/searxng) is a self-hosted meta-search engine
that federates across Google/Bing/DuckDuckGo/arXiv/PubMed/Semantic Scholar etc.
Run it via the Docker Compose stack: make stack-up

The default endpoint is http://localhost:8888 (configurable via
LIGHTHOUSE_SEARXNG_URL env var). JSON format must be enabled in SearXNG settings
(the docker-compose stack sets SEARXNG_SEARCH_FORMATS=html,json).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

DEFAULT_URL = "http://localhost:8888"
DEFAULT_TIMEOUT = 10.0

# SearXNG is a self-hosted meta-search service the user runs locally (the
# docker-compose stack binds it to localhost:8888). These loopback hosts are the
# only endpoints this adapter contacts, so they are the authorized egress hosts
# routed through the guard.
_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1"})

# Source quality filter: only keep results from these domains when
# scholarly=True is set. Extend this list as needed.
SCHOLARLY_DOMAINS = {
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "semanticscholar.org",
    "openalex.org",
    "crossref.org",
    "nature.com",
    "science.org",
    "cell.com",
    "nejm.org",
    "jamanetwork.com",
    "bmj.com",
    "thelancet.com",
    "pnas.org",
    "royalsocietypublishing.org",
    "journals.plos.org",
    "biorxiv.org",
    "medrxiv.org",
    "ssrn.com",
    "acm.org",
    "ieee.org",
    "springer.com",
    "wiley.com",
    "elsevier.com",
}


@dataclass
class SearxResult:
    url: str
    title: str
    content: str
    engine: str = ""
    score: float = 0.0


class SearXNGUnavailable(RuntimeError):
    """Raised when SearXNG is not reachable at the configured URL."""


def _searxng_url() -> str:
    return os.environ.get("LIGHTHOUSE_SEARXNG_URL", DEFAULT_URL)


def available(
    url: str | None = None,
    *,
    client: httpx.Client | None = None,
) -> bool:
    """True if SearXNG is reachable at the configured URL."""
    base = url or _searxng_url()
    try:
        owns_client = client is None
        if client is None:
            client = httpx.Client(timeout=2.0)
        try:
            r = guarded_get(
                f"{base}/healthz",
                allowed_domains=_ALLOWED_HOSTS,
                client=client,
            )
        finally:
            if owns_client and client is not None:
                client.close()
        return r.status_code == 200
    except Exception:
        return False


def search(
    query: str,
    *,
    max_results: int = 10,
    scholarly: bool = False,
    categories: str = "general",
    url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    client: httpx.Client | None = None,
) -> list[SearxResult]:
    """Search SearXNG and return results.

    Args:
        query: The search query.
        max_results: Maximum number of results to return.
        scholarly: If True, filter to scholarly domains only.
        categories: SearXNG category string (e.g. "general", "science").
        url: Override the default SearXNG URL.
        timeout: HTTP timeout in seconds.
        client: Optional injected httpx client (shares pool / config); when
            omitted a throwaway client honoring ``timeout`` is constructed.

    Returns:
        List of SearxResult objects, empty list if SearXNG is unavailable.

    Raises:
        SearXNGUnavailable: If SearXNG returns an error response.
    """
    base = url or _searxng_url()
    params: dict[str, str | int] = {
        "q": query,
        "format": "json",
        "categories": categories,
        "pageno": 1,
    }
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            f"{base}/search",
            allowed_domains=_ALLOWED_HOSTS,
            params=params,
            client=client,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SearXNGUnavailable(
            f"SearXNG at {base} returned error: {exc}"
        ) from exc
    except httpx.ConnectError as exc:
        raise SearXNGUnavailable(f"SearXNG not reachable at {base}") from exc
    except httpx.HTTPError as exc:
        raise SearXNGUnavailable(
            f"SearXNG at {base} returned error: {exc}"
        ) from exc
    finally:
        if owns_client and client is not None:
            client.close()

    data = resp.json()
    results: list[SearxResult] = []
    for item in data.get("results", [])[: max_results * 2]:  # fetch extra for filtering
        url_str = item.get("url", "")
        if scholarly:
            domain = urlparse(url_str).netloc.removeprefix("www.")
            if not any(domain.endswith(d) for d in SCHOLARLY_DOMAINS):
                continue
        results.append(
            SearxResult(
                url=url_str,
                title=item.get("title", ""),
                content=item.get("content", ""),
                engine=item.get("engine", ""),
                score=float(item.get("score", 0.0)),
            )
        )
        if len(results) >= max_results:
            break
    return results


def search_as_documents(
    query: str,
    *,
    max_results: int = 5,
    scholarly: bool = False,
    url: str | None = None,
) -> list[Document]:
    """Search SearXNG and return results as Document objects for ingestion.

    Returns empty list if SearXNG is unavailable (never raises).
    """
    try:
        results = search(query, max_results=max_results, scholarly=scholarly, url=url)
    except SearXNGUnavailable:
        return []
    docs: list[Document] = []
    for r in results:
        if not r.content:
            continue
        doc_id = f"searxng:{hash(r.url) & 0xFFFFFFFF:08x}"
        docs.append(
            Document(
                id=doc_id,
                text=f"{r.title}\n\n{r.content}",
                metadata={
                    "source": "searxng",
                    "url": r.url,
                    "title": r.title,
                    "engine": r.engine,
                    "grade": "B",  # web results are grade B by default
                },
            )
        )
    return docs
