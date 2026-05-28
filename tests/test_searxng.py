"""Tests for the SearXNG source adapter."""
from __future__ import annotations

import httpx
import pytest
import respx

from lighthouse_ai.sources.searxng import (
    SCHOLARLY_DOMAINS,
    SearXNGUnavailable,
    _searxng_url,
    available,
    search,
    search_as_documents,
)

MOCK_RESPONSE = {
    "results": [
        {
            "url": "https://arxiv.org/abs/2401.00001",
            "title": "Quantum Computing Overview",
            "content": "An overview of quantum computing fundamentals.",
            "engine": "arxiv",
            "score": 0.9,
        },
        {
            "url": "https://example-blog.com/post",
            "title": "Blog Post",
            "content": "A blog post about quantum computers.",
            "engine": "google",
            "score": 0.5,
        },
    ]
}


@respx.mock
def test_search_returns_results():
    respx.get("http://localhost:8888/search").mock(
        return_value=httpx.Response(200, json=MOCK_RESPONSE)
    )
    results = search("quantum computing", max_results=5)
    assert len(results) == 2
    assert results[0].url == "https://arxiv.org/abs/2401.00001"
    assert results[0].title == "Quantum Computing Overview"


@respx.mock
def test_search_scholarly_filters_non_academic():
    respx.get("http://localhost:8888/search").mock(
        return_value=httpx.Response(200, json=MOCK_RESPONSE)
    )
    results = search("quantum computing", max_results=5, scholarly=True)
    # Only the arxiv.org result should pass the scholarly filter
    assert len(results) == 1
    assert "arxiv.org" in results[0].url


@respx.mock
def test_search_raises_on_http_error():
    respx.get("http://localhost:8888/search").mock(
        return_value=httpx.Response(500)
    )
    with pytest.raises(SearXNGUnavailable):
        search("test")


def test_search_raises_on_connection_error():
    # No mock → ConnectError expected for the default localhost:8888
    with pytest.raises(SearXNGUnavailable):
        search("test", url="http://127.0.0.1:19999")  # nothing on this port


@respx.mock
def test_search_as_documents_returns_documents():
    respx.get("http://localhost:8888/search").mock(
        return_value=httpx.Response(200, json=MOCK_RESPONSE)
    )
    docs = search_as_documents("quantum computing", max_results=5)
    assert len(docs) >= 1
    assert docs[0].metadata["source"] == "searxng"
    assert "Quantum" in docs[0].text


def test_search_as_documents_empty_on_unavailable():
    """search_as_documents never raises — returns [] when SearXNG is down."""
    docs = search_as_documents("test", url="http://127.0.0.1:19999")
    assert docs == []


@respx.mock
def test_available_true_on_200():
    respx.get("http://localhost:8888/healthz").mock(
        return_value=httpx.Response(200)
    )
    assert available() is True


def test_available_false_on_connection_error():
    assert available("http://127.0.0.1:19999") is False


def test_scholarly_domains_includes_expected():
    assert "arxiv.org" in SCHOLARLY_DOMAINS
    assert "pubmed.ncbi.nlm.nih.gov" in SCHOLARLY_DOMAINS
    assert "semanticscholar.org" in SCHOLARLY_DOMAINS


def test_searxng_url_default():
    assert "localhost" in _searxng_url() or "8888" in _searxng_url()


def test_search_respects_max_results():
    big_response = {
        "results": [
            {
                "url": f"https://arxiv.org/abs/24{i:05d}",
                "title": f"Paper {i}",
                "content": f"Content {i}",
                "engine": "arxiv",
                "score": 0.9,
            }
            for i in range(20)
        ]
    }
    with respx.mock:
        respx.get("http://localhost:8888/search").mock(
            return_value=httpx.Response(200, json=big_response)
        )
        results = search("quantum", max_results=3)
    assert len(results) == 3


# --- Robustness & metadata (production-quality sweep) ---


@respx.mock
def test_search_extracts_published_date():
    resp = {
        "results": [
            {
                "url": "https://arxiv.org/abs/2401.00001",
                "title": "Dated Paper",
                "content": "Some content.",
                "engine": "arxiv",
                "score": 0.9,
                "publishedDate": "2024-01-15T00:00:00",
            }
        ]
    }
    respx.get("http://localhost:8888/search").mock(
        return_value=httpx.Response(200, json=resp)
    )
    results = search("quantum", max_results=5)
    assert results[0].published_date == "2024-01-15T00:00:00"


@respx.mock
def test_search_non_numeric_score_does_not_crash():
    resp = {
        "results": [
            {
                "url": "https://arxiv.org/abs/2401.00002",
                "title": "Weird Score",
                "content": "Content.",
                "engine": "x",
                "score": "not-a-number",
            }
        ]
    }
    respx.get("http://localhost:8888/search").mock(
        return_value=httpx.Response(200, json=resp)
    )
    results = search("quantum", max_results=5)
    assert results[0].score == 0.0


@respx.mock
def test_search_non_json_body_raises_unavailable():
    respx.get("http://localhost:8888/search").mock(
        return_value=httpx.Response(200, text="<html>json not enabled</html>")
    )
    with pytest.raises(SearXNGUnavailable):
        search("quantum", max_results=5)


@respx.mock
def test_search_as_documents_deterministic_id():
    resp = {
        "results": [
            {
                "url": "https://arxiv.org/abs/2401.00003",
                "title": "Stable",
                "content": "Body text.",
                "engine": "arxiv",
                "score": 0.9,
            }
        ]
    }
    respx.get("http://localhost:8888/search").mock(
        return_value=httpx.Response(200, json=resp)
    )
    docs1 = search_as_documents("quantum", max_results=5)
    with respx.mock:
        respx.get("http://localhost:8888/search").mock(
            return_value=httpx.Response(200, json=resp)
        )
        docs2 = search_as_documents("quantum", max_results=5)
    # Same URL must yield the same id across calls (process-independent).
    assert docs1[0].id == docs2[0].id
    assert docs1[0].id.startswith("searxng:")
