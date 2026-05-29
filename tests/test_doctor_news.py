"""Tests for `lighthouse doctor news` CLI subcommand (SL13).

All tests are offline-deterministic: no network calls, no real LLM.
The command must:
  - exit 0 even with no network access (offline default).
  - print a table with the six seed outlets visible.
  - print the known-unavailable outlets (NYT, WSJ, Bloomberg, FT, Fox).
  - work in live mode when LIGHTHOUSE_REAL_BACKEND=1 is set (mocked httpx).
  - not crash when LIGHTHOUSE_DATA_DIR is unset or points to a tmp dir.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from typer.testing import CliRunner

from lighthouse_ai.cli import app

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

runner = CliRunner()


@pytest.fixture()
def offline_env(tmp_path, monkeypatch):
    """Set LIGHTHOUSE_DATA_DIR so init-dependent code resolves paths safely."""
    monkeypatch.setenv("LIGHTHOUSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("LIGHTHOUSE_REAL_BACKEND", raising=False)
    return tmp_path / "data"


# ---------------------------------------------------------------------------
# Offline mode (default) tests
# ---------------------------------------------------------------------------


def test_doctor_news_exits_zero_offline(offline_env):
    """Command exits 0 with no network available."""
    result = runner.invoke(app, ["doctor", "news"])
    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}\nOutput:\n{result.stdout}"
    )


def test_doctor_news_shows_seed_outlets_offline(offline_env):
    """All six seed outlets appear in the table output.

    Rich may wrap long outlet names across lines in a narrow terminal, so we
    check for stable substrings rather than the full name on one line.
    """
    result = runner.invoke(app, ["doctor", "news"])
    assert result.exit_code == 0, result.stdout
    output = result.stdout

    # Use stable substrings that survive Rich's word-wrap in narrow terminals.
    expected_substrings = [
        "Reuters",
        "Associated",  # "Associated Press" may wrap
        "BBC News",
        "NPR",
        "Guardian",    # "The Guardian" may wrap
        "ProPublica",
    ]
    for substr in expected_substrings:
        assert substr in output, (
            f"Expected '{substr}' in output.\nFull output:\n{output}"
        )


def test_doctor_news_shows_offline_marker(offline_env):
    """Offline mode labels each outlet with 'offline'."""
    result = runner.invoke(app, ["doctor", "news"])
    assert result.exit_code == 0, result.stdout
    assert "offline" in result.stdout


def test_doctor_news_shows_unavailable_outlets(offline_env):
    """Paywall/ToS-blocked outlets appear with 'not fetchable' or similar.

    §4: "Visibility-with-reason beats silent omission."
    Rich may wrap names in a narrow terminal, so check stable substrings.
    """
    result = runner.invoke(app, ["doctor", "news"])
    assert result.exit_code == 0, result.stdout
    output = result.stdout

    # "Wall Street Journal" may wrap to "Wall Street" / "Journal"; "Bloomberg" is short.
    for substr in ["Wall Street", "Bloomberg"]:
        assert substr in output, (
            f"Expected '{substr}' in unavailable-outlet output.\nFull output:\n{output}"
        )


def test_doctor_news_shows_allsides_ratings(offline_env):
    """AllSides rating values are present in the table."""
    result = runner.invoke(app, ["doctor", "news"])
    assert result.exit_code == 0, result.stdout
    output = result.stdout

    # At least the "center" and "lean_left" ratings must appear.
    assert "center" in output or "lean_left" in output, (
        f"Expected AllSides ratings in output.\nFull output:\n{output}"
    )


def test_doctor_news_no_network_calls_in_offline_mode(offline_env, monkeypatch):
    """In offline mode, no HTTP requests are made."""
    calls: list[str] = []

    original_head = httpx.head

    def _patched_head(url, **kwargs):
        calls.append(url)
        return original_head(url, **kwargs)

    monkeypatch.setattr(httpx, "head", _patched_head)

    result = runner.invoke(app, ["doctor", "news"])
    assert result.exit_code == 0, result.stdout
    assert len(calls) == 0, f"Expected no HTTP calls in offline mode, got: {calls}"


# ---------------------------------------------------------------------------
# Live mode tests (mocked)
# ---------------------------------------------------------------------------


def test_doctor_news_live_flag_triggers_checks(offline_env):
    """--live flag attempts network checks (mocked to succeed)."""
    # Mock all six RSS feeds to return 200.
    feed_urls = [
        "https://feeds.reuters.com/reuters/topNews",
        "https://apnews.com/hub/ap-top-news",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.npr.org/1001/rss.xml",
        "https://www.theguardian.com/world/rss",
        "https://www.propublica.org/feeds/propublica/main",
    ]
    with respx.mock(assert_all_called=False) as mock:
        for url in feed_urls:
            mock.head(url).mock(return_value=httpx.Response(200))
        result = runner.invoke(app, ["doctor", "news", "--live"])
    assert result.exit_code == 0, result.stdout
    # 'offline' label should NOT be in output when live mode is active.
    assert "offline" not in result.stdout or "live" in result.stdout


def test_doctor_news_live_shows_unreachable_on_connection_error(offline_env):
    """Live mode marks outlets as unreachable when connection fails."""
    with respx.mock(assert_all_called=False) as mock:
        # Simulate a connection error for all feed URLs.
        mock.head(url__regex=r"https://.*").mock(
            side_effect=httpx.ConnectError("simulated failure")
        )
        result = runner.invoke(app, ["doctor", "news", "--live"])
    assert result.exit_code == 0, result.stdout
    # All failures are shown, not crash.
    output = result.stdout
    assert "Reuters" in output
    assert "BBC News" in output


def test_doctor_news_real_backend_env_triggers_live(offline_env, monkeypatch):
    """LIGHTHOUSE_REAL_BACKEND=1 triggers live checks without --live flag."""
    monkeypatch.setenv("LIGHTHOUSE_REAL_BACKEND", "1")

    with respx.mock(assert_all_called=False) as mock:
        mock.head(url__regex=r"https://.*").mock(return_value=httpx.Response(200))
        result = runner.invoke(app, ["doctor", "news"])
    assert result.exit_code == 0, result.stdout
    # Should not show the offline label.
    assert "offline (pass --live" not in result.stdout


# ---------------------------------------------------------------------------
# Table structure / format tests
# ---------------------------------------------------------------------------


def test_doctor_news_table_has_method_column(offline_env):
    """The output mentions fetch methods (RSS, API, etc.)."""
    result = runner.invoke(app, ["doctor", "news"])
    assert result.exit_code == 0, result.stdout
    # At least one method keyword should be present.
    assert "RSS" in result.stdout or "API" in result.stdout


def test_doctor_news_table_has_trusted_marker(offline_env):
    """The output contains a trusted indicator for seed outlets."""
    result = runner.invoke(app, ["doctor", "news"])
    assert result.exit_code == 0, result.stdout
    # The pre-selected seed outlets show a checkmark.
    output = result.stdout
    assert "✓" in output or "✓" in output or "trusted" in output.lower()


def test_doctor_news_no_crash_without_data_dir(tmp_path, monkeypatch):
    """Command does not crash even when LIGHTHOUSE_DATA_DIR is not set."""
    monkeypatch.setenv("LIGHTHOUSE_DATA_DIR", str(tmp_path / "nonexistent"))
    monkeypatch.delenv("LIGHTHOUSE_REAL_BACKEND", raising=False)
    result = runner.invoke(app, ["doctor", "news"])
    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}\nOutput:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# Confirm existing `doctor check` still works (regression guard)
# ---------------------------------------------------------------------------


def test_doctor_check_still_accessible(tmp_path, monkeypatch):
    """The renamed `doctor check` subcommand is reachable and exits 0 on a
    fresh (init'd) data dir."""
    monkeypatch.setenv("LIGHTHOUSE_DATA_DIR", str(tmp_path / "data"))
    # We need init to run first so the databases exist.
    init_result = runner.invoke(
        app, ["init", "--data-dir", str(tmp_path / "data"), "--no-install-service"]
    )
    assert init_result.exit_code == 0, init_result.stdout
    result = runner.invoke(app, ["doctor", "check"])
    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}\nOutput:\n{result.stdout}"
    )
