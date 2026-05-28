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

from ..rag.chunker import Document

DEFAULT_URL = "http://localhost:8888"
DEFAULT_TIMEOUT = 10.0

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
    """Return the SearXNG base URL.

    Resolution order:
    1. ``LIGHTHOUSE_SEARXNG_URL`` environment variable (highest priority, good
       for CI / container overrides).
    2. ``searxng_url`` key in the ``[sources]`` section of config.toml (user
       config, set once and forget).
    3. The compiled-in ``DEFAULT_URL`` (``http://localhost:8888``).
    """
    env_val = os.environ.get("LIGHTHOUSE_SEARXNG_URL")
    if env_val:
        return env_val
    # Try config.toml [sources] section
    try:
        from ..paths import Paths
        cfg_path = Paths.default().config_file
        if cfg_path.exists():
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib  # type: ignore[no-redef]
            with cfg_path.open("rb") as fh:
                cfg = tomllib.load(fh)
            url = cfg.get("sources", {}).get("searxng_url")
            if url:
                return str(url)
    except Exception:
        pass
    return DEFAULT_URL


def available(url: str | None = None) -> bool:
    """True if SearXNG is reachable at the configured URL."""
    base = url or _searxng_url()
    try:
        r = httpx.get(f"{base}/healthz", timeout=2.0)
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
) -> list[SearxResult]:
    """Search SearXNG and return results.

    Args:
        query: The search query.
        max_results: Maximum number of results to return.
        scholarly: If True, filter to scholarly domains only.
        categories: SearXNG category string (e.g. "general", "science").
        url: Override the default SearXNG URL.
        timeout: HTTP timeout in seconds.

    Returns:
        List of SearxResult objects, empty list if SearXNG is unavailable.

    Raises:
        SearXNGUnavailable: If SearXNG returns an error response.
    """
    base = url or _searxng_url()
    params = {
        "q": query,
        "format": "json",
        "categories": categories,
        "pageno": 1,
    }
    try:
        resp = httpx.get(f"{base}/search", params=params, timeout=timeout)
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
