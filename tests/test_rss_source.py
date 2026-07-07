"""Tests for the RSS/Atom source adapter and the `monitor run` CLI."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from lighthouse_ai.cli import app
from lighthouse_ai.sources.rss import fetch_feed, parse_feed_bytes

ATOM_FIXTURE = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom Feed</title>
  <entry>
    <title>Quantum breakthrough at MIT</title>
    <link href="https://example.com/post1" />
    <summary>Researchers report a fidelity record.</summary>
    <updated>2026-05-27T10:00:00Z</updated>
  </entry>
  <entry>
    <title>Second story</title>
    <link href="https://example.com/post2" />
    <summary>Body two.</summary>
  </entry>
</feed>"""

RSS_FIXTURE = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>HN front page</title>
    <item>
      <title>Show HN: Lighthouse</title>
      <link>https://news.ycombinator.com/item?id=1</link>
      <description>A local-first research tool.</description>
      <pubDate>Wed, 27 May 2026 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

MALFORMED_FIXTURE = b"<not valid xml &"


# --- parse_feed_bytes ---


def test_parse_atom_returns_two_items():
    items = parse_feed_bytes(ATOM_FIXTURE)
    assert len(items) == 2
    assert items[0].url == "https://example.com/post1"
    assert items[0].title == "Quantum breakthrough at MIT"
    assert "fidelity record" in items[0].body
    assert items[0].published_at == "2026-05-27T10:00:00Z"
    assert items[0].source == "Test Atom Feed"


def test_parse_rss_returns_item():
    items = parse_feed_bytes(RSS_FIXTURE)
    assert len(items) == 1
    assert items[0].title == "Show HN: Lighthouse"
    assert items[0].source == "HN front page"


def test_parse_malformed_returns_empty():
    assert parse_feed_bytes(MALFORMED_FIXTURE) == []


# Some feeds publish a bare <channel> document with no <rss> wrapper.
BARE_CHANNEL_FIXTURE = b"""<?xml version="1.0"?>
<channel>
  <title>Bare Channel Feed</title>
  <item>
    <title>Item one</title>
    <link>https://example.com/bare1</link>
    <description>Body one.</description>
  </item>
  <item>
    <title>Item two</title>
    <link>https://example.com/bare2</link>
    <description>Body two.</description>
  </item>
</channel>"""


def test_parse_bare_channel_at_root_returns_items():
    """A <channel> at the document root (no <rss> wrapper) must still parse."""
    items = parse_feed_bytes(BARE_CHANNEL_FIXTURE)
    assert len(items) == 2
    assert items[0].url == "https://example.com/bare1"
    assert items[0].title == "Item one"
    assert items[0].source == "Bare Channel Feed"


def test_parse_html_in_body_is_stripped():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>X</title>
<item><title>t</title><link>https://x/1</link>
<description>&lt;p&gt;hi &lt;b&gt;there&lt;/b&gt;&lt;/p&gt;</description></item></channel></rss>"""
    items = parse_feed_bytes(feed)
    assert items[0].body == "hi there"


# --- fetch_feed (mocked) ---


@pytest.fixture
def mocked_http():
    with respx.mock(assert_all_called=False) as m:
        yield m


def test_fetch_feed_returns_parsed_items(mocked_http):
    # bbc.co.uk is on the platform egress allowlist, so the guard admits the
    # fetch; the RSS adapter has no fixed host of its own (it points at any
    # registered feed, bounded by the platform allowlist).
    mocked_http.get("https://bbc.co.uk/feed.xml").respond(
        200, content=ATOM_FIXTURE, headers={"content-type": "application/atom+xml"}
    )
    items = fetch_feed("https://bbc.co.uk/feed.xml")
    assert len(items) == 2


def test_fetch_feed_with_broker_rejects_eicar(tmp_path, mocked_http):
    from lighthouse_ai.sandbox import Quarantine, SandboxBroker
    from lighthouse_ai.sandbox.scanners import EICAR_SIGNATURE, EICARScanner

    mocked_http.get("https://bbc.co.uk/evil.xml").respond(
        200, content=EICAR_SIGNATURE, headers={"content-type": "text/xml"}
    )
    q = Quarantine(tmp_path / "q.db", tmp_path / "Q")
    broker = SandboxBroker(q, [EICARScanner()])
    items = fetch_feed("https://bbc.co.uk/evil.xml", broker=broker)
    assert items == []


def test_fetch_feed_raises_on_http_error(mocked_http):
    mocked_http.get("https://bbc.co.uk/missing.xml").respond(404)
    with pytest.raises(httpx.HTTPStatusError):
        fetch_feed("https://bbc.co.uk/missing.xml")


# --- CLI: monitor run ---


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LIGHTHOUSE_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def initted_env(cli_env):
    runner = CliRunner()
    r = runner.invoke(app, ["init", "--data-dir", str(cli_env), "--no-install-service"])
    assert r.exit_code == 0
    return cli_env


def test_monitor_run_writes_html(initted_env, mocked_http, tmp_path):
    mocked_http.get("https://bbc.co.uk/feed.xml").respond(
        200, content=ATOM_FIXTURE, headers={"content-type": "application/atom+xml"}
    )
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "monitor",
            "run",
            "--source-url",
            "https://bbc.co.uk/feed.xml",
            "--topic",
            "test-topic",
        ],
    )
    assert r.exit_code == 0, r.stdout
    # Find the produced HTML file.
    staging = initted_env / "staging"
    files = list(staging.glob("monitor-test-topic-*.html"))
    assert files
    html = files[0].read_text()
    assert "test-topic" in html
    assert "Quantum breakthrough" in html


def test_monitor_run_handles_empty_feed(initted_env, mocked_http):
    mocked_http.get("https://bbc.co.uk/empty.xml").respond(
        200, content=b"<rss><channel></channel></rss>"
    )
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "monitor",
            "run",
            "--source-url",
            "https://bbc.co.uk/empty.xml",
            "--topic",
            "empty",
        ],
    )
    assert r.exit_code == 0
    assert "no items" in r.stdout.lower()


def test_monitor_run_handles_fetch_failure(initted_env, mocked_http):
    mocked_http.get("https://bbc.co.uk/down.xml").side_effect = httpx.ConnectError("down")
    runner = CliRunner()
    r = runner.invoke(
        app,
        [
            "monitor",
            "run",
            "--source-url",
            "https://bbc.co.uk/down.xml",
            "--topic",
            "down",
        ],
    )
    assert r.exit_code != 0
