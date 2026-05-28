"""PubMed source adapter — query NCBI E-utilities (esearch + efetch), no auth.

PubMed is the authoritative index for biomedical literature, so its records are
graded "A". The E-utilities API is two-step: ``esearch`` resolves a free-text
query to a list of PMIDs, then ``efetch`` returns the full article records as
XML (which is the only E-utilities endpoint that reliably carries the abstract
body — ``esummary`` omits it). We parse the efetch XML to assemble each
Document's title + abstract text.

A client is injectable so the two HTTP calls can be exercised together under
respx in tests without real network access; when omitted we open and close our
own short-lived :class:`httpx.Client`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from ..rag.chunker import Document

_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_HEADERS = {"User-Agent": "Lighthouse/0.1"}


def _parse_pmids(payload: bytes) -> list[str]:
    """Extract PMIDs from an esearch XML response.

    Returning ``[]`` on a parse error (rather than raising) keeps a malformed
    search response from aborting the pipeline — the caller simply gets no hits.
    """
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []
    return [el.text.strip() for el in root.findall(".//IdList/Id")
            if el.text and el.text.strip()]


def _abstract_text(article: ET.Element) -> str:
    """Join all AbstractText nodes.

    Structured abstracts split the body across multiple labelled
    ``<AbstractText Label="...">`` elements, so we concatenate them (prefixing
    the label when present) to reconstruct the full abstract.
    """
    parts: list[str] = []
    for node in article.findall(".//Abstract/AbstractText"):
        text = " ".join((node.text or "").split())
        if not text:
            continue
        label = node.get("Label")
        parts.append(f"{label}: {text}" if label else text)
    return " ".join(parts)


def _parse_articles(payload: bytes) -> list[Document]:
    """Turn an efetch PubmedArticleSet XML body into Documents."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []
    out: list[Document] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = (article.findtext(".//PMID") or "").strip()
        title = " ".join((article.findtext(".//ArticleTitle") or "").split())
        if not title:
            continue
        abstract = _abstract_text(article)
        # PubMed splits the publication date into Year/Month/Day children.
        date_el = article.find(".//PubDate")
        published = ""
        if date_el is not None:
            year = (date_el.findtext("Year") or "").strip()
            month = (date_el.findtext("Month") or "").strip()
            day = (date_el.findtext("Day") or "").strip()
            published = "-".join(p for p in (year, month, day) if p)
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
        out.append(Document(
            id=f"pubmed:{pmid}" if pmid else f"pubmed:{title[:40]}",
            text=f"{title}. {abstract}" if abstract else title,
            metadata={"source": "pubmed", "url": url, "grade": "A",
                      "published_date": published, "title": title},
        ))
    return out


def search_pubmed(query: str, *, max_results: int = 5,
                  client: httpx.Client | None = None,
                  timeout: float = 30.0) -> list[Document]:
    """Search PubMed and return up to ``max_results`` articles as Documents.

    Pass ``client`` to reuse a connection (and to make both the esearch and
    efetch calls mockable in tests); otherwise a temporary client is used.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        search = client.get(_ESEARCH, headers=_HEADERS, params={
            "db": "pubmed", "term": query, "retmax": max_results,
            "retmode": "xml", "sort": "relevance"})
        search.raise_for_status()
        pmids = _parse_pmids(search.content)
        if not pmids:
            return []
        fetch = client.get(_EFETCH, headers=_HEADERS, params={
            "db": "pubmed", "id": ",".join(pmids), "retmode": "xml",
            "rettype": "abstract"})
        fetch.raise_for_status()
        return _parse_articles(fetch.content)
    finally:
        if owns_client:
            client.close()
