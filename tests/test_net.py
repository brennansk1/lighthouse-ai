"""Tests for the egress-guarded HTTP client (``lighthouse_ai.net``).

These exercise the security boundary: an allowed request fetches and audits; a
denied request must raise BEFORE any packet leaves the machine. We assert the
latter by mocking the route with ``respx`` and checking it was *never called* —
the strongest available proxy for "no socket was opened" without real network.
No test here performs real network I/O.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from lighthouse_ai.governor.egress_proxy import EgressProxy, PrivacyTier
from lighthouse_ai.net import EgressBlocked, EgressGuardedClient, guarded_get

ALLOWED = frozenset({"arxiv.org", "api.github.com"})


def _proxy(tmp_path: Path) -> EgressProxy:
    return EgressProxy(ALLOWED, log_path=tmp_path / "egress.jsonl")


def _records(tmp_path: Path) -> list[dict]:
    log = tmp_path / "egress.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


# --- allowed fetches ---


@respx.mock
def test_allowed_domain_fetches(tmp_path: Path) -> None:
    route = respx.get("https://arxiv.org/abs/1").mock(
        return_value=httpx.Response(200, text="ok")
    )
    client = EgressGuardedClient(_proxy(tmp_path))
    resp = client.get("https://arxiv.org/abs/1")
    assert resp.status_code == 200
    assert resp.text == "ok"
    assert route.called


@respx.mock
def test_allowed_subdomain_fetches(tmp_path: Path) -> None:
    route = respx.get("https://export.arxiv.org/api").mock(
        return_value=httpx.Response(200)
    )
    client = EgressGuardedClient(_proxy(tmp_path))
    client.get("https://export.arxiv.org/api")
    assert route.called


@respx.mock
def test_allowed_fetch_writes_connection_log(tmp_path: Path) -> None:
    respx.get("https://arxiv.org/x").mock(
        return_value=httpx.Response(200, text="hello")
    )
    EgressGuardedClient(_proxy(tmp_path)).get("https://arxiv.org/x")
    recs = _records(tmp_path)
    assert len(recs) == 1
    assert recs[0]["host"] == "arxiv.org"
    assert recs[0]["allowed"] is True


@respx.mock
def test_log_records_bytes_received(tmp_path: Path) -> None:
    body = "x" * 42
    respx.get("https://arxiv.org/y").mock(return_value=httpx.Response(200, text=body))
    EgressGuardedClient(_proxy(tmp_path)).get("https://arxiv.org/y")
    rec = _records(tmp_path)[0]
    assert rec["bytes_received"] == len(body.encode())


@respx.mock
def test_log_records_port_443_for_https(tmp_path: Path) -> None:
    respx.get("https://arxiv.org/z").mock(return_value=httpx.Response(200))
    EgressGuardedClient(_proxy(tmp_path)).get("https://arxiv.org/z")
    assert _records(tmp_path)[0]["port"] == 443


@respx.mock
def test_log_records_explicit_port(tmp_path: Path) -> None:
    respx.get("https://arxiv.org:8443/p").mock(return_value=httpx.Response(200))
    EgressGuardedClient(_proxy(tmp_path)).get("https://arxiv.org:8443/p")
    assert _records(tmp_path)[0]["port"] == 8443


@respx.mock
def test_non_200_status_still_logged(tmp_path: Path) -> None:
    respx.get("https://arxiv.org/missing").mock(return_value=httpx.Response(404))
    resp = EgressGuardedClient(_proxy(tmp_path)).get("https://arxiv.org/missing")
    assert resp.status_code == 404
    assert len(_records(tmp_path)) == 1


# --- blocked: non-allowlisted domain ---


@respx.mock
def test_non_allowlisted_domain_blocked(tmp_path: Path) -> None:
    route = respx.get("https://evil.example.com/").mock(
        return_value=httpx.Response(200)
    )
    client = EgressGuardedClient(_proxy(tmp_path))
    with pytest.raises(EgressBlocked):
        client.get("https://evil.example.com/")
    assert not route.called  # no socket opened — nothing leaked


@respx.mock
def test_lookalike_domain_blocked(tmp_path: Path) -> None:
    route = respx.get("https://evilarxiv.org/").mock(return_value=httpx.Response(200))
    with pytest.raises(EgressBlocked):
        EgressGuardedClient(_proxy(tmp_path)).get("https://evilarxiv.org/")
    assert not route.called


@respx.mock
def test_blocked_request_writes_no_log(tmp_path: Path) -> None:
    respx.get("https://evil.example.com/").mock(return_value=httpx.Response(200))
    with pytest.raises(EgressBlocked):
        EgressGuardedClient(_proxy(tmp_path)).get("https://evil.example.com/")
    assert _records(tmp_path) == []


def test_blocked_reason_propagated(tmp_path: Path) -> None:
    with pytest.raises(EgressBlocked) as exc:
        EgressGuardedClient(_proxy(tmp_path)).get("https://evil.example.com/")
    assert "allowlist" in exc.value.reason


# --- blocked: PRIVATE tier ---


@respx.mock
def test_private_tier_blocks_even_allowlisted_host(tmp_path: Path) -> None:
    route = respx.get("https://arxiv.org/secret").mock(
        return_value=httpx.Response(200)
    )
    client = EgressGuardedClient(_proxy(tmp_path))
    with pytest.raises(EgressBlocked):
        client.get("https://arxiv.org/secret", privacy=PrivacyTier.PRIVATE)
    assert not route.called


def test_private_tier_reason_mentions_private(tmp_path: Path) -> None:
    with pytest.raises(EgressBlocked) as exc:
        EgressGuardedClient(_proxy(tmp_path)).get(
            "https://arxiv.org/x", privacy=PrivacyTier.PRIVATE
        )
    assert "PRIVATE" in exc.value.reason


# --- injectable client & defaults ---


@respx.mock
def test_uses_injected_client(tmp_path: Path) -> None:
    injected = httpx.Client()
    route = respx.get("https://arxiv.org/inj").mock(return_value=httpx.Response(200))
    client = EgressGuardedClient(_proxy(tmp_path), client=injected)
    client.get("https://arxiv.org/inj")
    assert route.called
    injected.close()


def test_does_not_close_injected_client(tmp_path: Path) -> None:
    injected = httpx.Client()
    client = EgressGuardedClient(_proxy(tmp_path), client=injected)
    client.close()
    assert not injected.is_closed  # caller owns it
    injected.close()


@respx.mock
def test_builds_default_proxy_from_allowed_domains() -> None:
    route = respx.get("https://arxiv.org/d").mock(return_value=httpx.Response(200))
    client = EgressGuardedClient(allowed_domains=ALLOWED)
    client.get("https://arxiv.org/d")
    assert route.called
    client.close()


def test_default_allowlist_blocks_unknown_host() -> None:
    client = EgressGuardedClient(allowed_domains=ALLOWED)
    with pytest.raises(EgressBlocked):
        client.get("https://nope.example.com/")
    client.close()


# --- guarded_get convenience ---


@respx.mock
def test_guarded_get_allows_allowlisted(tmp_path: Path) -> None:
    route = respx.get("https://api.github.com/r").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    resp = guarded_get("https://api.github.com/r", allowed_domains=ALLOWED)
    assert resp.status_code == 200
    assert route.called


@respx.mock
def test_guarded_get_blocks_non_allowlisted(tmp_path: Path) -> None:
    route = respx.get("https://evil.example.com/").mock(
        return_value=httpx.Response(200)
    )
    with pytest.raises(EgressBlocked):
        guarded_get("https://evil.example.com/", allowed_domains=ALLOWED)
    assert not route.called


@respx.mock
def test_guarded_get_private_tier_blocks(tmp_path: Path) -> None:
    route = respx.get("https://arxiv.org/p").mock(return_value=httpx.Response(200))
    with pytest.raises(EgressBlocked):
        guarded_get(
            "https://arxiv.org/p",
            allowed_domains=ALLOWED,
            privacy=PrivacyTier.PRIVATE,
        )
    assert not route.called


# --- context manager ---


@respx.mock
def test_context_manager_fetches_and_closes(tmp_path: Path) -> None:
    respx.get("https://arxiv.org/cm").mock(return_value=httpx.Response(200))
    with EgressGuardedClient(_proxy(tmp_path)) as client:
        client.get("https://arxiv.org/cm")
    assert len(_records(tmp_path)) == 1
