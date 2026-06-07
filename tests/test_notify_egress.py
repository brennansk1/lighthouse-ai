"""Egress-guard proof for the notification channels (A3).

The Telegram and Discord channels must reach the network *only* through the
egress guard (:mod:`lighthouse_ai.net`), never via raw ``httpx``. Two properties
together prove that, mirroring :mod:`tests.test_egress_enforcement`:

  1. **It routes through the guard.** Sending succeeds *and* writes a connection
     record to ``egress.jsonl`` — a side effect only
     :meth:`EgressProxy.log_connection` produces. A raw ``httpx`` call would
     deliver the same bytes but leave the audit log empty.

  2. **The kill switch is load-bearing.** With ``LIGHTHOUSE_AIRGAP=1`` the guard
     raises :class:`EgressBlocked` *before* any socket opens (swallowed by the
     channel into a ``False`` return) and the respx route is *never* called —
     the strongest available proxy for "zero sockets opened" without real I/O.

The channels build a throwaway proxy internally from their ``allowed_domains``,
so to observe the audit log we replace each module's ``guarded_request`` /
``guarded_get`` with a thin shim that threads the *same* call (allowlist +
injected client preserved) through an :class:`EgressGuardedClient` backed by a
real :class:`EgressProxy` writing to a temp ``egress.jsonl``. The shim adds no
policy of its own, so the guard's real ``check`` → fetch → ``log_connection``
path (and its AIRGAP short-circuit) is what actually runs. No test here performs
real network I/O.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from lighthouse_ai.governor.egress_proxy import EgressProxy
from lighthouse_ai.net import EgressGuardedClient
from lighthouse_ai.notify import channels, telegram
from lighthouse_ai.notify.channels import DiscordChannel
from lighthouse_ai.notify.telegram import API_ROOT, TelegramChannel, request_confirmation

TOKEN = "123:ABC"
CHAT = "555"
SEND_URL = f"{API_ROOT}/bot{TOKEN}/sendMessage"
UPDATES_URL = f"{API_ROOT}/bot{TOKEN}/getUpdates"
WEBHOOK_URL = "https://discord.com/api/webhooks/42/abc"


def _records(tmp_path: Path) -> list[dict]:
    """Parse the temp ``egress.jsonl`` audit log into records."""
    log = tmp_path / "egress.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def _install_logging_request(
    monkeypatch: pytest.MonkeyPatch, module: object, tmp_path: Path
) -> None:
    """Route ``module.guarded_request`` through a logging :class:`EgressProxy`.

    The replacement preserves the channel's call shape exactly — it accepts the
    channel's own ``allowed_domains`` and injected ``client`` — but threads the
    request through an :class:`EgressGuardedClient` whose proxy writes to a temp
    ``egress.jsonl``. This makes the guard's real decide-before-fetch + audit
    path observable without changing the policy the channel declared.
    """

    def _shim(
        method: str,
        url: str,
        *,
        allowed_domains: frozenset[str] | set[str] | None = None,
        client: httpx.Client | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        proxy = EgressProxy(allowed_domains, log_path=tmp_path / "egress.jsonl")
        guard = EgressGuardedClient(proxy, client=client)
        try:
            return guard.request(method, url, **kwargs)  # type: ignore[arg-type]
        finally:
            guard.close()

    monkeypatch.setattr(module, "guarded_request", _shim)


def _install_logging_get(
    monkeypatch: pytest.MonkeyPatch, module: object, tmp_path: Path
) -> None:
    """Route ``module.guarded_get`` through the same logging proxy as above."""

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


# --- Telegram: TelegramChannel.send ------------------------------------------


@respx.mock
def test_telegram_send_routes_through_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A Telegram send succeeds and writes an allowed=true audit record."""
    _install_logging_request(monkeypatch, telegram, tmp_path)
    route = respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    with httpx.Client() as client:
        ok = TelegramChannel(TOKEN, CHAT, client=client).send("Title", "Body")

    assert ok is True
    assert route.called
    records = _records(tmp_path)
    assert len(records) == 1
    assert records[0]["host"] == "api.telegram.org"
    assert records[0]["allowed"] is True


@respx.mock
def test_telegram_send_blocked_by_airgap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """LIGHTHOUSE_AIRGAP=1 blocks the send with no socket opened."""
    _install_logging_request(monkeypatch, telegram, tmp_path)
    monkeypatch.setenv("LIGHTHOUSE_AIRGAP", "1")
    route = respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    with httpx.Client() as client:
        # The channel swallows EgressBlocked into a False return (delivery failure).
        ok = TelegramChannel(TOKEN, CHAT, client=client).send("Title", "Body")

    assert ok is False
    # The guard refuses before any socket opens: the respx route is never hit.
    assert route.called is False


# --- Telegram: request_confirmation airlock (POST + GET) ----------------------


@respx.mock
def test_confirmation_routes_through_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The §24.10 airlock POST (prompt) and GET (poll) both route through the guard."""
    _install_logging_request(monkeypatch, telegram, tmp_path)
    _install_logging_get(monkeypatch, telegram, tmp_path)
    send_route = respx.post(SEND_URL).mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    poll_route = respx.get(UPDATES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {"update_id": 1, "message": {"chat": {"id": CHAT}, "text": "YES"}}
                ],
            },
        )
    )

    with httpx.Client() as client:
        confirmed = request_confirmation(
            TOKEN, CHAT, "reply YES", timeout_s=5, client=client, sleep=lambda _s: None
        )

    assert confirmed is True
    assert send_route.called and poll_route.called
    records = _records(tmp_path)
    # Both the prompt POST and the poll GET are audited as allowed.
    assert len(records) >= 2
    assert all(r["host"] == "api.telegram.org" for r in records)
    assert all(r["allowed"] is True for r in records)


@respx.mock
def test_confirmation_blocked_by_airgap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With AIRGAP on, the airlock cannot deliver its prompt → aborts, no socket."""
    _install_logging_request(monkeypatch, telegram, tmp_path)
    _install_logging_get(monkeypatch, telegram, tmp_path)
    monkeypatch.setenv("LIGHTHOUSE_AIRGAP", "1")
    send_route = respx.post(SEND_URL).mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    with httpx.Client() as client:
        confirmed = request_confirmation(
            TOKEN, CHAT, "reply YES", timeout_s=5, client=client, sleep=lambda _s: None
        )

    # EgressBlocked on the prompt POST is treated as "could not ask" → abort.
    assert confirmed is False
    assert send_route.called is False


# --- Discord: DiscordChannel.send --------------------------------------------


@respx.mock
def test_discord_send_routes_through_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A Discord webhook send succeeds and writes an allowed=true audit record.

    The webhook host is user-configured and not in DEFAULT_ALLOWED_DOMAINS; it is
    permitted because the channel passes it as user-authorized ``allowed_domains``.
    """
    _install_logging_request(monkeypatch, channels, tmp_path)
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(204))

    with httpx.Client() as client:
        ok = DiscordChannel(WEBHOOK_URL, client=client).send("Title", "Body")

    assert ok is True
    assert route.called
    records = _records(tmp_path)
    assert len(records) == 1
    assert records[0]["host"] == "discord.com"
    assert records[0]["allowed"] is True


@respx.mock
def test_discord_send_blocked_by_airgap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """LIGHTHOUSE_AIRGAP=1 blocks the Discord send with no socket opened."""
    _install_logging_request(monkeypatch, channels, tmp_path)
    monkeypatch.setenv("LIGHTHOUSE_AIRGAP", "1")
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(204))

    with httpx.Client() as client:
        ok = DiscordChannel(WEBHOOK_URL, client=client).send("Title", "Body")

    assert ok is False
    # The guard refuses before any socket opens: the respx route is never hit.
    assert route.called is False
