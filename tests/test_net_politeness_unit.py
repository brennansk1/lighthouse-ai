"""Focused unit tests for ``lighthouse_ai.net_politeness`` (Zone F politeness layer).

Complements tests/test_politeness.py (integration-leaning, real sleeps) with
deterministic unit coverage:

* an injected fake monotonic clock instead of wall-clock sleeps;
* stubbed robots/budget collaborators to pin the PolitenessGate decision order;
* forced-fallback tests that monkeypatch the optional-dep flags
  (``_HAS_PROTEGO`` / ``_HAS_COURLAN`` / ``_HAS_PYRATE``) so the no-deps paths
  run unconditionally, even on machines where the libraries ARE installed;
* with-deps tests guarded by ``pytest.importorskip`` (skipped when absent).

No sockets are opened anywhere; robots.txt bytes are always injected via the
fetcher callable.
"""

from __future__ import annotations

import time

import pytest

import lighthouse_ai.net_politeness as np
from lighthouse_ai.net import EgressBlocked
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
ROBOTS_CRAWL_DELAY = b"User-agent: *\nDisallow:\nCrawl-delay: 7\n"
ROBOTS_AGENT_SPLIT = b"User-agent: BadBot\nDisallow: /\n\nUser-agent: *\nDisallow:\n"


class FakeClock:
    """Controllable monotonic clock for deterministic refill/crawl-delay tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Replace ``time.monotonic`` (as used by net_politeness) with a fake clock."""
    fake = FakeClock()
    monkeypatch.setattr(time, "monotonic", fake)
    return fake


def _stub_robots(*, allow: bool = True, delay: float = 0.0) -> RobotsPolicy:
    """RobotsPolicy whose verdicts are fixed — runs without protego installed."""
    robots = RobotsPolicy(fetcher=None)
    robots.allowed = lambda url, user_agent=None: allow  # type: ignore[method-assign]
    robots.crawl_delay = lambda host: delay  # type: ignore[method-assign]
    return robots


class _RecordingBudget(RateBudget):
    """RateBudget that records acquire() hosts instead of rate-limiting."""

    def __init__(self) -> None:
        super().__init__()
        self.acquired: list[str] = []

    def acquire(self, host: str) -> None:
        self.acquired.append(host)


# ---------------------------------------------------------------------------
# canonicalize — stdlib fallback path (forced, runs with or without courlan)
# ---------------------------------------------------------------------------


def test_canonicalize_fallback_preserves_path_and_query_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only scheme+host are lowercased; path and query case is significant."""
    monkeypatch.setattr(np, "_HAS_COURLAN", False)
    result = canonicalize("HTTPS://Example.COM/CaseSensitive/Path?Query=Value")
    assert result.startswith("https://example.com/")
    assert "/CaseSensitive/Path" in result
    assert "Query=Value" in result


def test_canonicalize_fallback_keeps_mismatched_default_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """:443 is only a default for https, :80 only for http — mismatches survive."""
    monkeypatch.setattr(np, "_HAS_COURLAN", False)
    assert ":443" in canonicalize("http://example.com:443/path")
    assert ":80" in canonicalize("https://example.com:80/path")


def test_canonicalize_fallback_strips_fragment_keeps_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(np, "_HAS_COURLAN", False)
    result = canonicalize("https://example.com/page?q=1#section-2")
    assert "#" not in result
    assert "q=1" in result


def test_canonicalize_fallback_empty_fragment_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(np, "_HAS_COURLAN", False)
    assert canonicalize("https://example.com/page#") == "https://example.com/page"


def test_canonicalize_fallback_schemeless_url_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A schemeless input is degenerate but must stay deterministic and not raise."""
    monkeypatch.setattr(np, "_HAS_COURLAN", False)
    result = canonicalize("example.com/path")
    assert isinstance(result, str)
    assert canonicalize(result) == result  # idempotent


def test_canonicalize_with_courlan_strips_fragment() -> None:
    """When courlan IS installed the fragment is still stripped explicitly."""
    pytest.importorskip("courlan")
    result = canonicalize("https://example.com/page#anchor")
    assert "#" not in result
    assert "example.com" in result


# ---------------------------------------------------------------------------
# RobotsPolicy — fetch plumbing and cache mechanics (dep-free)
# ---------------------------------------------------------------------------


def test_robots_fetcher_receives_robots_url_for_bare_lowercased_host() -> None:
    """The fetcher gets https://<host>/robots.txt with port stripped, host lowered."""
    fetched: list[str] = []

    def fetcher(url: str) -> bytes:
        fetched.append(url)
        return b""

    policy = RobotsPolicy(fetcher=fetcher)
    policy.allowed("https://EXAMPLE.com:8443/some/page")
    assert fetched == ["https://example.com/robots.txt"]


def test_robots_cache_expires_after_ttl(clock: FakeClock) -> None:
    """A cached robots entry is re-fetched once the TTL has elapsed."""
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return b""

    policy = RobotsPolicy(fetcher=fetcher, ttl=10.0)
    policy.allowed("https://example.com/a")
    clock.advance(9.0)
    policy.allowed("https://example.com/b")  # within TTL — cache hit
    assert len(calls) == 1
    clock.advance(2.0)  # total 11s > ttl
    policy.allowed("https://example.com/c")
    assert len(calls) == 2


def test_robots_failed_fetch_is_cached_within_ttl() -> None:
    """A failing fetcher is not hammered: the None result is cached like a success."""
    calls: list[str] = []

    def bad_fetcher(url: str) -> bytes:
        calls.append(url)
        raise OSError("connection refused")

    policy = RobotsPolicy(fetcher=bad_fetcher, ttl=60.0)
    assert policy.allowed("https://example.com/a") is True  # permissive on failure
    assert policy.allowed("https://example.com/b") is True
    assert len(calls) == 1


def test_robots_cache_is_per_host() -> None:
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return b""

    policy = RobotsPolicy(fetcher=fetcher)
    policy.allowed("https://host-a.example/x")
    policy.allowed("https://host-b.example/x")
    assert calls == [
        "https://host-a.example/robots.txt",
        "https://host-b.example/robots.txt",
    ]


def test_robots_disallow_bytes_permissive_when_protego_forced_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without protego even a Disallow-all robots.txt degrades to permissive."""
    monkeypatch.setattr(np, "_HAS_PROTEGO", False)
    policy = RobotsPolicy(fetcher=lambda url: ROBOTS_DISALLOW_ALL)
    assert policy.allowed("https://example.com/secret") is True


def test_robots_crawl_delay_zero_when_protego_forced_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without protego a Crawl-delay directive degrades to 0.0 (no throttling)."""
    monkeypatch.setattr(np, "_HAS_PROTEGO", False)
    policy = RobotsPolicy(fetcher=lambda url: ROBOTS_CRAWL_DELAY)
    assert policy.crawl_delay("example.com") == 0.0


def test_robots_allowed_user_agent_override_with_protego() -> None:
    """The per-call user_agent overrides the instance default (protego path)."""
    pytest.importorskip("protego")
    policy = RobotsPolicy(fetcher=lambda url: ROBOTS_AGENT_SPLIT, user_agent="GoodBot")
    assert policy.allowed("https://example.com/x") is True
    assert policy.allowed("https://example.com/x", user_agent="BadBot") is False


# ---------------------------------------------------------------------------
# _PureTokenBucket — deterministic refill with an injected clock
# ---------------------------------------------------------------------------


def test_bucket_refill_is_proportional_to_elapsed_time(clock: FakeClock) -> None:
    """At 2 tokens/s, 0.4s gives 0.8 tokens (refused); 0.5s gives a full token."""
    bucket = _PureTokenBucket(rate_per_second=2.0, capacity=1.0)
    assert bucket.try_acquire() is True  # exhaust the initial token
    clock.advance(0.4)
    assert bucket.try_acquire() is False  # only 0.8 tokens refilled
    clock.advance(0.1)
    assert bucket.try_acquire() is True  # 1.0 tokens now available


def test_bucket_refill_caps_at_capacity(clock: FakeClock) -> None:
    """A long idle period never grants more than `capacity` tokens."""
    bucket = _PureTokenBucket(rate_per_second=10.0, capacity=3.0)
    for _ in range(3):
        assert bucket.try_acquire() is True
    clock.advance(3600.0)  # would refill 36000 tokens uncapped
    successes = sum(1 for _ in range(10) if bucket.try_acquire())
    assert successes == 3


def test_bucket_acquire_spins_until_refill_without_real_sleep(
    clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """acquire() blocks via sleep-and-retry; with a fake sleep that advances the
    clock it terminates after exactly the simulated refill interval."""
    bucket = _PureTokenBucket(rate_per_second=2.0, capacity=1.0)
    assert bucket.try_acquire() is True  # empty the bucket

    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)

    monkeypatch.setattr(time, "sleep", fake_sleep)
    bucket.acquire()  # must terminate once 0.5 simulated seconds have passed
    assert sleeps, "acquire() should have waited for a refill"
    assert sum(sleeps) == pytest.approx(0.5, abs=0.05)


# ---------------------------------------------------------------------------
# RateBudget — bucket selection and deterministic refill (fallback forced)
# ---------------------------------------------------------------------------


def test_rate_budget_uses_pure_bucket_when_pyrate_forced_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(np, "_HAS_PYRATE", False)
    budget = RateBudget(default_rate=1.0, default_burst=2)
    bucket = budget._bucket_for("example.com")
    assert isinstance(bucket, _PureTokenBucket)


def test_rate_budget_bucket_reused_per_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(np, "_HAS_PYRATE", False)
    budget = RateBudget(default_rate=1.0, default_burst=2)
    assert budget._bucket_for("example.com") is budget._bucket_for("example.com")
    assert budget._bucket_for("example.com") is not budget._bucket_for("other.com")


def test_rate_budget_refills_deterministically(
    clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forced pure-python path: an exhausted host recovers after 1/rate seconds."""
    monkeypatch.setattr(np, "_HAS_PYRATE", False)
    budget = RateBudget(default_rate=1.0, default_burst=1)
    assert budget.try_acquire("example.com") is True
    assert budget.try_acquire("example.com") is False
    clock.advance(1.0)
    assert budget.try_acquire("example.com") is True


def test_rate_budget_with_pyrate_exhaustion_returns_false() -> None:
    """pyrate-limiter path: burst is honoured and try_acquire degrades to False."""
    pytest.importorskip("pyrate_limiter")
    budget = RateBudget(default_rate=0.001, default_burst=1)
    assert budget.try_acquire("slow.example") is True
    assert budget.try_acquire("slow.example") is False
    assert budget.try_acquire("other.example") is True  # independent host


# ---------------------------------------------------------------------------
# PolitenessGate — construction and configuration
# ---------------------------------------------------------------------------


def test_gate_default_sleeper_is_time_sleep() -> None:
    gate = PolitenessGate()
    assert gate._sleeper is time.sleep


def test_gate_passes_default_user_agent_to_robots() -> None:
    seen: list[str | None] = []
    robots = RobotsPolicy(fetcher=None)
    robots.allowed = (  # type: ignore[method-assign]
        lambda url, user_agent=None: seen.append(user_agent) or True
    )
    gate = PolitenessGate(robots=robots)
    gate.check("https://example.com/x")
    assert seen == ["LighthouseBot"]


def test_gate_passes_custom_user_agent_to_robots() -> None:
    seen: list[str | None] = []
    robots = RobotsPolicy(fetcher=None)
    robots.allowed = (  # type: ignore[method-assign]
        lambda url, user_agent=None: seen.append(user_agent) or True
    )
    gate = PolitenessGate(robots=robots, user_agent="MyBot/2.0")
    gate.check("https://example.com/x")
    assert seen == ["MyBot/2.0"]


# ---------------------------------------------------------------------------
# PolitenessGate — EgressBlocked raising path (no optional deps required)
# ---------------------------------------------------------------------------


def test_gate_robots_deny_raises_egress_blocked() -> None:
    """A denying robots verdict raises EgressBlocked — exercised dep-free via stub."""
    gate = PolitenessGate(robots=_stub_robots(allow=False), user_agent="TestBot")
    with pytest.raises(EgressBlocked) as exc:
        gate.check("https://example.com/private")
    assert "robots.txt" in exc.value.reason
    assert "https://example.com/private" in exc.value.reason
    assert "TestBot" in exc.value.reason


def test_gate_robots_deny_skips_rate_budget() -> None:
    """Decision order: a robots block must short-circuit before the rate budget."""
    budget = _RecordingBudget()
    gate = PolitenessGate(robots=_stub_robots(allow=False), budget=budget)
    with pytest.raises(EgressBlocked):
        gate.check("https://example.com/x")
    assert budget.acquired == []


def test_gate_budget_receives_bare_lowercased_host() -> None:
    """The rate budget is keyed by bare host: lowercased, port stripped."""
    budget = _RecordingBudget()
    gate = PolitenessGate(budget=budget)
    gate.check("https://EXAMPLE.com:8443/some/page")
    assert budget.acquired == ["example.com"]


def test_gate_allowed_url_acquires_budget_token() -> None:
    budget = _RecordingBudget()
    gate = PolitenessGate(robots=_stub_robots(allow=True), budget=budget)
    gate.check("https://example.com/a")
    gate.check("https://example.com/b")
    assert budget.acquired == ["example.com", "example.com"]


# ---------------------------------------------------------------------------
# PolitenessGate — crawl-delay with an injected clock (no real sleeps)
# ---------------------------------------------------------------------------


def test_gate_first_check_for_host_never_sleeps(clock: FakeClock) -> None:
    """With no prior fetch timestamp there is nothing to delay against."""
    slept: list[float] = []
    gate = PolitenessGate(robots=_stub_robots(delay=5.0), sleeper=slept.append)
    gate.check("https://example.com/first")
    assert slept == []


def test_gate_sleeps_exactly_remaining_delay(clock: FakeClock) -> None:
    """Crawl-delay 5s with 2s already elapsed must sleep precisely 3s."""
    slept: list[float] = []
    gate = PolitenessGate(robots=_stub_robots(delay=5.0), sleeper=slept.append)
    gate.check("https://example.com/a")  # records last-fetch at t=1000
    clock.advance(2.0)
    gate.check("https://example.com/b")
    assert slept == [pytest.approx(3.0)]


def test_gate_no_sleep_when_delay_already_elapsed(clock: FakeClock) -> None:
    slept: list[float] = []
    gate = PolitenessGate(robots=_stub_robots(delay=5.0), sleeper=slept.append)
    gate.check("https://example.com/a")
    clock.advance(10.0)  # well past the 5s delay
    gate.check("https://example.com/b")
    assert slept == []


def test_gate_crawl_delay_tracked_per_host(clock: FakeClock) -> None:
    """host-a's fetch timestamp must not throttle host-b's first request."""
    slept: list[float] = []
    gate = PolitenessGate(robots=_stub_robots(delay=5.0), sleeper=slept.append)
    gate.check("https://host-a.example/x")
    clock.advance(1.0)
    gate.check("https://host-b.example/x")  # first fetch for host-b: no sleep
    assert slept == []
    clock.advance(1.0)
    gate.check("https://host-a.example/y")  # 2s elapsed of 5s → sleep 3s
    assert slept == [pytest.approx(3.0)]
