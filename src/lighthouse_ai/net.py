"""Egress-guarded HTTP client — the enforcement edge of the Governor's policy.

The Governor's :class:`~lighthouse_ai.governor.egress_proxy.EgressProxy` is a
*pure* policy oracle: it decides allow/deny and records audit lines, but it
deliberately never opens a socket (see that module's docstring). That purity is
what makes it testable, but it also means a policy is only as good as the code
that consults it. This module is that code: a thin wrapper around ``httpx`` that
makes the proxy's verdict load-bearing on the actual transport.

The single security invariant here is **decide before you fetch, never after**.
A request to a non-allowlisted host, or any ``PRIVATE``-tier request, must be
refused *without a packet leaving the machine* — by the time bytes are on the
wire the data has already leaked, so a post-hoc check is worthless. Every public
method therefore calls :meth:`EgressProxy.check` first and raises
:class:`EgressBlocked` on a deny verdict before constructing or sending any
request. Only on an allow verdict do we fetch, and only then do we report the
real byte/status figures back to :meth:`EgressProxy.log_connection` so the
user's ``egress.jsonl`` audit trail reflects exactly what went upstream.
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit

import httpx

from .governor.egress_proxy import (
    DEFAULT_ALLOWED_DOMAINS,
    EgressProxy,
    PrivacyTier,
)


class EgressBlocked(RuntimeError):
    """Raised when egress policy denies a request *before* it is sent.

    Subclasses :class:`RuntimeError` rather than introducing a bespoke base so
    call sites that only care that "the fetch did not happen" can catch broadly,
    while the ``reason`` carried from the :class:`EgressDecision` remains
    available for logging and user-facing diagnostics.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _default_port(url: str) -> int:
    """Best-effort port for the audit log when the URL omits one.

    The connection record wants a concrete port; if the URL does not specify
    one we infer it from the scheme (443 for https, 80 otherwise) so the audit
    trail is never blank.
    """

    parts = urlsplit(url)
    if parts.port is not None:
        return parts.port
    return 443 if parts.scheme == "https" else 80


class EgressGuardedClient:
    """An ``httpx``-backed fetcher that cannot bypass the egress policy.

    Every outbound request is gated by an :class:`EgressProxy`: the decision is
    consulted *first*, and a deny verdict raises :class:`EgressBlocked` without
    ever touching the network. This is the only sanctioned way for the rest of
    Lighthouse to reach the internet, so the policy gate is impossible to
    accidentally skip.

    The underlying ``httpx.Client`` is injectable to keep the class testable and
    to let callers share connection pools / configure timeouts; when not
    supplied we own a private client and close it with the instance.
    """

    def __init__(
        self,
        proxy: EgressProxy | None = None,
        *,
        allowed_domains: frozenset[str] | set[str] | None = None,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if proxy is not None:
            self._proxy = proxy
        else:
            # Build a default policy from the (optional) allowlist so a caller
            # can spin up a guarded client without first constructing a proxy.
            self._proxy = EgressProxy(
                allowed_domains
                if allowed_domains is not None
                else DEFAULT_ALLOWED_DOMAINS
            )
        # Track ownership: we must only close a client we created ourselves.
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    @property
    def proxy(self) -> EgressProxy:
        return self._proxy

    def get(
        self, url: str, *, privacy: PrivacyTier = PrivacyTier.PUBLIC_OK
    ) -> httpx.Response:
        """Fetch ``url`` only if egress policy permits it.

        Policy is consulted before any request object is built. On a deny
        verdict we raise :class:`EgressBlocked` immediately — no socket is
        opened, so nothing leaks. On an allow verdict we perform the GET, then
        record the real host/byte/status figures to the egress audit log so the
        user can see exactly what left the machine.
        """

        decision = self._proxy.check(url, privacy)
        if not decision.allowed:
            # Refuse BEFORE fetching: egress is a one-way door (§15.11).
            raise EgressBlocked(decision.reason)

        started = time.monotonic()
        # Force no auto-redirect even if an injected client enabled it: a 3xx to
        # a non-allowlisted host would otherwise be followed WITHOUT re-checking
        # the policy, leaking to an unvetted destination. The caller receives the
        # 3xx and must re-issue the redirect target through this same gate.
        response = self._client.get(url, follow_redirects=False)
        duration_ms = (time.monotonic() - started) * 1000.0

        request_bytes = len(response.request.content) if response.request is not None else 0
        self._proxy.log_connection(
            decision.host,
            port=_default_port(url),
            bytes_sent=request_bytes,
            bytes_received=len(response.content),
            duration_ms=duration_ms,
            tier=privacy,
            allowed=True,
            reason="fetched",
        )
        return response

    def close(self) -> None:
        """Close the underlying client if (and only if) we own it."""

        if self._owns_client:
            self._client.close()

    def __enter__(self) -> EgressGuardedClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def guarded_get(
    url: str,
    *,
    allowed_domains: frozenset[str] | set[str] | None = None,
    privacy: PrivacyTier = PrivacyTier.PUBLIC_OK,
    client: httpx.Client | None = None,
) -> httpx.Response:
    """One-shot guarded GET for callers that do not hold a client.

    Constructs a throwaway :class:`EgressGuardedClient` from ``allowed_domains``,
    enforces the same decide-before-fetch invariant, and tears down any client
    it created. A blocked request raises :class:`EgressBlocked` and performs no
    network I/O, exactly as :meth:`EgressGuardedClient.get` does.
    """

    guard = EgressGuardedClient(
        allowed_domains=allowed_domains, client=client
    )
    try:
        return guard.get(url, privacy=privacy)
    finally:
        guard.close()
