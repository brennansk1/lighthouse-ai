"""Source adapters — turn external feeds/APIs into items or Documents."""

from .arxiv import search_arxiv
from .crossref import search_crossref
from .openalex import search_openalex
from .pubmed import search_pubmed
from .rss import fetch_feed, parse_feed_bytes
from .searxng import search_as_documents as searxng_search_as_documents

__all__ = [
    "fetch_feed",
    "parse_feed_bytes",
    "search_arxiv",
    "search_crossref",
    "search_openalex",
    "search_pubmed",
    "searxng_search_as_documents",
]
