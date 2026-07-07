"""Tests for deterministic payload compaction (OpenHuman §5 integration)."""

from __future__ import annotations

import json

from lighthouse_ai.rag.compaction import (
    BUILTIN_RULES,
    CompactionRule,
    compact,
    estimate_tokens,
    load_rules,
    looks_like_html,
)

HTML_FIXTURE = """
<html><head><style>.x{color:red}</style><script>track();</script></head>
<body>
<nav>Skip to content</nav>
<p>Photovoltaic cells convert sunlight into electricity.</p>
<p>Photovoltaic cells convert sunlight into electricity.</p>
<a href="https://example.com/very/long/path?utm=123&ref=abc">source</a>
<footer>© 2024 Example Corp. All rights reserved.</footer>
</body></html>
"""


# --- transforms / end-to-end ----------------------------------------------


def test_strips_tags_and_scripts() -> None:
    out, _ = compact(HTML_FIXTURE, content_type="text/html")
    assert "<script>" not in out and "track()" not in out
    assert "<p>" not in out and ".x{color:red}" not in out
    assert "Photovoltaic cells convert sunlight into electricity." in out


def test_dedupes_repeated_lines() -> None:
    out, _ = compact(HTML_FIXTURE, content_type="text/html")
    assert out.count("Photovoltaic cells convert sunlight into electricity.") == 1


def test_strips_boilerplate_footer() -> None:
    out, _ = compact(HTML_FIXTURE, content_type="text/html")
    assert "All rights reserved" not in out
    assert "Skip to content" not in out


def test_shortens_urls_but_keeps_domain() -> None:
    # Inline URLs in text get shortened to the domain (provenance kept). URLs in
    # HTML href attributes are removed with the tag — that's expected.
    text = "See https://example.com/very/long/path?utm=123&ref=abc for details."
    out, _ = compact(text, content_type="text/plain")
    assert "example.com" in out
    assert "very/long/path" not in out


def test_token_reduction_is_measured() -> None:
    out, stats = compact(HTML_FIXTURE, content_type="text/html")
    assert stats.orig_tokens > stats.new_tokens
    assert 0.0 < stats.ratio <= 1.0


def test_idempotent_for_default_ruleset() -> None:
    once, _ = compact(HTML_FIXTURE, content_type="text/html")
    twice, _ = compact(once, content_type="text/html")
    assert once == twice


# --- grapheme safety -------------------------------------------------------


def test_cjk_and_emoji_round_trip_without_splitting() -> None:
    text = "研究結果: 太陽光発電は効率的です。\n\nResult 🔬🌞 verified."
    out, _ = compact(text, content_type="text/plain")
    assert "研究結果" in out
    assert "🔬🌞" in out  # emoji preserved intact, not byte-split


def test_empty_payload_is_safe() -> None:
    out, stats = compact("", content_type="text/html")
    assert out == ""
    assert stats.ratio == 0.0


# --- layer precedence ------------------------------------------------------


def test_project_rule_overrides_user_overrides_builtin(tmp_path) -> None:
    user = tmp_path / "user"
    project = tmp_path / "project"
    user.mkdir()
    project.mkdir()
    # Same id "dedupe-lines" as a builtin; user then project override its transform.
    (user / "r.json").write_text(
        json.dumps(
            [
                {
                    "id": "dedupe-lines",
                    "match": "*",
                    "transform": "regex_sub",
                    "params": {"pattern": "USER", "repl": "u"},
                }
            ]
        )
    )
    (project / "r.json").write_text(
        json.dumps(
            [
                {
                    "id": "dedupe-lines",
                    "match": "*",
                    "transform": "regex_sub",
                    "params": {"pattern": "PROJECT", "repl": "p"},
                }
            ]
        )
    )
    rules = load_rules(user_dir=user, project_dir=project)
    by_id = {r.id: r for r in rules}
    assert by_id["dedupe-lines"].params["pattern"] == "PROJECT"  # project wins
    # builtin-only ids still present
    assert "html-to-markdown" in by_id


def test_load_rules_ignores_missing_dirs(tmp_path) -> None:
    rules = load_rules(user_dir=tmp_path / "nope", project_dir=tmp_path / "nada")
    assert {r.id for r in rules} == {r.id for r in BUILTIN_RULES}


# --- matching --------------------------------------------------------------


def test_rule_match_glob_on_source() -> None:
    rule = CompactionRule(
        "pubmed-strip", "*.nih.gov", "regex_sub", {"pattern": "BOILER", "repl": ""}
    )
    out, _ = compact("keep BOILER", source="pubmed.ncbi.nlm.nih.gov", rules=[rule])
    assert out == "keep "
    # Non-matching source leaves it untouched.
    out2, _ = compact("keep BOILER", source="arxiv.org", rules=[rule])
    assert out2 == "keep BOILER"


# --- helpers ---------------------------------------------------------------


def test_looks_like_html() -> None:
    assert looks_like_html("<p>hi</p>") is True
    assert looks_like_html("1 < 2 and 3 > 2") is False  # stray angle brackets


def test_estimate_tokens_monotonic() -> None:
    assert estimate_tokens("a" * 40) > estimate_tokens("a" * 4)
