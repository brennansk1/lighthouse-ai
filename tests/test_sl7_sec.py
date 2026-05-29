"""SL7 — SEC EDGAR skill tests (offline, deterministic).

Covers:
* Skill loads cleanly (no import-guard violation).
* ``run()`` returns Documents tagged with provenance metadata.
* ``run_watchable()`` filters by ``since`` date.
* ``parse_10k_item_1a`` correctly extracts the Risk Factors section.
* ``parse_10k_item_7`` correctly extracts the MD&A section.
* Empty / not-found returns for missing headers.
* HTML stripping works correctly in the parsers.
* ``load_skill("sec_edgar")`` resolves from the real library directory.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.skills import load_skill, run_skill, run_watchable

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LIBRARY_DIR = (
    Path(__file__).parent.parent
    / "src" / "lighthouse_ai" / "skills" / "library"
)

# Minimal canned Document list the monkeypatch returns.
_CANNED_DOCS = [
    Document(
        id="sec:0001234567-24-000001",
        text="Apple Inc — 10-K. Supply chain risk … ",
        metadata={
            "source": "sec_edgar",
            "url": "https://www.sec.gov/Archives/edgar/data/0000320193/000032019324000001/",
            "grade": "B",
            "published_date": "2024-11-01",
            "title": "Apple Inc — 10-K",
            "form_type": "10-K",
            "entity_name": "Apple Inc",
            "display_names": ["Apple Inc"],
        },
    ),
    Document(
        id="sec:0009876543-23-000002",
        text="Tesla, Inc — 8-K. Earnings release … ",
        metadata={
            "source": "sec_edgar",
            "url": "https://www.sec.gov/Archives/edgar/data/0001318605/000131860523000002/",
            "grade": "B",
            "published_date": "2023-01-26",
            "title": "Tesla, Inc — 8-K",
            "form_type": "8-K",
            "entity_name": "Tesla, Inc",
            "display_names": ["Tesla, Inc"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Synthetic 10-K text used for parser unit tests
# ---------------------------------------------------------------------------

_SYNTHETIC_10K = """\
UNITED STATES SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549

FORM 10-K

PART I

Item 1. Business
We are a technology company that makes widgets.

Item 1A. Risk Factors
Our business is subject to a number of risks and uncertainties. The following
risk factors could materially and adversely affect our operating results:

SUPPLY CHAIN RISKS: We rely on a limited number of suppliers for key components.
Any disruption to our supply chain could negatively impact our ability to deliver
products on time.

COMPETITIVE RISKS: The market for widgets is highly competitive. We face competition
from established technology companies and new market entrants.

REGULATORY RISKS: We are subject to regulations in multiple jurisdictions.

Item 1B. Unresolved Staff Comments
None.

Item 2. Properties
We own and lease office space in multiple locations.

PART II

Item 5. Market for Registrant's Common Equity
Our common stock is listed on the NASDAQ exchange.

Item 6. [Reserved]

Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations

OVERVIEW
The following discussion and analysis should be read in conjunction with our
consolidated financial statements.

REVENUE
Total net revenue increased 12% year over year to $10.5 billion, driven by strong
demand for our flagship widget product line.

OPERATING EXPENSES
Operating expenses increased 8% to $7.2 billion.

Item 7A. Quantitative and Qualitative Disclosures About Market Risk
We are exposed to market risk in the ordinary course of business.

Item 8. Financial Statements and Supplementary Data
See the consolidated financial statements included in this Annual Report.
"""

_SYNTHETIC_10K_HTML = """\
<html><body>
<p>PART I</p>
<p><b>Item 1A.</b> Risk Factors</p>
<p>Our business faces the following <em>material risks</em>:</p>
<ul><li>Supply chain disruption risk.</li></ul>
<p><b>Item 1B.</b> Unresolved Staff Comments</p>
<p>None.</p>
<p><b>Item 7.</b> Management&#8217;s Discussion</p>
<p>Revenue increased 5% year over year. &amp; Operating margins improved.</p>
<p><b>Item 7A.</b> Quantitative Disclosures</p>
<p>We hold interest-rate sensitive instruments.</p>
</body></html>
"""

# A 10-K fragment that lacks Item 1A (tests empty-return path)
_NO_ITEM_1A_TEXT = """\
FORM 10-K

Item 1. Business
We are a small company.

Item 2. Properties
None.
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def broker(tmp_path):
    return build_default_broker(tmp_path)


@pytest.fixture()
def skill():
    return load_skill("sec_edgar", library_dir=_LIBRARY_DIR)


@pytest.fixture()
def patched_skill(monkeypatch):
    """Load the real sec_edgar skill but monkeypatch the adapter to return canned docs."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.sec_edgar.search_sec_edgar",
        lambda query, max_results=5, **kwargs: _CANNED_DOCS[:max_results],
    )
    return load_skill("sec_edgar", library_dir=_LIBRARY_DIR)


# ---------------------------------------------------------------------------
# 1. Skill loads + import guard
# ---------------------------------------------------------------------------

def test_skill_loads(skill):
    """sec_edgar skill loads without import-guard violation."""
    assert skill.manifest.id == "sec_edgar"
    assert callable(skill.entrypoint)
    assert skill.watchable_entrypoint is not None


def test_skill_manifest_fields(skill):
    m = skill.manifest
    assert m.category == "financial"
    assert m.tier == "A"
    assert m.signed is True
    assert m.watchable is True
    assert "list_recent_for_cik" in m.watchable_tools
    assert m.output_shape == "enumerable"
    assert m.temporal_tools is True
    assert set(m.allowed_domains) == {"sec.gov", "www.sec.gov"}


def test_skill_no_forbidden_imports(skill):
    """Import guard passes — skill.py does not import httpx/requests/etc."""
    # If the skill loaded (see test_skill_loads), the guard already passed.
    # This test makes the invariant explicit and documents the contract.
    assert skill is not None


# ---------------------------------------------------------------------------
# 2. run() returns tagged Documents
# ---------------------------------------------------------------------------

def test_run_returns_documents(patched_skill, broker):
    result = run_skill(patched_skill, "Apple 10-K risk factors", broker=broker)
    assert result.ok
    assert len(result.documents) >= 1


def test_run_documents_have_provenance(patched_skill, broker):
    result = run_skill(patched_skill, "Apple 10-K risk factors", broker=broker)
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "sec_edgar"
    assert doc.metadata["skill_version"] == "0.1.0"
    assert doc.metadata.get("grade") == "B"
    assert "fetch_backend" in doc.metadata


def test_run_documents_preserve_source_metadata(patched_skill, broker):
    result = run_skill(patched_skill, "Apple 10-K", broker=broker)
    doc = result.documents[0]
    assert doc.metadata["source"] == "sec_edgar"
    assert doc.metadata["form_type"] == "10-K"
    assert doc.metadata["entity_name"] == "Apple Inc"


def test_run_max_results_respected(patched_skill, broker):
    result = run_skill(patched_skill, "any query", broker=broker, max_results=1)
    assert len(result.documents) <= 1


def test_run_swallows_adapter_errors(monkeypatch, broker):
    """run() catches adapter exceptions and returns empty list gracefully.

    skill.py catches the exception internally and returns []; the runner sees a
    successful call with zero documents (ok=True, thin=True).  This is the
    intended degradation path: a broken adapter yields an empty corpus rather
    than a job crash.
    """
    monkeypatch.setattr(
        "lighthouse_ai.sources.sec_edgar.search_sec_edgar",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("EDGAR down")),
    )
    skill = load_skill("sec_edgar", library_dir=_LIBRARY_DIR)
    result = run_skill(skill, "anything", broker=broker)
    # skill.py catches the error → runner sees ok=True but no documents (thin)
    assert result.ok
    assert result.thin
    assert result.documents == []


# ---------------------------------------------------------------------------
# 3. run_watchable() filters by since
# ---------------------------------------------------------------------------

def test_run_watchable_returns_documents(patched_skill, broker):
    result = run_watchable(patched_skill, "0000320193", since=None, broker=broker)
    assert result.ok
    assert len(result.documents) >= 1


def test_run_watchable_since_filters_old_docs(patched_skill, broker):
    # _CANNED_DOCS[1] has published_date "2023-01-26" → should be filtered out
    # when since = 2023-06-01 (after that date).
    since_dt = datetime(2023, 6, 1)
    result = run_watchable(patched_skill, "0001318605", since=since_dt, broker=broker)
    # Only the Apple doc (2024-11-01) should survive
    for doc in result.documents:
        file_date = doc.metadata.get("published_date", "")
        if file_date:
            assert datetime.strptime(file_date, "%Y-%m-%d") > since_dt


def test_run_watchable_since_none_includes_all(patched_skill, broker):
    result = run_watchable(patched_skill, "filings", since=None, broker=broker)
    assert len(result.documents) == len(_CANNED_DOCS)


# ---------------------------------------------------------------------------
# 4. parse_10k_item_1a unit tests
# ---------------------------------------------------------------------------

from lighthouse_ai.skills.library.sec_edgar.parsers import parse_10k_item_1a, parse_10k_item_7


def test_parse_10k_item_1a_extracts_risk_factors():
    result = parse_10k_item_1a(_SYNTHETIC_10K)
    assert result != ""
    assert "Risk Factors" in result or "SUPPLY CHAIN RISKS" in result


def test_parse_10k_item_1a_contains_key_content():
    result = parse_10k_item_1a(_SYNTHETIC_10K)
    assert "SUPPLY CHAIN RISKS" in result
    assert "COMPETITIVE RISKS" in result
    assert "REGULATORY RISKS" in result


def test_parse_10k_item_1a_does_not_include_item_1b():
    result = parse_10k_item_1a(_SYNTHETIC_10K)
    # Item 1B header and "Unresolved Staff Comments" body should NOT appear in 1A output
    assert "Unresolved Staff Comments" not in result


def test_parse_10k_item_1a_does_not_include_item_2():
    result = parse_10k_item_1a(_SYNTHETIC_10K)
    assert "We own and lease office space" not in result


def test_parse_10k_item_1a_not_found_returns_empty():
    result = parse_10k_item_1a(_NO_ITEM_1A_TEXT)
    assert result == ""


def test_parse_10k_item_1a_html_input():
    """Parser accepts HTML input and strips tags correctly."""
    result = parse_10k_item_1a(_SYNTHETIC_10K_HTML)
    assert result != ""
    assert "Supply chain disruption risk" in result
    # HTML entity for em-dash stripped, not leaked
    assert "&#8217;" not in result


# ---------------------------------------------------------------------------
# 5. parse_10k_item_7 unit tests
# ---------------------------------------------------------------------------

def test_parse_10k_item_7_extracts_mda():
    result = parse_10k_item_7(_SYNTHETIC_10K)
    assert result != ""
    assert "Management" in result or "OVERVIEW" in result


def test_parse_10k_item_7_contains_key_content():
    result = parse_10k_item_7(_SYNTHETIC_10K)
    assert "OVERVIEW" in result
    assert "REVENUE" in result
    assert "10.5 billion" in result


def test_parse_10k_item_7_does_not_include_item_7a():
    result = parse_10k_item_7(_SYNTHETIC_10K)
    assert "Quantitative and Qualitative Disclosures" not in result


def test_parse_10k_item_7_does_not_include_item_8():
    result = parse_10k_item_7(_SYNTHETIC_10K)
    assert "Financial Statements and Supplementary Data" not in result
    assert "See the consolidated financial statements" not in result


def test_parse_10k_item_7_not_found_returns_empty():
    result = parse_10k_item_7("Item 1. Business\nWe make widgets.\nItem 8. Financials\n")
    assert result == ""


def test_parse_10k_item_7_html_input():
    result = parse_10k_item_7(_SYNTHETIC_10K_HTML)
    assert result != ""
    assert "Revenue increased" in result
    # HTML entity &amp; should be converted to &, not leaked raw
    assert "&amp;" not in result


# ---------------------------------------------------------------------------
# 6. load_skill("sec_edgar") resolves from real library
# ---------------------------------------------------------------------------

def test_load_skill_sec_edgar_resolves():
    """Confirm the real library scan picks up sec_edgar."""
    from lighthouse_ai.skills import discover_skills
    manifests = discover_skills(_LIBRARY_DIR)
    assert "sec_edgar" in manifests, (
        f"sec_edgar not found in discovered skills: {list(manifests.keys())}"
    )
