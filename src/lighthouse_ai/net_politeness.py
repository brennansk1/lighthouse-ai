"""Politeness layer for the egress-guarded HTTP client (Zone F).

This module provides three composable components that enforce crawl courtesy
without coupling the core fetch path to any optional dependency. Every library
(protego, courlan, pyrate-limiter) is lazily imported; when absent the module
falls back to a permissive pure-Python implementation so the base Lighthouse
install never breaks.

The decision order inside :class:`PolitenessGate` mirrors the standard crawl
contract:

1. **Robots check** — is this path allowed for the given user-agent?
   Disallowed → raises :class:`~lighthouse_ai.net.EgressBlocked` before any
   connection attempt.
2. **Rate budget** — is there capacity in the per-domain token bucket?
   Exhausted → ``acquire`` blocks (or ``try_acquire`` returns False).

Components are designed to be injected into :class:`EgressGuardedClient` via
the optional ``politeness`` parameter added to that class; they are also usable
standalone for testing or custom fetch pipelines.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional-import probes
# ---------------------------------------------------------------------------

try:
    import protego as _protego  # type: ignore[import-untyped]

    _HAS_PROTEGO = True
except ModuleNotFoundError:
    _HAS_PROTEGO = False

try:
    from courlan import clean_url as _courlan_clean  # type: ignore[import-untyped]

    _HAS_COURLAN = True
except ModuleNotFoundError:
    _HAS_COURLAN = False

try:
    from pyrate_limiter import (  # type: ignore[import-untyped]
        Duration,
        Limiter,
        Rate,
    )

    _HAS_PYRATE = True
except ModuleNotFoundError:
    _HAS_PYRATE = False


# ---------------------------------------------------------------------------
# canonicalize — URL normalisation
# ---------------------------------------------------------------------------


def canonicalize(url: str) -> str:
    """Return a canonicalized form of *url*.

    When ``courlan`` is installed it delegates to :func:`courlan.clean_url`
    which handles percent-encoding, trailing slashes, default ports, and
    fragment stripping. Without courlan we perform a minimal stdlib
    normalisation: scheme+host lowercasing, default-port removal, and fragment
    stripping.

    The function is deterministic and never raises for a well-formed URL.
    """

    if _HAS_COURLAN:
        try:
            cleaned = _courlan_clean(url)
            if cleaned:
                return cleaned
        except Exception:  # pragma: no cover
            pass  # fall through to stdlib path

    # Stdlib fallback
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    # Strip default ports
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    elif netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    # Remove fragment; keep path, query
    canonical = parts._replace(scheme=scheme, netloc=netloc, fragment="").geturl()
    return canonical


# ---------------------------------------------------------------------------
# RobotsPolicy — robots.txt fetch + cache
# ---------------------------------------------------------------------------


class RobotsPolicy:
    """Fetch and cache ``robots.txt`` per host; answer allow/deny questions.

    By design this class does **not** open sockets itself. The caller supplies
    a *fetcher* callable ``fetcher(url: str) -> bytes`` so that tests can inject
    canned robots.txt bytes and production code can route through the already-
    guarded HTTP client.

    When ``protego`` is installed the full ``robots.txt`` spec (per-agent rules,
    wildcards, Crawl-delay) is honoured. Without it the policy is permissive:
    every path is allowed and ``crawl_delay`` returns 0.0.
    """

    def __init__(
        self,
        fetcher: Callable[[str], bytes] | None = None,
        *,
        user_agent: str = "LighthouseBot",
        ttl: float = 3600.0,
    ) -> None:
        """
        Parameters
        ----------
        fetcher:
            Callable ``(url) -> bytes`` used to retrieve ``robots.txt``.  When
            ``None`` the gate is permanently permissive (no fetch is ever made).
        user_agent:
            The user-agent string presented to the robots.txt parser.
        ttl:
            How long (seconds) to cache a parsed robots.txt before re-fetching.
            Defaults to one hour.
        """
        self._fetcher = fetcher
        self._user_agent = user_agent
        self._ttl = ttl
        # host → (parsed_robot_or_None, fetched_at_monotonic)
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _robots_url(self, host: str) -> str:
        return f"https://{host}/robots.txt"

    def _fetch_and_parse(self, host: str) -> Any:
        """Fetch and parse robots.txt for *host*; returns parsed object or None."""
        if self._fetcher is None:
            return None

        robots_url = self._robots_url(host)
        try:
            raw_bytes = self._fetcher(robots_url)
        except Exception as exc:
            logger.debug("robots.txt fetch failed for %s: %s", host, exc)
            return None

        if not _HAS_PROTEGO:
            return None  # permissive fallback — no parser available

        try:
            text = raw_bytes.decode("utf-8", errors="replace")
            return _protego.Protego.parse(text)
        except Exception as exc:  # pragma: no cover
            logger.debug("robots.txt parse failed for %s: %s", host, exc)
            return None

    def _get_parsed(self, host: str) -> Any:
        """Return cached or freshly fetched parsed robots object for *host*."""
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(host)
            if entry is not None:
                parsed, fetched_at = entry
                if now - fetched_at < self._ttl:
                    return parsed

        parsed = self._fetch_and_parse(host)
        with self._lock:
            self._cache[host] = (parsed, now)
        return parsed

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def allowed(self, url: str, user_agent: str | None = None) -> bool:
        """Return True if *url* is allowed for *user_agent* (or the instance default).

        When protego is absent or robots.txt fetch fails the policy is
        permissive (returns True) so the core fetch path is never blocked by a
        missing optional dependency.
        """
        parts = urlsplit(url)
        host = parts.netloc.lower().split(":")[0]
        ua = user_agent or self._user_agent

        parsed = self._get_parsed(host)
        if parsed is None:
            return True  # permissive fallback

        try:
            result = parsed.can_fetch(url, ua)
            return bool(result)
        except Exception as exc:  # pragma: no cover
            logger.debug("robots allowed() check failed for %s: %s", url, exc)
            return True

    def crawl_delay(self, host: str) -> float:
        """Return the Crawl-delay directive (seconds) for *host*, or 0.0.

        Uses the per-agent delay when available, falling back to the wildcard
        ``*`` delay. Returns 0.0 when protego is absent or robots.txt fetch
        fails.
        """
        parsed = self._get_parsed(host)
        if parsed is None:
            return 0.0

        try:
            # protego exposes .crawl_delay(ua) returning float|None
            delay = parsed.crawl_delay(self._user_agent)
            if delay is None:
                delay = parsed.crawl_delay("*")
            return float(delay) if delay is not None else 0.0
        except Exception as exc:  # pragma: no cover
            logger.debug("crawl_delay() failed for %s: %s", host, exc)
            return 0.0


# ---------------------------------------------------------------------------
# _PureTokenBucket — deterministic pure-python fallback
# ---------------------------------------------------------------------------


class _PureTokenBucket:
    """Minimal token-bucket rate limiter for one domain (no external deps).

    Uses a leaky-bucket / token refill algorithm: tokens refill continuously
    at *rate_per_second*, capped at *capacity*. ``acquire`` blocks until a
    token is available; ``try_acquire`` returns immediately.

    This implementation is intentionally simple and deterministic: the refill
    calculation uses ``time.monotonic()`` so it is immune to wall-clock changes.
    """

    def __init__(self, rate_per_second: float, capacity: float) -> None:
        self._rate = rate_per_second
        self._capacity = capacity
        self._tokens: float = capacity
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time (call with lock held)."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    def try_acquire(self) -> bool:
        """Attempt to consume one token; return True on success, False if empty."""
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def acquire(self) -> None:
        """Block until one token is available, then consume it."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            # Sleep a short interval and retry
            time.sleep(0.05)


# ---------------------------------------------------------------------------
# RateBudget — per-domain token bucket
# ---------------------------------------------------------------------------


class RateBudget:
    """Per-domain rate limiter backed by pyrate-limiter or a pure-python fallback.

    A new bucket is created on first access for each host. The default rate
    (1 request per second, burst of 5) is polite for most public APIs; callers
    can override *default_rate* and *default_burst* to relax or tighten this.

    When ``pyrate-limiter`` is installed it is used for its accurate sliding-
    window semantics. Without it the pure-Python token bucket in this module
    serves as a functionally equivalent fallback.
    """

    def __init__(
        self,
        default_rate: float = 1.0,
        default_burst: int = 5,
    ) -> None:
        """
        Parameters
        ----------
        default_rate:
            Sustained requests-per-second per domain.
        default_burst:
            Maximum burst capacity (tokens) per domain.
        """
        self._rate = default_rate
        self._burst = default_burst
        # host → bucket (either pyrate Limiter or _PureTokenBucket)
        self._buckets: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _bucket_for(self, host: str) -> Any:
        with self._lock:
            if host not in self._buckets:
                self._buckets[host] = self._make_bucket()
            return self._buckets[host]

    def _window_seconds(self) -> int:
        """Window (in seconds) for the pyrate-limiter Rate of ``burst`` requests.

        Guards two degenerate cases that would otherwise break the limiter:

        * ``rate <= 0`` — integer division ``burst / rate`` raises
          ``ZeroDivisionError``. Treat a non-positive rate as effectively
          unlimited by collapsing the window to its 1-second floor (burst
          requests are permitted immediately).
        * ``burst < rate`` — ``int(burst / rate)`` floors to ``0``, and
          ``Duration.SECOND * 0`` is an invalid (zero-length) window. Clamp the
          multiplier to ``>= 1`` so the Rate is always well-formed.
        """
        if self._rate <= 0:
            return 1
        return max(1, int(self._burst / self._rate))

    def _make_bucket(self) -> Any:
        if _HAS_PYRATE:
            # pyrate-limiter ≥ 3.x API: Rate + Limiter
            rate = Rate(self._burst, Duration.SECOND * self._window_seconds())
            return Limiter(rate)
        return _PureTokenBucket(self._rate, float(self._burst))

    def acquire(self, host: str) -> None:
        """Block until a request is permitted for *host*.

        With pyrate-limiter: calls ``limiter.try_acquire(host)`` in a spin with
        brief sleeps. With the pure-python bucket: calls ``bucket.acquire()``.
        """
        bucket = self._bucket_for(host)
        if _HAS_PYRATE:
            # pyrate-limiter raises BucketFullException when rate exceeded;
            # we retry until it succeeds.
            from pyrate_limiter import BucketFullException  # type: ignore[import-untyped]

            while True:
                try:
                    bucket.try_acquire(host)
                    return
                except BucketFullException:
                    time.sleep(0.05)
        else:
            bucket.acquire()

    def try_acquire(self, host: str) -> bool:
        """Non-blocking acquire; returns True if permitted, False if rate-limited.

        With pyrate-limiter: returns False on BucketFullException.
        With the pure-python bucket: delegates to ``try_acquire()``.
        """
        bucket = self._bucket_for(host)
        if _HAS_PYRATE:
            from pyrate_limiter import BucketFullException  # type: ignore[import-untyped]

            try:
                bucket.try_acquire(host)
                return True
            except BucketFullException:
                return False
        else:
            return bucket.try_acquire()


# ---------------------------------------------------------------------------
# PolitenessGate — combined robots + rate-budget check
# ---------------------------------------------------------------------------


class PolitenessGate:
    """Combine robots.txt policy and per-domain rate limiting into one decision.

    ``PolitenessGate`` is the public API consumed by
    :class:`~lighthouse_ai.net.EgressGuardedClient`. Call :meth:`check` before
    making a request; it will:

    1. Consult :class:`RobotsPolicy` — a disallowed path raises
       :class:`~lighthouse_ai.net.EgressBlocked`.
    2. Call :meth:`RateBudget.acquire` — blocks until capacity is available.

    Both components are optional in the constructor; when omitted the gate is
    fully permissive (no robots check, no rate limiting).

    Design notes
    ------------
    * ``check`` raises ``EgressBlocked`` (imported lazily to avoid a circular
      import) rather than returning a verdict; callers need no ``if`` check and
      the stack trace points directly at the disallowing rule.
    * Every decision is logged at DEBUG level for observability.
    * The gate is deterministic given the same robots bytes and token bucket
      state — no hidden randomness, no wall-clock sensitivity beyond what the
      token bucket already requires.
    """

    def __init__(
        self,
        robots: RobotsPolicy | None = None,
        budget: RateBudget | None = None,
        *,
        user_agent: str = "LighthouseBot",
    ) -> None:
        """
        Parameters
        ----------
        robots:
            A :class:`RobotsPolicy` instance.  When ``None`` the robots check
            is skipped (permissive).
        budget:
            A :class:`RateBudget` instance.  When ``None`` rate limiting is
            skipped.
        user_agent:
            The user-agent string used for robots.txt allow/deny checks.
        """
        self._robots = robots
        self._budget = budget
        self._user_agent = user_agent

    def check(self, url: str) -> None:
        """Enforce politeness for *url*, blocking or raising as necessary.

        Raises :class:`~lighthouse_ai.net.EgressBlocked` if the robots policy
        disallows the URL. Blocks (via rate budget) if the per-domain token
        bucket is empty. Returns normally when the request may proceed.
        """
        # Lazy import to avoid circular dependency: net imports net_politeness,
        # net_politeness must not import net at module level.
        from lighthouse_ai.net import EgressBlocked

        parts = urlsplit(url)
        host = parts.netloc.lower().split(":")[0]

        # 1. Robots check
        if self._robots is not None:
            is_allowed = self._robots.allowed(url, self._user_agent)
            if not is_allowed:
                reason = f"robots.txt disallows {url!r} for agent {self._user_agent!r}"
                logger.debug("PolitenessGate: BLOCKED — %s", reason)
                raise EgressBlocked(reason)
            logger.debug("PolitenessGate: robots OK for %s", url)

        # 2. Rate budget
        if self._budget is not None:
            logger.debug("PolitenessGate: acquiring rate token for %s", host)
            self._budget.acquire(host)
            logger.debug("PolitenessGate: rate token acquired for %s", host)
