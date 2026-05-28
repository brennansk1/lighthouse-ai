"""Egress proxy — the single chokepoint for outbound requests (design §24.9, §15.11).

A local-first research tool's core promise is that the user's data does not leak.
The threat model (§15) calls out DNS rebinding / SSRF, query eavesdropping, and
egress fingerprinting. The defense is to funnel *every* outbound HTTP request
through one policy gate that:

  * checks the target host against a configurable allowlist
    (``config.toml [egress] allowed_domains``) — anything else is denied with an
    audit entry (§15.11: "anything else denied with audit");
  * classifies the request's privacy tier (§15.11) — ``PRIVATE`` (user-typed
    queries pre-disambiguation) never leaves the machine; ``PUBLIC-OK`` (search)
    and ``PUBLIC-WIDE`` (authenticated APIs) are allowed;
  * logs every connection to ``logs/egress.jsonl`` (§24.9, §15.6) so the user
    can audit exactly what went upstream and when.

This module implements the **policy decision and the audit log only**. It does
not open sockets, resolve DNS, or route through Tor — that is the transport
layer's job, and keeping policy pure makes it trivially testable and impossible
to accidentally turn into a live network call during a test. Decisions are
returned as a frozen :class:`EgressDecision` mirroring the Governor's other
allow/deny verdicts.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit


class PrivacyTier(str, Enum):
    """Per-source privacy classification (§15.11).

    ``str`` mixin keeps the values JSON-serializable for the egress log without
    a custom encoder.
    """

    PRIVATE = "PRIVATE"  # user-typed queries pre-disambiguation; local-only.
    PUBLIC_OK = "PUBLIC-OK"  # search-engine queries.
    PUBLIC_WIDE = "PUBLIC-WIDE"  # authenticated APIs.


# The default allowlist from §15.11; callers override via [egress] allowed_domains.
DEFAULT_ALLOWED_DOMAINS: frozenset[str] = frozenset(
    {
        "arxiv.org",
        "openalex.org",
        "api.semanticscholar.org",
        "api.crossref.org",
        "pubmed.ncbi.nlm.nih.gov",
        "github.com",
        "api.github.com",
        "www.sec.gov",
        "www.courtlistener.com",
        "api.stlouisfed.org",
        "www.imf.org",
        "archive.org",
        "web.archive.org",
    }
)


@dataclass(frozen=True)
class EgressDecision:
    """Allow/deny verdict for one outbound request.

    ``host`` and ``tier`` are echoed back so the caller can log and act on the
    decision without re-parsing the URL.
    """

    allowed: bool
    host: str = ""
    tier: PrivacyTier = PrivacyTier.PUBLIC_WIDE
    reason: str = ""


def extract_host(url_or_host: str) -> str:
    """Return the bare, lowercased hostname for a URL or host string.

    Accepts both full URLs (``https://arxiv.org/abs/...``) and bare hosts so
    call sites need not normalize first. Strips any port and userinfo, which are
    never part of an allowlist match.
    """

    candidate = url_or_host.strip()
    if "://" in candidate:
        netloc = urlsplit(candidate).netloc
    else:
        # ``urlsplit`` needs a scheme to populate ``netloc``; add a dummy one.
        netloc = urlsplit("//" + candidate).netloc
    # Drop userinfo and port.
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[-1]
    if netloc.startswith("["):  # bracketed IPv6 literal
        host = netloc[1 : netloc.index("]")] if "]" in netloc else netloc
    else:
        host = netloc.split(":", 1)[0]
    return host.lower().rstrip(".")


class EgressProxy:
    """Policy + audit gate for all outbound requests (§24.9).

    A single instance is configured with the session's allowlist and the path to
    ``egress.jsonl``; the runtime asks it for a decision before any transport
    layer opens a connection, then reports the actual byte/duration figures back
    via :meth:`log_connection` once the request completes.
    """

    def __init__(
        self,
        allowed_domains: frozenset[str] | set[str] | None = None,
        log_path: Path | str | None = None,
        *,
        allow_subdomains: bool = True,
    ) -> None:
        self._allowed = frozenset(
            d.lower().rstrip(".")
            for d in (allowed_domains if allowed_domains is not None else DEFAULT_ALLOWED_DOMAINS)
        )
        self._log_path = Path(log_path) if log_path is not None else None
        self._allow_subdomains = allow_subdomains

    @property
    def allowed_domains(self) -> frozenset[str]:
        return self._allowed

    # --- allowlist (§15.11) ---

    def is_allowed_host(self, host: str) -> bool:
        """True when ``host`` matches the allowlist.

        With ``allow_subdomains`` (the default) ``export.arxiv.org`` matches an
        allowlisted ``arxiv.org`` — APIs routinely live on subdomains. The match
        is on label boundaries so ``evilarxiv.org`` never matches ``arxiv.org``.
        """

        host = host.lower().rstrip(".")
        if host in self._allowed:
            return True
        if self._allow_subdomains:
            return any(host.endswith("." + dom) for dom in self._allowed)
        return False

    # --- combined decision (§24.9) ---

    def check(
        self, url_or_host: str, tier: PrivacyTier = PrivacyTier.PUBLIC_WIDE
    ) -> EgressDecision:
        """Decide whether a request may leave the machine.

        Order matters: a ``PRIVATE`` request is denied *before* the allowlist is
        consulted, because the privacy tier — not the destination — is the
        binding constraint (a private query must never egress even to an
        allowlisted host). Allowlisted public requests are permitted.
        """

        host = extract_host(url_or_host)

        if tier == PrivacyTier.PRIVATE:
            return EgressDecision(
                allowed=False,
                host=host,
                tier=tier,
                reason="PRIVATE tier: local-only, no egress (§15.11)",
            )

        if not host:
            return EgressDecision(
                allowed=False, host=host, tier=tier, reason="no resolvable host"
            )

        if not self.is_allowed_host(host):
            return EgressDecision(
                allowed=False,
                host=host,
                tier=tier,
                reason=f"host {host!r} not in egress allowlist",
            )

        return EgressDecision(allowed=True, host=host, tier=tier, reason="allowed")

    # --- connection log (§24.9, §15.6) ---

    def log_connection(
        self,
        host: str,
        *,
        port: int,
        bytes_sent: int = 0,
        bytes_received: int = 0,
        duration_ms: float = 0.0,
        tier: PrivacyTier = PrivacyTier.PUBLIC_WIDE,
        allowed: bool = True,
        reason: str = "",
        timestamp: _dt.datetime | None = None,
    ) -> dict[str, object]:
        """Append one connection record to ``egress.jsonl`` and return it.

        The record is the audit unit the user inspects to answer "what left my
        machine?" — so it captures host, port, byte counts, duration, the
        privacy tier, and whether the request was permitted. We append a single
        JSON line per connection (newline-delimited JSON) so the log is both
        streamable and trivially greppable. Parent directories are created on
        demand because the log may be written before any other egress setup.
        """

        record: dict[str, object] = {
            "ts": (timestamp or _dt.datetime.now(_dt.timezone.utc)).isoformat(),
            "host": host,
            "port": port,
            "bytes_sent": bytes_sent,
            "bytes_received": bytes_received,
            "duration_ms": duration_ms,
            "tier": tier.value if isinstance(tier, PrivacyTier) else str(tier),
            "allowed": allowed,
            "reason": reason,
        }
        if self._log_path is not None:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def read_log(self) -> list[dict[str, object]]:
        """Parse the egress log back into records (for ``doctor`` stats, §24.11)."""

        if self._log_path is None or not self._log_path.exists():
            return []
        records: list[dict[str, object]] = []
        with self._log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
