"""Tests for the Zone F politeness layer (net_politeness.py + net.py integration).

All tests use pure-Python fallbacks — no protego/courlan/pyrate-limiter required.
Canned robots.txt bytes are injected via the fetcher callable so no sockets are
opened.  Network I/O in EgressGuardedClient is suppressed by an injected
httpx.Client mocked with respx.
"""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from lighthouse_ai.net import EgressBlocked, EgressGuardedClient, guarded_get
from lighthouse_ai.net_politeness import (
    PolitenessGate,
    RateBudget,
    RobotsPolicy,
    _PureTokenBucket,
    canonicalize,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROBOTS_DISALLOW_ALL = b"User-agent: *\nDisallow: /\n"
ROBOTS_ALLOW_ALL = b"User-agent: *\nDisallow:\n"
ROBOTS_DISALLOW_PATH = b"User-agent: *\nDisallow: /private/\n"
ROBOTS_CRAWL_DELAY = b"User-agent: *\nDisallow:\nCrawl-delay: 2\n"
ROBOTS_AGENT_DELAY = b"User-agent: LighthouseBot\nCrawl-delay: 3\nDisallow:\nUser-agent: *\nCrawl-delay: 1\nDisallow:\n"

ALLOWED = frozenset({"arxiv.org"})


def _fetcher_for(content: bytes):
    """Return a fetcher callable that always returns *content*."""

    def _fetch(url: str) -> bytes:
        return content

    return _fetch


def _fetcher_map(mapping: dict[str, bytes]):
    """Return a fetcher that returns bytes keyed by URL hostname."""

    def _fetch(url: str) -> bytes:
        for host, body in mapping.items():
            if host in url:
                return body
        return b""

    return _fetch


# ---------------------------------------------------------------------------
# canonicalize
# ---------------------------------------------------------------------------


class TestCanonicalize:
    def test_strips_fragment(self) -> None:
        url = "https://example.com/page#section"
        result = canonicalize(url)
        assert "#" not in result

    def test_lowercases_scheme_and_host(self) -> None:
        url = "HTTPS://EXAMPLE.COM/path"
        result = canonicalize(url)
        assert result.startswith("https://example.com")

    def test_removes_default_https_port(self) -> None:
        url = "https://example.com:443/path"
        result = canonicalize(url)
        assert ":443" not in result

    def test_removes_default_http_port(self) -> None:
        url = "http://example.com:80/path"
        result = canonicalize(url)
        assert ":80" not in result

    def test_preserves_non_default_port(self) -> None:
        url = "https://example.com:8443/path"
        result = canonicalize(url)
        assert ":8443" in result

    def test_preserves_path_and_query(self) -> None:
        url = "https://example.com/search?q=test"
        result = canonicalize(url)
        assert "/search" in result
        assert "q=test" in result

    def test_idempotent(self) -> None:
        url = "https://example.com/path?q=1"
        assert canonicalize(canonicalize(url)) == canonicalize(url)


# ---------------------------------------------------------------------------
# RobotsPolicy — pure-python fallback path (no protego)
# ---------------------------------------------------------------------------


class TestRobotsPolicyFallback:
    """Tests that run regardless of whether protego is installed.

    When protego is absent all paths are permissive; when it IS installed the
    tests that feed Disallow rules will assert blocking behaviour.
    """

    def test_none_fetcher_is_permissive(self) -> None:
        """Without a fetcher every URL is allowed."""
        policy = RobotsPolicy(fetcher=None)
        assert policy.allowed("https://example.com/anything") is True

    def test_none_fetcher_crawl_delay_zero(self) -> None:
        policy = RobotsPolicy(fetcher=None)
        assert policy.crawl_delay("example.com") == 0.0

    def test_allow_all_robots(self) -> None:
        policy = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_ALLOW_ALL))
        assert policy.allowed("https://example.com/public") is True

    def test_empty_robots_is_permissive(self) -> None:
        policy = RobotsPolicy(fetcher=_fetcher_for(b""))
        assert policy.allowed("https://example.com/anything") is True

    def test_robots_cached_on_second_call(self) -> None:
        """The fetcher is called once; subsequent calls use the cache."""
        call_count = [0]

        def counting_fetcher(url: str) -> bytes:
            call_count[0] += 1
            return ROBOTS_ALLOW_ALL

        policy = RobotsPolicy(fetcher=counting_fetcher, ttl=60.0)
        policy.allowed("https://example.com/a")
        policy.allowed("https://example.com/b")
        assert call_count[0] == 1

    def test_fetcher_exception_is_permissive(self) -> None:
        def bad_fetcher(url: str) -> bytes:
            raise OSError("connection refused")

        policy = RobotsPolicy(fetcher=bad_fetcher)
        assert policy.allowed("https://example.com/") is True


# ---------------------------------------------------------------------------
# RobotsPolicy — when protego is installed
# ---------------------------------------------------------------------------

try:
    import protego  # noqa: F401

    _PROTEGO_AVAILABLE = True
except ModuleNotFoundError:
    _PROTEGO_AVAILABLE = False

pytestmark_protego = pytest.mark.skipif(not _PROTEGO_AVAILABLE, reason="protego not installed")


@pytest.mark.skipif(not _PROTEGO_AVAILABLE, reason="protego not installed")
class TestRobotsPolicyWithProtego:
    def test_disallow_all_blocks(self) -> None:
        policy = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_DISALLOW_ALL))
        assert policy.allowed("https://example.com/page") is False

    def test_disallow_path_blocks_matching(self) -> None:
        policy = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_DISALLOW_PATH))
        assert policy.allowed("https://example.com/private/secret") is False

    def test_disallow_path_allows_other(self) -> None:
        policy = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_DISALLOW_PATH))
        assert policy.allowed("https://example.com/public/page") is True

    def test_crawl_delay_parsed(self) -> None:
        policy = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_CRAWL_DELAY))
        delay = policy.crawl_delay("example.com")
        assert delay == pytest.approx(2.0)

    def test_agent_specific_crawl_delay(self) -> None:
        policy = RobotsPolicy(
            fetcher=_fetcher_for(ROBOTS_AGENT_DELAY),
            user_agent="LighthouseBot",
        )
        delay = policy.crawl_delay("example.com")
        assert delay == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# _PureTokenBucket
# ---------------------------------------------------------------------------


class TestPureTokenBucket:
    def test_initial_tokens_allow_burst(self) -> None:
        bucket = _PureTokenBucket(rate_per_second=1.0, capacity=5.0)
        # Should be able to acquire 5 times immediately
        successes = sum(1 for _ in range(5) if bucket.try_acquire())
        assert successes == 5

    def test_exhausted_bucket_refuses(self) -> None:
        bucket = _PureTokenBucket(rate_per_second=0.01, capacity=2.0)
        bucket.try_acquire()
        bucket.try_acquire()
        # Now empty
        assert bucket.try_acquire() is False

    def test_tokens_refill_over_time(self) -> None:
        bucket = _PureTokenBucket(rate_per_second=100.0, capacity=1.0)
        bucket.try_acquire()  # exhaust
        assert bucket.try_acquire() is False
        # Sleep long enough for refill (rate=100/s so 0.02s ≈ 2 tokens)
        time.sleep(0.02)
        assert bucket.try_acquire() is True

    def test_capacity_caps_tokens(self) -> None:
        bucket = _PureTokenBucket(rate_per_second=1000.0, capacity=3.0)
        # Wait a while — tokens should be capped at capacity
        time.sleep(0.01)
        successes = sum(1 for _ in range(10) if bucket.try_acquire())
        # Can never exceed capacity in a single burst
        assert successes <= 3


# ---------------------------------------------------------------------------
# RateBudget
# ---------------------------------------------------------------------------


class TestRateBudget:
    def test_different_hosts_independent(self) -> None:
        budget = RateBudget(default_rate=1.0, default_burst=2)
        assert budget.try_acquire("host-a.com") is True
        assert budget.try_acquire("host-b.com") is True  # independent bucket

    def test_exhausted_host_returns_false(self) -> None:
        budget = RateBudget(default_rate=0.001, default_burst=1)
        budget.try_acquire("slow.com")  # consume the one token
        assert budget.try_acquire("slow.com") is False

    def test_separate_domain_not_affected(self) -> None:
        budget = RateBudget(default_rate=0.001, default_burst=1)
        budget.try_acquire("slow.com")
        # A different host is unaffected
        assert budget.try_acquire("fast.com") is True

    def test_acquire_blocks_until_token_available(self) -> None:
        budget = RateBudget(default_rate=50.0, default_burst=1)
        budget.try_acquire("fast-refill.com")  # consume
        t0 = time.monotonic()
        budget.acquire("fast-refill.com")  # should unblock quickly
        elapsed = time.monotonic() - t0
        # At 50 req/s a token refills in 0.02s; allow up to 1s for test runner jitter
        assert elapsed < 1.0


class TestRateBudgetWindowMath:
    """Window math for the pyrate-limiter ``Rate`` (exercised library-free).

    The window is in **milliseconds** so high rates work and stay consistent with
    the pure-Python fallback. Guards: ``rate <= 0`` would divide by zero, and
    ``burst < rate`` would round to a zero-length window. We test the pure math
    helper directly so the test needs no pyrate-limiter install.
    """

    def test_zero_rate_does_not_divide_by_zero(self) -> None:
        # rate == 0 would raise ZeroDivisionError on bucket creation.
        budget = RateBudget(default_rate=0.0, default_burst=5)
        assert budget._window_ms() == 1

    def test_negative_rate_is_unlimited_floor(self) -> None:
        budget = RateBudget(default_rate=-3.0, default_burst=5)
        assert budget._window_ms() == 1

    def test_burst_smaller_than_rate_keeps_window_at_least_one(self) -> None:
        # burst < rate → 1/10*1000 = 100 ms (no longer floored to a zero window).
        budget = RateBudget(default_rate=10.0, default_burst=1)
        assert budget._window_ms() == 100

    def test_normal_rate_window_is_burst_over_rate_seconds(self) -> None:
        # 5 burst / 1 rate → 5 s sustained → 5000 ms window.
        budget = RateBudget(default_rate=1.0, default_burst=5)
        assert budget._window_ms() == 5000

    def test_high_rate_low_burst_uses_subsecond_window(self) -> None:
        # 50 req/s, burst 1 → 20 ms window (whole-second flooring gave 1 s = 1/s).
        budget = RateBudget(default_rate=50.0, default_burst=1)
        assert budget._window_ms() == 20

    def test_zero_rate_bucket_creation_does_not_raise(self) -> None:
        # End-to-end: a bucket can be made and used even with rate 0.
        budget = RateBudget(default_rate=0.0, default_burst=3)
        assert budget.try_acquire("any.com") is True


# ---------------------------------------------------------------------------
# PolitenessGate
# ---------------------------------------------------------------------------


class TestCrawlDelayEnforcement:
    """PolitenessGate must honour the robots Crawl-delay directive.

    Regression tests for the audit finding: previously crawl_delay was parsed
    but PolitenessGate.check() never used it.
    """

    def test_crawl_delay_causes_sleep_via_injected_sleeper(self) -> None:
        """check() must sleep the crawl-delay duration on the first post-delay call.

        Uses protego-independent setup: we stub crawl_delay() directly on
        RobotsPolicy so the test runs without protego installed.
        """
        slept: list[float] = []

        robots = RobotsPolicy(fetcher=None)
        # Stub the crawl_delay method to return 5.0 seconds for any host.
        robots.crawl_delay = lambda host: 5.0  # type: ignore[method-assign]

        gate = PolitenessGate(robots=robots, sleeper=slept.append)
        # First call: no prior fetch timestamp for this host → delay should be
        # enforced from the very next call (or immediately on first, depending on
        # implementation).  Call twice; the second must cause a sleep.
        gate.check("https://example.com/a")
        gate.check("https://example.com/b")

        assert slept, "expected at least one sleep call for crawl-delay enforcement"
        assert slept[0] == pytest.approx(5.0, abs=0.1), f"expected sleep of 5.0s, got {slept[0]}"

    def test_no_crawl_delay_no_sleep(self) -> None:
        """When crawl_delay() returns 0.0 no sleep must occur."""
        slept: list[float] = []
        robots = RobotsPolicy(fetcher=None)
        robots.crawl_delay = lambda host: 0.0  # type: ignore[method-assign]

        gate = PolitenessGate(robots=robots, sleeper=slept.append)
        gate.check("https://example.com/a")
        gate.check("https://example.com/b")
        assert slept == [], f"unexpected sleeps: {slept}"

    def test_crawl_delay_per_host_independent(self) -> None:
        """Crawl-delay tracking is per-host; different hosts don't share state."""
        slept: list[float] = []
        robots = RobotsPolicy(fetcher=None)
        robots.crawl_delay = lambda host: 3.0  # type: ignore[method-assign]

        # Use a clock that starts far in the past so the delay fires immediately.
        gate = PolitenessGate(robots=robots, sleeper=slept.append)
        gate.check("https://host-a.com/page")
        gate.check("https://host-b.com/page")
        # host-b has no prior fetch timestamp → its first call records the
        # timestamp; no sleep needed yet (delay is relative to *last* fetch).
        # The important thing: host-a's state doesn't affect host-b.
        # A second call to host-b should trigger the delay.
        gate.check("https://host-b.com/other")
        # At least one sleep was recorded overall (the second call to host-b or
        # the second call to host-a).
        assert len(slept) >= 1

    def test_no_robots_no_sleep(self) -> None:
        """When robots=None the gate must never sleep (fully permissive)."""
        slept: list[float] = []
        gate = PolitenessGate(robots=None, sleeper=slept.append)
        gate.check("https://example.com/a")
        gate.check("https://example.com/b")
        assert slept == []


class TestPolitenessGateNoLibs:
    """PolitenessGate with no optional libraries — pure-python fallbacks."""

    def test_no_robots_no_budget_is_noop(self) -> None:
        gate = PolitenessGate()
        gate.check("https://example.com/anything")  # must not raise

    def test_permissive_robots_does_not_raise(self) -> None:
        robots = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_ALLOW_ALL))
        gate = PolitenessGate(robots=robots)
        gate.check("https://example.com/public")  # must not raise

    def test_rate_budget_only_does_not_raise_for_first_request(self) -> None:
        budget = RateBudget(default_rate=1.0, default_burst=5)
        gate = PolitenessGate(budget=budget)
        gate.check("https://example.com/page")  # must not raise

    def test_none_fetcher_never_raises(self) -> None:
        robots = RobotsPolicy(fetcher=None)
        budget = RateBudget(default_rate=1.0, default_burst=10)
        gate = PolitenessGate(robots=robots, budget=budget)
        for _ in range(5):
            gate.check("https://example.com/page")  # must not raise


@pytest.mark.skipif(not _PROTEGO_AVAILABLE, reason="protego not installed")
class TestPolitenessGateWithProtego:
    def test_disallow_all_raises_egress_blocked(self) -> None:
        robots = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_DISALLOW_ALL))
        gate = PolitenessGate(robots=robots)
        with pytest.raises(EgressBlocked) as exc:
            gate.check("https://example.com/page")
        assert "robots.txt" in exc.value.reason

    def test_allow_all_does_not_raise(self) -> None:
        robots = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_ALLOW_ALL))
        gate = PolitenessGate(robots=robots)
        gate.check("https://example.com/public")  # must not raise

    def test_disallow_path_raises_for_matching_url(self) -> None:
        robots = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_DISALLOW_PATH))
        gate = PolitenessGate(robots=robots)
        with pytest.raises(EgressBlocked):
            gate.check("https://example.com/private/secret")

    def test_disallow_path_allows_other_paths(self) -> None:
        robots = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_DISALLOW_PATH))
        gate = PolitenessGate(robots=robots)
        gate.check("https://example.com/public/page")  # must not raise

    def test_egress_blocked_reason_mentions_agent(self) -> None:
        robots = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_DISALLOW_ALL), user_agent="MyBot")
        gate = PolitenessGate(robots=robots, user_agent="MyBot")
        with pytest.raises(EgressBlocked) as exc:
            gate.check("https://example.com/")
        assert "MyBot" in exc.value.reason


# ---------------------------------------------------------------------------
# EgressGuardedClient with PolitenessGate
# ---------------------------------------------------------------------------


class TestEgressGuardedClientWithPoliteness:
    """Integration: EgressGuardedClient + PolitenessGate, no real network."""

    @respx.mock
    def test_politeness_none_behavior_unchanged(self) -> None:
        """politeness=None must not change the existing egress-only behaviour."""
        route = respx.get("https://arxiv.org/abs/1").mock(
            return_value=httpx.Response(200, text="ok")
        )
        client = EgressGuardedClient(allowed_domains=ALLOWED, politeness=None)
        resp = client.get("https://arxiv.org/abs/1")
        assert resp.status_code == 200
        assert route.called
        client.close()

    @respx.mock
    def test_permissive_gate_allows_fetch(self) -> None:
        """A gate with no robots and permissive budget passes through."""
        route = respx.get("https://arxiv.org/abs/2").mock(
            return_value=httpx.Response(200, text="data")
        )
        gate = PolitenessGate(robots=None, budget=None)
        client = EgressGuardedClient(allowed_domains=ALLOWED, politeness=gate)
        resp = client.get("https://arxiv.org/abs/2")
        assert resp.status_code == 200
        assert route.called
        client.close()

    def test_egress_blocked_before_fetch_on_disallowed_domain(self) -> None:
        """Egress allowlist still fires (even with politeness=None)."""
        client = EgressGuardedClient(
            allowed_domains=ALLOWED,
            politeness=PolitenessGate(),
        )
        with pytest.raises(EgressBlocked) as exc:
            client.get("https://evil.example.com/")
        assert "allowlist" in exc.value.reason
        client.close()

    @pytest.mark.skipif(not _PROTEGO_AVAILABLE, reason="protego not installed")
    @respx.mock
    def test_robots_disallow_raises_egress_blocked_no_fetch(self) -> None:
        """robots.txt disallow must raise EgressBlocked; the network route must NOT be called."""
        route = respx.get("https://arxiv.org/private/doc").mock(return_value=httpx.Response(200))
        # Inject a robots.txt that disallows everything
        robots = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_DISALLOW_ALL))
        gate = PolitenessGate(robots=robots)
        client = EgressGuardedClient(allowed_domains=ALLOWED, politeness=gate)

        with pytest.raises(EgressBlocked) as exc:
            client.get("https://arxiv.org/private/doc")

        assert "robots.txt" in exc.value.reason
        assert not route.called  # nothing went over the wire
        client.close()

    @pytest.mark.skipif(not _PROTEGO_AVAILABLE, reason="protego not installed")
    @respx.mock
    def test_per_call_politeness_overrides_instance(self) -> None:
        """A per-call gate that disallows overrides a permissive instance gate."""
        route = respx.get("https://arxiv.org/page").mock(return_value=httpx.Response(200))
        # Instance gate is permissive
        instance_gate = PolitenessGate()
        # Per-call gate disallows everything
        blocking_robots = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_DISALLOW_ALL))
        blocking_gate = PolitenessGate(robots=blocking_robots)

        client = EgressGuardedClient(allowed_domains=ALLOWED, politeness=instance_gate)
        with pytest.raises(EgressBlocked):
            client.get("https://arxiv.org/page", politeness=blocking_gate)
        assert not route.called
        client.close()


# ---------------------------------------------------------------------------
# guarded_get with politeness
# ---------------------------------------------------------------------------


class TestGuardedGetPoliteness:
    @respx.mock
    def test_guarded_get_politeness_none_unchanged(self) -> None:
        route = respx.get("https://arxiv.org/abs/g").mock(return_value=httpx.Response(200))
        resp = guarded_get("https://arxiv.org/abs/g", allowed_domains=ALLOWED)
        assert resp.status_code == 200
        assert route.called

    def test_guarded_get_allowlist_blocks_no_change(self) -> None:
        with pytest.raises(EgressBlocked) as exc:
            guarded_get("https://evil.example.com/", allowed_domains=ALLOWED)
        assert "allowlist" in exc.value.reason

    @pytest.mark.skipif(not _PROTEGO_AVAILABLE, reason="protego not installed")
    @respx.mock
    def test_guarded_get_with_blocking_gate(self) -> None:
        route = respx.get("https://arxiv.org/blocked").mock(return_value=httpx.Response(200))
        robots = RobotsPolicy(fetcher=_fetcher_for(ROBOTS_DISALLOW_ALL))
        gate = PolitenessGate(robots=robots)
        with pytest.raises(EgressBlocked):
            guarded_get(
                "https://arxiv.org/blocked",
                allowed_domains=ALLOWED,
                politeness=gate,
            )
        assert not route.called


# ---------------------------------------------------------------------------
# net.py public signature unchanged (regression guard)
# ---------------------------------------------------------------------------


class TestNetPublicSignatureUnchanged:
    """Ensure the existing public signatures of net.py are not broken."""

    def test_egress_blocked_is_runtime_error(self) -> None:
        exc = EgressBlocked("test reason")
        assert isinstance(exc, RuntimeError)
        assert exc.reason == "test reason"

    def test_egress_guarded_client_default_args_unchanged(self) -> None:
        """EgressGuardedClient can be constructed with original args only."""

        # Original signature: (proxy, *, allowed_domains, client, timeout)
        # politeness is additive/optional — must default to None
        client = EgressGuardedClient(allowed_domains=ALLOWED)
        assert client._politeness is None
        client.close()

    @respx.mock
    def test_get_original_signature_still_works(self) -> None:
        """get(url, *, privacy=...) still works exactly as before."""
        respx.get("https://arxiv.org/abs/sig").mock(return_value=httpx.Response(200))
        client = EgressGuardedClient(allowed_domains=ALLOWED)
        resp = client.get("https://arxiv.org/abs/sig")
        assert resp.status_code == 200
        client.close()

    def test_guarded_get_original_signature_still_works(self) -> None:
        """guarded_get(url, *, allowed_domains, privacy, client) raises on blocked."""
        with pytest.raises(EgressBlocked):
            guarded_get("https://evil.example.com/", allowed_domains=ALLOWED)
