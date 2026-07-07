"""Consolidated egress-enforcement proof for the migrated source adapters (A2).

The migrated source adapters (``lighthouse_ai.sources.*``) must reach the network
*only* through the egress guard (:mod:`lighthouse_ai.net`), never via raw
``httpx``. Two properties together prove that:

  1. **It routes through the guard.** Calling an adapter with a mocked endpoint
     succeeds *and* writes a connection record to ``egress.jsonl`` — a side
     effect only :class:`EgressProxy.log_connection` produces. A raw ``httpx``
     call would fetch the same bytes but leave the audit log empty.

  2. **The kill switch is load-bearing.** With ``LIGHTHOUSE_AIRGAP=1`` the same
     call raises :class:`EgressBlocked` and the respx route is *never* called —
     the strongest available proxy for "zero sockets opened" without real I/O.

Both properties are asserted per-adapter for a representative sample: arxiv,
openalex, pubmed, sec_edgar, courtlistener, and searxng.

The adapters take ``allowed_domains`` (and build a throwaway proxy internally),
so to observe the audit log we replace each module's ``guarded_get`` with a thin
shim that routes the *same* call through an :class:`EgressGuardedClient` backed
by a real :class:`EgressProxy` writing to a temp ``egress.jsonl``. The shim adds
no policy of its own — it preserves the adapter's allowlist and injected client,
so the guard's real ``check`` → fetch → ``log_connection`` path (and its AIRGAP
short-circuit) is what actually runs. No test here performs real network I/O.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
import respx

from lighthouse_ai.governor.egress_proxy import EgressProxy
from lighthouse_ai.net import EgressBlocked, EgressGuardedClient
from lighthouse_ai.sources import (
    arxiv,
    courtlistener,
    openalex,
    pubmed,
    searxng,
    sec_edgar,
)


def _records(tmp_path: Path) -> list[dict]:
    """Parse the temp ``egress.jsonl`` audit log into records."""
    log = tmp_path / "egress.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def _install_logging_guard(monkeypatch: pytest.MonkeyPatch, module: object, tmp_path: Path) -> None:
    """Route ``module.guarded_get`` through a logging :class:`EgressProxy`.

    The replacement preserves the adapter's call shape exactly — it accepts the
    adapter's own ``allowed_domains`` and injected ``client`` — but threads the
    request through an :class:`EgressGuardedClient` whose proxy writes to a temp
    ``egress.jsonl``. This makes the guard's real decide-before-fetch + audit
    path observable without changing the policy the adapter declared.
    """

    def _shim(
        url: str,
        *,
        allowed_domains: frozenset[str] | set[str] | None = None,
        client: httpx.Client | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        proxy = EgressProxy(allowed_domains, log_path=tmp_path / "egress.jsonl")
        guard = EgressGuardedClient(proxy, client=client)
        try:
            return guard.request("GET", url, **kwargs)  # type: ignore[arg-type]
        finally:
            guard.close()

    monkeypatch.setattr(module, "guarded_get", _shim)


# Each entry: (module, callable that invokes the adapter with the injected client,
# respx routes to register, the host expected in the audit record).
def _call_arxiv(client: httpx.Client) -> object:
    return arxiv.search_arxiv("graphene", max_results=1, client=client)


def _routes_arxiv() -> str:
    body = (
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry><id>http://arxiv.org/abs/1</id><title>Graphene</title>"
        "<summary>An abstract.</summary><published>2020-01-01</published></entry>"
        "</feed>"
    )
    respx.get(url__startswith="https://export.arxiv.org/api/query").mock(
        return_value=httpx.Response(200, text=body)
    )
    return "export.arxiv.org"


def _call_openalex(client: httpx.Client) -> object:
    return openalex.search_openalex("graphene", max_results=1, client=client)


def _routes_openalex() -> str:
    respx.get(url__startswith="https://api.openalex.org/works").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "title": "Graphene",
                        "abstract_inverted_index": {"An": [0], "abstract": [1]},
                        "publication_date": "2020-01-01",
                        "cited_by_count": 3,
                    }
                ]
            },
        )
    )
    return "api.openalex.org"


def _call_pubmed(client: httpx.Client) -> object:
    return pubmed.search_pubmed("graphene", max_results=1, client=client)


def _routes_pubmed() -> str:
    respx.get(url__startswith="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch").mock(
        return_value=httpx.Response(
            200,
            text="<eSearchResult><IdList><Id>123</Id></IdList></eSearchResult>",
        )
    )
    respx.get(url__startswith="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<PubmedArticleSet><PubmedArticle>"
                "<MedlineCitation><PMID>123</PMID>"
                "<Article><ArticleTitle>Graphene</ArticleTitle>"
                "<Abstract><AbstractText>An abstract.</AbstractText></Abstract>"
                "</Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"
            ),
        )
    )
    return "eutils.ncbi.nlm.nih.gov"


def _call_sec_edgar(client: httpx.Client) -> object:
    return sec_edgar.search_sec_edgar("revenue", max_results=1, client=client)


def _routes_sec_edgar() -> str:
    respx.get(url__startswith="https://efts.sec.gov/LATEST/search-index").mock(
        return_value=httpx.Response(
            200,
            json={
                "hits": {
                    "hits": [
                        {
                            "_id": "0001-24-1",
                            "_source": {
                                "entity_name": "ACME CORP",
                                "form_type": "10-K",
                                "file_date": "2024-01-01",
                                "accession_no": "0001-24-1",
                                "cik": 1,
                            },
                        }
                    ]
                }
            },
        )
    )
    return "efts.sec.gov"


def _call_courtlistener(client: httpx.Client) -> object:
    return courtlistener.search_courtlistener("speech", max_results=1, client=client)


def _routes_courtlistener() -> str:
    respx.get(url__startswith="https://www.courtlistener.com").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 1,
                        "caseName": "Doe v. Roe",
                        "snippet": "A holding.",
                        "dateFiled": "2020-01-01",
                        "absolute_url": "/opinion/1/doe-v-roe/",
                    }
                ]
            },
        )
    )
    return "www.courtlistener.com"


def _call_searxng(client: httpx.Client) -> object:
    return searxng.search("graphene", max_results=1, client=client)


def _routes_searxng() -> str:
    respx.get(url__startswith="http://localhost:8888/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.org/a",
                        "title": "Graphene",
                        "content": "A result.",
                        "engine": "google",
                        "score": 1.0,
                    }
                ]
            },
        )
    )
    return "localhost"


# (id, module, call, register_routes, expected_host)
_ADAPTERS: list[tuple[str, object, Callable[[httpx.Client], object], Callable[[], str], str]] = [
    ("arxiv", arxiv, _call_arxiv, _routes_arxiv, "export.arxiv.org"),
    ("openalex", openalex, _call_openalex, _routes_openalex, "api.openalex.org"),
    ("pubmed", pubmed, _call_pubmed, _routes_pubmed, "eutils.ncbi.nlm.nih.gov"),
    ("sec_edgar", sec_edgar, _call_sec_edgar, _routes_sec_edgar, "efts.sec.gov"),
    (
        "courtlistener",
        courtlistener,
        _call_courtlistener,
        _routes_courtlistener,
        "www.courtlistener.com",
    ),
    ("searxng", searxng, _call_searxng, _routes_searxng, "localhost"),
]


@pytest.mark.parametrize(
    "module, call, register_routes, expected_host",
    [(m, c, r, h) for (_id, m, c, r, h) in _ADAPTERS],
    ids=[a[0] for a in _ADAPTERS],
)
@respx.mock
def test_adapter_routes_through_guard_and_audits(
    module: object,
    call: Callable[[httpx.Client], object],
    register_routes: Callable[[], str],
    expected_host: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter (a) succeeds and (b) writes an allowed audit record.

    The audit line is the proof of routing through the guard: a raw ``httpx``
    call would return the same bytes but leave ``egress.jsonl`` empty.
    """
    register_routes()
    _install_logging_guard(monkeypatch, module, tmp_path)

    with httpx.Client() as client:
        result = call(client)

    # (a) succeeds — the adapter returned a non-empty result set.
    assert result, f"{module} returned no results"

    # (b) routed through the guard — an allowed connection record was written.
    recs = _records(tmp_path)
    allowed = [r for r in recs if r["allowed"] is True]
    assert allowed, f"no allowed egress record written by {module}: {recs}"
    assert any(r["host"] == expected_host for r in allowed), (
        f"expected host {expected_host!r} in audit log, got {[r['host'] for r in allowed]}"
    )


@pytest.mark.parametrize(
    "module, call, register_routes",
    [(m, c, r) for (_id, m, c, r, _h) in _ADAPTERS],
    ids=[a[0] for a in _ADAPTERS],
)
@respx.mock
def test_adapter_blocked_in_airgap_opens_no_socket(
    module: object,
    call: Callable[[httpx.Client], object],
    register_routes: Callable[[], str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With LIGHTHOUSE_AIRGAP=1 the adapter is refused before any socket opens.

    ``respx`` records every route here; asserting ``not route.called`` on all of
    them proves the kill switch denies *before* the transport layer runs — zero
    sockets in airgap mode.
    """
    register_routes()
    routes = list(respx.mock.routes)
    _install_logging_guard(monkeypatch, module, tmp_path)

    monkeypatch.setenv("LIGHTHOUSE_AIRGAP", "1")
    with httpx.Client() as client:
        with pytest.raises(EgressBlocked) as exc:
            call(client)

    assert "AIRGAP" in exc.value.reason
    # Not a single mocked endpoint was contacted — nothing left the machine.
    for route in routes:
        assert not route.called, f"{module} opened a socket in airgap mode"
