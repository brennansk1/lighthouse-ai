"""Tests for the PubMed and Crossref specialty source adapters.

All HTTP is respx-mocked; no real network is touched. The PubMed adapter makes
two calls (esearch then efetch), so its fixtures provide both halves.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.sources.crossref import search_crossref
from lighthouse_ai.sources.pubmed import search_pubmed

# --- Fixtures: PubMed E-utilities ---

ESEARCH_XML = b"""<?xml version="1.0"?>
<eSearchResult>
  <Count>2</Count>
  <IdList>
    <Id>30000001</Id>
    <Id>30000002</Id>
  </IdList>
</eSearchResult>"""

ESEARCH_EMPTY_XML = b"""<?xml version="1.0"?>
<eSearchResult>
  <Count>0</Count>
  <IdList></IdList>
</eSearchResult>"""

EFETCH_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>30000001</PMID>
      <Article>
        <ArticleTitle>CRISPR gene editing in vivo</ArticleTitle>
        <Abstract>
          <AbstractText>We report a high-efficiency edit.</AbstractText>
        </Abstract>
        <Journal>
          <JournalIssue>
            <PubDate>
              <Year>2025</Year>
              <Month>03</Month>
              <Day>14</Day>
            </PubDate>
          </JournalIssue>
        </Journal>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>30000002</PMID>
      <Article>
        <ArticleTitle>Structured abstract study</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Context here.</AbstractText>
          <AbstractText Label="RESULTS">Findings here.</AbstractText>
        </Abstract>
        <Journal>
          <JournalIssue>
            <PubDate>
              <Year>2024</Year>
            </PubDate>
          </JournalIssue>
        </Journal>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>"""

# An article with no title should be skipped.
EFETCH_NOTITLE_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>40000001</PMID>
      <Article>
        <Abstract><AbstractText>Orphan abstract.</AbstractText></Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>"""

# --- Fixtures: Crossref ---

CROSSREF_JSON = {
    "message": {
        "items": [
            {
                "DOI": "10.1000/abc",
                "URL": "https://doi.org/10.1000/abc",
                "type": "journal-article",
                "title": ["Deep learning for protein folding"],
                "abstract": "<jats:p>We <jats:bold>predict</jats:bold> structures.</jats:p>",
                "published": {"date-parts": [[2023, 6, 1]]},
            },
            {
                "DOI": "10.1000/xyz",
                "type": "posted-content",
                "title": ["A preprint on quantum noise"],
                "issued": {"date-parts": [[2026]]},
            },
        ]
    }
}

CROSSREF_EMPTY_JSON = {"message": {"items": []}}

CROSSREF_NOTITLE_JSON = {"message": {"items": [{"DOI": "10.1/n", "type": "journal-article"}]}}


@pytest.fixture
def mocked_http():
    with respx.mock(assert_all_called=False) as m:
        yield m


def _pubmed_ok(m, *, search=ESEARCH_XML, fetch=EFETCH_XML):
    m.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(
        200, content=search, headers={"content-type": "text/xml"}
    )
    m.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi").respond(
        200, content=fetch, headers={"content-type": "text/xml"}
    )


def _crossref_ok(m, payload=CROSSREF_JSON):
    m.get("https://api.crossref.org/works").respond(200, json=payload)


# --- PubMed ---


def test_pubmed_returns_documents(mocked_http):
    _pubmed_ok(mocked_http)
    docs = search_pubmed("crispr")
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)


def test_pubmed_title_and_abstract_in_text(mocked_http):
    _pubmed_ok(mocked_http)
    docs = search_pubmed("crispr")
    assert docs[0].text == "CRISPR gene editing in vivo. We report a high-efficiency edit."


def test_pubmed_structured_abstract_joined_with_labels(mocked_http):
    _pubmed_ok(mocked_http)
    docs = search_pubmed("crispr")
    assert "BACKGROUND: Context here." in docs[1].text
    assert "RESULTS: Findings here." in docs[1].text


def test_pubmed_metadata_grade_and_source(mocked_http):
    _pubmed_ok(mocked_http)
    doc = search_pubmed("crispr")[0]
    assert doc.metadata["source"] == "pubmed"
    assert doc.metadata["grade"] == "A"
    assert doc.metadata["title"] == "CRISPR gene editing in vivo"


def test_pubmed_metadata_url_and_id(mocked_http):
    _pubmed_ok(mocked_http)
    doc = search_pubmed("crispr")[0]
    assert doc.metadata["url"] == "https://pubmed.ncbi.nlm.nih.gov/30000001/"
    assert doc.id == "pubmed:30000001"


def test_pubmed_published_date_full(mocked_http):
    _pubmed_ok(mocked_http)
    doc = search_pubmed("crispr")[0]
    assert doc.metadata["published_date"] == "2025-03-14"


def test_pubmed_published_date_year_only(mocked_http):
    _pubmed_ok(mocked_http)
    doc = search_pubmed("crispr")[1]
    assert doc.metadata["published_date"] == "2024"


def test_pubmed_respects_max_results_param(mocked_http):
    route = mocked_http.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(
        200, content=ESEARCH_XML
    )
    mocked_http.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi").respond(
        200, content=EFETCH_XML
    )
    search_pubmed("crispr", max_results=3)
    assert route.calls.last.request.url.params["retmax"] == "3"


def test_pubmed_empty_search_skips_efetch(mocked_http):
    mocked_http.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(
        200, content=ESEARCH_EMPTY_XML
    )
    fetch_route = mocked_http.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    ).respond(200, content=EFETCH_XML)
    docs = search_pubmed("nothing")
    assert docs == []
    assert not fetch_route.called


def test_pubmed_skips_articles_without_title(mocked_http):
    _pubmed_ok(mocked_http, fetch=EFETCH_NOTITLE_XML)
    assert search_pubmed("x") == []


def test_pubmed_malformed_efetch_returns_empty(mocked_http):
    _pubmed_ok(mocked_http, fetch=b"<not valid &")
    assert search_pubmed("x") == []


def test_pubmed_raises_on_esearch_http_error(mocked_http):
    mocked_http.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        search_pubmed("x")


def test_pubmed_raises_on_efetch_http_error(mocked_http):
    mocked_http.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(
        200, content=ESEARCH_XML
    )
    mocked_http.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi").respond(404)
    with pytest.raises(httpx.HTTPStatusError):
        search_pubmed("x")


def test_pubmed_uses_injected_client(mocked_http):
    _pubmed_ok(mocked_http)
    with httpx.Client() as client:
        docs = search_pubmed("crispr", client=client)
        assert len(docs) == 2
        # Injected client must remain usable (adapter must not close it).
        assert not client.is_closed


# --- Crossref ---


def test_crossref_returns_documents(mocked_http):
    _crossref_ok(mocked_http)
    docs = search_crossref("protein")
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)


def test_crossref_strips_jats_tags(mocked_http):
    _crossref_ok(mocked_http)
    doc = search_crossref("protein")[0]
    assert doc.text == "Deep learning for protein folding. We predict structures."
    assert "<jats" not in doc.text


def test_crossref_grade_a_for_journal_article(mocked_http):
    _crossref_ok(mocked_http)
    assert search_crossref("protein")[0].metadata["grade"] == "A"


def test_crossref_grade_b_for_preprint(mocked_http):
    _crossref_ok(mocked_http)
    assert search_crossref("protein")[1].metadata["grade"] == "B"


def test_crossref_metadata_source_url_id(mocked_http):
    _crossref_ok(mocked_http)
    doc = search_crossref("protein")[0]
    assert doc.metadata["source"] == "crossref"
    assert doc.metadata["url"] == "https://doi.org/10.1000/abc"
    assert doc.id == "crossref:10.1000/abc"


def test_crossref_published_date(mocked_http):
    _crossref_ok(mocked_http)
    assert search_crossref("protein")[0].metadata["published_date"] == "2023-6-1"


def test_crossref_issued_fallback_date(mocked_http):
    _crossref_ok(mocked_http)
    assert search_crossref("protein")[1].metadata["published_date"] == "2026"


def test_crossref_text_without_abstract_is_title_only(mocked_http):
    _crossref_ok(mocked_http)
    assert search_crossref("protein")[1].text == "A preprint on quantum noise"


def test_crossref_empty_results(mocked_http):
    _crossref_ok(mocked_http, CROSSREF_EMPTY_JSON)
    assert search_crossref("nothing") == []


def test_crossref_skips_items_without_title(mocked_http):
    _crossref_ok(mocked_http, CROSSREF_NOTITLE_JSON)
    assert search_crossref("x") == []


def test_crossref_respects_max_results(mocked_http):
    route = _crossref_ok_route = mocked_http.get("https://api.crossref.org/works").respond(
        200, json=CROSSREF_JSON
    )
    search_crossref("protein", max_results=7)
    assert route.calls.last.request.url.params["rows"] == "7"


def test_crossref_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.crossref.org/works").respond(503)
    with pytest.raises(httpx.HTTPStatusError):
        search_crossref("x")


def test_crossref_uses_injected_client(mocked_http):
    _crossref_ok(mocked_http)
    with httpx.Client() as client:
        docs = search_crossref("protein", client=client)
        assert len(docs) == 2
        assert not client.is_closed
