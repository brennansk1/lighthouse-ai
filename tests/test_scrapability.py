"""Tests for the scrapability pre-flight (Watch v2, FUTURE_FEATURES §1).

All offline-deterministic: every byte comes from an injected ``fetch`` closure
or pre-supplied ``robots_bytes``; no socket is ever opened.
"""

from __future__ import annotations

import pytest

from lighthouse_ai.sources.scrapability import (
    FetchResult,
    verify_scrapable,
)

# A small body that extracts to well over the default token floor.
RICH_HTML = (
    b"<html><body><article>"
    + b"<p>" + (b"lorem ipsum dolor sit amet " * 40) + b"</p>"
    + b"</article></body></html>"
)

# A JS-shell body: almost no static prose.
SHELL_HTML = b"<html><body><div id='root'></div><script>app()</script></body></html>"

ALLOW = frozenset({"example.com"})


def _fetch_for(body: bytes, *, status: int = 200, headers: dict | None = None):
    def fetch(url: str) -> FetchResult:
        return FetchResult(status=status, headers=headers or {}, body=body,
                           content_type="text/html")
    return fetch


def test_robots_disallow_blocks():
    robots = b"User-agent: *\nDisallow: /\n"
    v = verify_scrapable(
        "https://example.com/page",
        robots_bytes=robots,
        fetch=_fetch_for(RICH_HTML),
        allowlist=ALLOW,
    )
    # protego may or may not be installed; if installed -> blocked.
    pytest.importorskip("protego")
    assert v.robots_ok is False
    assert v.verdict == "blocked"
    assert "robots" in v.reason.lower()


def test_allowlisted_static_extract_is_good_via_diff_or_etag():
    # No feed, no ETag -> static extract is monitorable via content-diff = limited.
    v = verify_scrapable(
        "https://example.com/page",
        robots_bytes=b"User-agent: *\nAllow: /\n",
        fetch=_fetch_for(RICH_HTML),
        allowlist=ALLOW,
    )
    assert v.robots_ok is True
    assert v.reachable is True
    assert v.extract_tier == "static"
    assert v.change_method == "diff"
    assert v.verdict == "limited"  # static + diff is workable but heavier


def test_static_extract_with_etag_is_good():
    v = verify_scrapable(
        "https://example.com/page",
        robots_bytes=b"User-agent: *\nAllow: /\n",
        fetch=_fetch_for(RICH_HTML, headers={"ETag": '"abc123"'}),
        allowlist=ALLOW,
    )
    assert v.change_method == "etag"
    assert v.extract_tier == "static"
    assert v.verdict == "good"


def test_feed_link_detected_is_good():
    body = (
        b"<html><head>"
        b"<link rel='alternate' type='application/rss+xml' "
        b"href='/feed.xml' title='Feed'>"
        b"</head><body>"
        + RICH_HTML
        + b"</body></html>"
    )
    v = verify_scrapable(
        "https://example.com/page",
        robots_bytes=b"User-agent: *\nAllow: /\n",
        fetch=_fetch_for(body),
        allowlist=ALLOW,
    )
    assert v.change_method == "feed"
    assert v.feed_url == "https://example.com/feed.xml"
    assert v.verdict == "good"
    assert "feed" in v.reason.lower()


def test_static_below_token_floor_is_js_limited():
    v = verify_scrapable(
        "https://example.com/page",
        robots_bytes=b"User-agent: *\nAllow: /\n",
        fetch=_fetch_for(SHELL_HTML),
        allowlist=ALLOW,
        min_tokens=50,
    )
    assert v.extract_tier == "js"
    assert v.verdict == "limited"
    assert "js" in v.reason.lower() or "render" in v.reason.lower()


def test_unreachable_host_is_limited_with_trust_hint():
    v = verify_scrapable(
        "https://not-allowed.example.org/page",
        robots_bytes=b"User-agent: *\nAllow: /\n",
        fetch=_fetch_for(RICH_HTML),
        allowlist=ALLOW,
    )
    assert v.reachable is False
    assert v.trust_add_hint == "not-allowed.example.org"
    assert v.verdict == "limited"
    assert "trust add" in v.reason


def test_no_content_no_feed_is_blocked():
    # Empty body, reachable, robots ok -> nothing to extract or diff.
    v = verify_scrapable(
        "https://example.com/page",
        robots_bytes=b"User-agent: *\nAllow: /\n",
        fetch=_fetch_for(b"", status=200),
        allowlist=ALLOW,
    )
    assert v.extract_tier == "none"
    assert v.change_method == "diff"
    assert v.verdict == "blocked"


def test_fetch_failure_is_blocked():
    def boom(url: str) -> FetchResult:
        raise RuntimeError("connection reset")

    v = verify_scrapable(
        "https://example.com/page",
        robots_bytes=b"User-agent: *\nAllow: /\n",
        fetch=boom,
        allowlist=ALLOW,
    )
    assert v.verdict == "blocked"
    assert "fetch" in v.reason.lower() or "network" in v.reason.lower()


def test_no_fetch_permissive_robots_no_egress():
    # No fetch and no robots_bytes -> permissive robots, no page probe.
    v = verify_scrapable(
        "https://example.com/page",
        allowlist=ALLOW,
    )
    assert v.robots_ok is True
    assert v.reachable is True
    assert v.extract_tier == "none"
    # Reachable + robots ok but nothing extractable and no feed -> blocked.
    assert v.verdict == "blocked"


def test_body_is_itself_a_feed():
    body = b"<?xml version='1.0'?><rss version='2.0'><channel></channel></rss>"
    v = verify_scrapable(
        "https://example.com/feed.xml",
        robots_bytes=b"User-agent: *\nAllow: /\n",
        fetch=_fetch_for(body),
        allowlist=ALLOW,
    )
    assert v.change_method == "feed"
    assert v.feed_url == "https://example.com/feed.xml"


def test_verdict_as_dict_roundtrips_fields():
    v = verify_scrapable(
        "https://example.com/page",
        robots_bytes=b"User-agent: *\nAllow: /\n",
        fetch=_fetch_for(RICH_HTML, headers={"ETag": '"x"'}),
        allowlist=ALLOW,
    )
    d = v.as_dict()
    assert set(d) >= {
        "robots_ok", "crawl_delay", "reachable", "extract_tier",
        "change_method", "verdict", "reason", "trust_add_hint", "feed_url",
    }
