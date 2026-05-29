"""Egress-proxy integration tests for fetch_and_ingest (§15.11 + §24.9).

These tests verify that every call to ``fetch_and_ingest`` is gated by the
egress proxy and that the audit line written to ``egress.jsonl`` accurately
reflects the outcome:

  1. A user-explicit fetch (``allow_host=True``, the default) — URL's own host
     is permitted even if absent from ``DEFAULT_ALLOWED_DOMAINS``; exactly one
     audit line is written with ``allowed=true``.

  2. A programmatic/skill fetch (``allow_host=False``) against a host that is
     NOT in ``DEFAULT_ALLOWED_DOMAINS`` — ``EgressBlocked`` is raised before any
     network I/O, and exactly one denied audit line is written.

  3. Redirect + content-type flow is preserved end-to-end when ``log_path`` and
     ``proxy`` are supplied.

No real network I/O occurs: all HTTP is mocked via ``respx`` with an injected
``httpx.Client``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from lighthouse_ai.governor.egress_proxy import DEFAULT_ALLOWED_DOMAINS, EgressProxy
from lighthouse_ai.ingest import fetch_and_ingest
from lighthouse_ai.net import EgressBlocked
from lighthouse_ai.sandbox.broker import SandboxBroker
from lighthouse_ai.sandbox.quarantine import Quarantine
from lighthouse_ai.sandbox.scanners import EICARScanner

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def broker(tmp_path: Path) -> SandboxBroker:
    q = Quarantine(tmp_path / "quarantine.db", tmp_path / "quarantine")
    return SandboxBroker(q, [EICARScanner()])


@pytest.fixture()
def egress_log(tmp_path: Path) -> Path:
    """Path for the egress.jsonl audit log (file need not pre-exist)."""
    return tmp_path / "logs" / "egress.jsonl"


def _read_log(path: Path) -> list[dict]:
    """Parse newline-delimited JSON from the egress log."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Test 1: user-explicit fetch — allowed=True, one audit line written
# ---------------------------------------------------------------------------


@respx.mock
def test_explicit_url_logged_as_allowed(
    broker: SandboxBroker,
    egress_log: Path,
) -> None:
    """fetch_and_ingest with allow_host=True (default) logs an allowed=true line.

    The host ``user-typed.example`` is NOT in DEFAULT_ALLOWED_DOMAINS but must
    be permitted and recorded — the user explicitly requested it.
    """
    url = "https://user-typed.example/article"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text="article body",
            headers={"content-type": "text/plain"},
        )
    )

    with httpx.Client() as client:
        doc = fetch_and_ingest(url, broker, client=client, log_path=egress_log)

    assert doc is not None
    assert "article body" in doc.text

    lines = _read_log(egress_log)
    assert len(lines) == 1, f"Expected 1 audit line, got {len(lines)}: {lines}"

    record = lines[0]
    assert record["host"] == "user-typed.example"
    assert record["allowed"] is True
    assert record["bytes_received"] > 0


# ---------------------------------------------------------------------------
# Test 2: programmatic fetch with allow_host=False — EgressBlocked + denied
# ---------------------------------------------------------------------------


@respx.mock
def test_programmatic_blocked_not_in_allowlist(
    broker: SandboxBroker,
    egress_log: Path,
) -> None:
    """fetch_and_ingest with allow_host=False raises EgressBlocked for unknown hosts.

    No bytes are transferred; the audit line records allowed=false.
    """
    url = "https://not-in-allowlist.example/data"
    # No respx route registered — if a request were actually made it would raise
    # a respx.NetworkX exception, so the test would fail noisily.

    proxy = EgressProxy(DEFAULT_ALLOWED_DOMAINS, egress_log)

    with pytest.raises(EgressBlocked):
        fetch_and_ingest(url, broker, allow_host=False, proxy=proxy)

    lines = _read_log(egress_log)
    assert len(lines) == 1, f"Expected 1 audit line, got {len(lines)}: {lines}"

    record = lines[0]
    assert record["host"] == "not-in-allowlist.example"
    assert record["allowed"] is False
    assert record["bytes_received"] == 0


# ---------------------------------------------------------------------------
# Test 3: redirect + content-type flow through to broker/extractor
# ---------------------------------------------------------------------------


@respx.mock
def test_redirect_and_content_type_flow(
    broker: SandboxBroker,
    egress_log: Path,
) -> None:
    """Redirects are followed and the final Content-Type reaches the extractor.

    The proxy is built with an extended allowlist so both the initial and final
    hosts are permitted.  One audit line is recorded for the completed fetch.
    """
    # Both the initial host and the redirect target need to be in the allowlist.
    allowed = frozenset(DEFAULT_ALLOWED_DOMAINS | {"redirect-from.example", "redirect-to.example"})
    proxy = EgressProxy(allowed, egress_log)

    respx.get("https://redirect-from.example/old").mock(
        return_value=httpx.Response(
            302,
            headers={"location": "https://redirect-to.example/new"},
        )
    )
    respx.get("https://redirect-to.example/new").mock(
        return_value=httpx.Response(
            200,
            html="<html><body><p>redirected content</p></body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )

    # Use a follow_redirects client so respx can handle the chain.
    with httpx.Client(follow_redirects=True) as client:
        doc = fetch_and_ingest(
            "https://redirect-from.example/old",
            broker,
            client=client,
            proxy=proxy,
        )

    assert doc is not None
    assert "redirected content" in doc.text

    lines = _read_log(egress_log)
    # Exactly one audit line — recorded after the full redirect chain completes.
    assert len(lines) == 1
    record = lines[0]
    assert record["allowed"] is True
    # The content-type metadata flows into the document.
    assert "text/html" in (doc.metadata.get("content_type") or "")
