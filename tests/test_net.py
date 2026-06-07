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
from lighthouse_ai.net import (
    EgressBlocked,
    EgressGuardedClient,
    guarded_get,
    guarded_request,
)

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


# --- redirect-aware enforcement (egress is a one-way door) ---


@respx.mock
def test_redirect_to_disallowed_host_blocked(tmp_path: Path) -> None:
    """A follow-redirects client must not let a redirect escape the allowlist.

    arxiv.org is allowed; the 302 target is not. With an injected
    follow_redirects client the bytes would otherwise be fetched and returned,
    bypassing the egress policy. The final host is re-checked and the call
    raises EgressBlocked instead of returning the attacker's response.
    """
    respx.get("https://arxiv.org/r").mock(
        return_value=httpx.Response(302, headers={"location": "https://evil.example.com/x"})
    )
    respx.get("https://evil.example.com/x").mock(
        return_value=httpx.Response(200, text="LEAKED")
    )
    redir_client = httpx.Client(follow_redirects=True)
    client = EgressGuardedClient(_proxy(tmp_path), client=redir_client)
    with pytest.raises(EgressBlocked) as exc:
        client.get("https://arxiv.org/r")
    assert "evil.example.com" in exc.value.reason
    # A denied audit line for the final host with zero bytes is recorded.
    recs = _records(tmp_path)
    denied = [r for r in recs if r["allowed"] is False]
    assert denied and denied[-1]["host"] == "evil.example.com"
    redir_client.close()


@respx.mock
def test_redirect_to_allowed_host_succeeds_without_crash(tmp_path: Path) -> None:
    """A redirect between two allowlisted hosts succeeds and does not raise.

    Also guards the historical RequestNotRead crash: a redirected request's
    body is never buffered, so naively reading ``response.request.content``
    would raise after the fetch already completed.
    """
    proxy = EgressProxy(frozenset({"arxiv.org", "export.arxiv.org"}), log_path=tmp_path / "egress.jsonl")
    respx.get("https://arxiv.org/a").mock(
        return_value=httpx.Response(302, headers={"location": "https://export.arxiv.org/b"})
    )
    respx.get("https://export.arxiv.org/b").mock(
        return_value=httpx.Response(200, text="final")
    )
    redir_client = httpx.Client(follow_redirects=True)
    client = EgressGuardedClient(proxy, client=redir_client)
    resp = client.get("https://arxiv.org/a")
    assert resp.status_code == 200
    assert resp.text == "final"
    rec = _records(tmp_path)[0]
    assert rec["allowed"] is True
    assert rec["host"] == "export.arxiv.org"
    redir_client.close()


# --- general request(): params, headers, POST ---


@respx.mock
def test_request_forwards_params_and_headers(tmp_path: Path) -> None:
    """request() must carry the caller's query params and headers upstream."""
    route = respx.get("https://api.github.com/search").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = EgressGuardedClient(_proxy(tmp_path))
    resp = client.request(
        "GET",
        "https://api.github.com/search",
        params={"q": "lighthouse", "page": 2},
        headers={"X-Test": "abc"},
    )
    assert resp.status_code == 200
    assert route.called
    sent = route.calls.last.request
    assert sent.url.params["q"] == "lighthouse"
    assert sent.url.params["page"] == "2"
    assert sent.headers["X-Test"] == "abc"


@respx.mock
def test_request_post_with_json_is_logged(tmp_path: Path) -> None:
    """A POST with a JSON body fetches, sends the body, and is audit-logged."""
    route = respx.post("https://api.github.com/markdown").mock(
        return_value=httpx.Response(201, text="created")
    )
    client = EgressGuardedClient(_proxy(tmp_path))
    resp = client.request(
        "POST",
        "https://api.github.com/markdown",
        json={"text": "# hi"},
    )
    assert resp.status_code == 201
    assert route.called
    sent = route.calls.last.request
    assert json.loads(sent.content) == {"text": "# hi"}
    recs = _records(tmp_path)
    assert len(recs) == 1
    assert recs[0]["host"] == "api.github.com"
    assert recs[0]["allowed"] is True
    assert recs[0]["bytes_sent"] > 0


@respx.mock
def test_guarded_request_post_allows_allowlisted(tmp_path: Path) -> None:
    route = respx.post("https://api.github.com/markdown").mock(
        return_value=httpx.Response(200, text="ok")
    )
    resp = guarded_request(
        "POST",
        "https://api.github.com/markdown",
        allowed_domains=ALLOWED,
        json={"text": "hi"},
    )
    assert resp.status_code == 200
    assert route.called


# --- central kill switch: LIGHTHOUSE_AIRGAP ---


@respx.mock
def test_airgap_denies_request_before_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With LIGHTHOUSE_AIRGAP set, an otherwise-allowed request is refused.

    The respx route must never fire — the kill switch denies before any socket
    is opened — and clearing the env var restores normal behaviour.
    """
    route = respx.get("https://arxiv.org/k").mock(return_value=httpx.Response(200))
    client = EgressGuardedClient(_proxy(tmp_path))

    monkeypatch.setenv("LIGHTHOUSE_AIRGAP", "1")
    with pytest.raises(EgressBlocked) as exc:
        client.request("GET", "https://arxiv.org/k")
    assert "AIRGAP" in exc.value.reason
    assert not route.called  # no socket opened — nothing leaked

    monkeypatch.delenv("LIGHTHOUSE_AIRGAP")
    resp = client.request("GET", "https://arxiv.org/k")
    assert resp.status_code == 200
    assert route.called


# --- context manager ---


@respx.mock
def test_context_manager_fetches_and_closes(tmp_path: Path) -> None:
    respx.get("https://arxiv.org/cm").mock(return_value=httpx.Response(200))
    with EgressGuardedClient(_proxy(tmp_path)) as client:
        client.get("https://arxiv.org/cm")
    assert len(_records(tmp_path)) == 1
