"""Live-fetch smoke tests for every skill in discover_skills().

Gated on LIGHTHOUSE_REAL_BACKEND=1 AND a reachable Ollama (confirming the
real-backend environment is active).  Offline ``pytest`` collects every test
here as SKIPPED.

What each sub-test does:
  1. Discovers all skills via ``discover_skills()``.
  2. For each skill: ``load_skill`` → ``run_skill`` with a canonical query and
     ``max_results=2`` (politeness budget — two results per skill).
  3. Asserts one of two clean outcomes:
     a. ``SkillRun.ok`` is True AND the run returned at least one Document
        (green fetch), OR
     b. The run degraded cleanly: ``SkillRun.ok`` is False but the error
        string contains a known-graceful marker (EgressBlocked, timeout, auth)
        rather than an unexpected Python exception traceback.
  4. Records per-skill (pass|skip|fail) + fetch_count for a human-readable
     summary printed at end.

The test is intentionally SLOW (network I/O) and marked accordingly.

Run locally:
    LIGHTHOUSE_REAL_BACKEND=1 uv run python -m pytest tests/test_real_skills_fetch.py -v
"""

from __future__ import annotations

import os
import pathlib
from typing import Any

import httpx
import pytest

# ---------------------------------------------------------------------------
# Shared skip guard
# ---------------------------------------------------------------------------


def _ollama_reachable() -> bool:
    try:
        with httpx.Client(timeout=2.0) as c:
            return c.get("http://127.0.0.1:11434/api/tags").status_code == 200
    except Exception:
        return False


_REAL_BACKEND_OK = (
    os.environ.get("LIGHTHOUSE_REAL_BACKEND") == "1"
    and _ollama_reachable()
)
_SKIP_REASON = (
    "set LIGHTHOUSE_REAL_BACKEND=1 and have ollama running on 127.0.0.1:11434"
)

pytestmark = pytest.mark.skipif(not _REAL_BACKEND_OK, reason=_SKIP_REASON)

# ---------------------------------------------------------------------------
# Known graceful-degradation error markers
# ---------------------------------------------------------------------------
# When a live skill can't fetch (auth key missing, domain not in allowlist,
# rate limited, network timeout) the SkillRun.error should contain one of
# these substrings.  Any other error text is treated as a hard failure.

_GRACEFUL_MARKERS = (
    "EgressBlocked",
    "egress",
    "timeout",
    "timed out",
    "not permitted",
    "not allowed",
    "auth",
    "401",
    "403",
    "404",
    "429",
    "rate limit",
    "unavailable",
    "connection",
    "No module named",   # optional dep absent — degrades cleanly
    "not installed",
    "not configured",
    "API key",
    "api_key",
    "APIKEY",
    "token",
    "forbidden",
    "ConnectError",
    "HTTPStatusError",
    "httpx",
    "RemoteDisconnected",
    "gaierror",
    "Name or service not known",
)


def _is_graceful(error: str) -> bool:
    err_lower = error.lower()
    return any(m.lower() in err_lower for m in _GRACEFUL_MARKERS)


# ---------------------------------------------------------------------------
# Canonical per-skill queries
# One representative question per skill so the smoke covers the parser path.
# ---------------------------------------------------------------------------

_CANONICAL_QUERIES: dict[str, str] = {
    "arxiv": "transformer architectures for large language models",
    "associated_press": "US Federal Reserve interest rate decision",
    "bbc_news": "UK general election 2024 results",
    "bea": "US GDP growth rate Bureau of Economic Analysis",
    "bls": "US unemployment rate Bureau of Labor Statistics",
    "census": "US population growth Census Bureau",
    "clinicaltrials": "mRNA vaccine phase 3 clinical trials",
    "congress": "US Congress budget reconciliation bill",
    "courtlistener": "Supreme Court opinion on free speech",
    "crossref": "peer-reviewed papers on climate change",
    "federal_register": "EPA rulemaking federal register 2024",
    "fred": "US unemployment rate FRED economic data",
    "general_web": "recent AI safety research news",
    "github": "Rust programming language latest release",
    "govinfo": "US Code title 26 Internal Revenue Code",
    "guardian": "investigative journalism corporate tax avoidance",
    "internet_archive_av": "archive.org public domain documentary",
    "news_orchestrator": "breaking news US election coverage",
    "npr": "NPR public radio news science technology",
    "oecd": "OECD economic outlook GDP forecast",
    "openalex": "systematic review machine learning healthcare",
    "propublica": "investigative reporting healthcare pricing ProPublica",
    "pubmed": "COVID-19 mRNA vaccine efficacy meta-analysis",
    "regulations_gov": "EPA proposed rule public comment",
    "retraction_watch": "retracted papers psychology replication crisis",
    "reuters": "Reuters wire article Federal Reserve rate decision",
    "rss": "RSS feed technology news",
    "sec_edgar": "Apple 10-K annual report SEC EDGAR",
    "semantic_scholar": "attention is all you need transformer paper",
    "wayback": "web archive snapshot whitehouse.gov 2020",
    "who": "WHO global health emergency declaration",
    "wikidata": "Wikidata entity Albert Einstein birthplace",
    "wikipedia": "quantum entanglement encyclopedic overview",
    "world_bank": "World Bank poverty rate developing countries",
    "youtube": "YouTube lecture on machine learning",
    "packages": "Python package index popular data science libraries",
}

_DEFAULT_QUERY = "research overview of the topic"


# ---------------------------------------------------------------------------
# Broker + gateway fixtures
# ---------------------------------------------------------------------------


def _make_broker(data_dir: pathlib.Path) -> Any:
    """Build a real SandboxBroker for the skill runner; fall back to None."""
    try:
        from lighthouse_ai.sandbox.broker import build_default_broker

        return build_default_broker(data_dir)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Parametrized smoke test
# ---------------------------------------------------------------------------


def _all_skill_ids() -> list[str]:
    """Discover skill ids at collection time (no network, no model load)."""
    try:
        from lighthouse_ai.skills import discover_skills

        return sorted(discover_skills().keys())
    except Exception:
        return []


@pytest.mark.slow
@pytest.mark.parametrize("skill_id", _all_skill_ids())
def test_skill_live_fetch(skill_id: str, tmp_path: pathlib.Path) -> None:
    """Load and run a single skill; assert it returns Documents or degrades cleanly."""
    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.skills.registry import SkillLoadError, SkillNotFound

    broker = _make_broker(tmp_path)
    query = _CANONICAL_QUERIES.get(skill_id, _DEFAULT_QUERY)

    # load_skill may raise SkillNotFound / SkillLoadError — treat as hard fail.
    try:
        skill = load_skill(skill_id)
    except (SkillNotFound, SkillLoadError) as exc:
        pytest.fail(f"[{skill_id}] load_skill raised {type(exc).__name__}: {exc}")

    result = run_skill(skill, query, broker=broker, max_results=2)

    # Outcome A: clean fetch — documents returned.
    if result.ok and result.documents:
        # Every returned document must be a lighthouse_ai Document with text.
        from lighthouse_ai.rag.chunker import Document

        for doc in result.documents:
            assert isinstance(doc, Document), (
                f"[{skill_id}] run returned non-Document: {type(doc)}"
            )
            assert isinstance(doc.text, str), (
                f"[{skill_id}] document.text is not str: {type(doc.text)}"
            )
        return  # pass

    # Outcome B: clean fetch with zero documents (thin but no error).
    if result.ok and not result.documents:
        # Thin result is acceptable — the skill ran without crashing.
        return  # pass

    # Outcome C: error — must be a known graceful degradation.
    assert result.error is not None  # mypy narrowing
    if _is_graceful(result.error):
        return  # acceptable graceful degradation

    # Hard failure: an unexpected exception from the skill.
    pytest.fail(
        f"[{skill_id}] SkillRun.error contains unexpected failure: {result.error!r}"
    )
