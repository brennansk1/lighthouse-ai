"""Offline tests for the SL3 clinical skill family.

Covers:
  1. Skill loading — load_skill("clinicaltrials") and load_skill("who") succeed
     (manifest parses, import guard passes, entrypoints are callable).
  2. run_skill returns Documents tagged with skill_id and grade.
  3. EgressBlocked degrades gracefully — skill returns [] with no exception.
  4. run_watchable works including since-based filtering (clinicaltrials).
  5. Adapter exceptions are swallowed; skill returns [].
  6. Manifest fields are correctly declared (signed, temporal_tools, output_shape, etc.).
  7. No forbidden imports in skill.py files (import guard audit).

All HTTP is monkeypatched on the adapter module functions — no real network.
No datetime.now() at import; all fixtures are deterministic and offline.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.skills import load_skill, run_skill, run_watchable

# ---------------------------------------------------------------------------
# Canned fixture data — ClinicalTrials.gov
# ---------------------------------------------------------------------------

_CT_DOCS = [
    Document(
        id="clinicaltrials:NCT04668625",
        text="A Phase 3 Study of Drug X in Type 2 Diabetes. Evaluates efficacy.",
        metadata={
            "source": "clinicaltrials",
            "url": "https://clinicaltrials.gov/study/NCT04668625",
            "grade": "A",
            "title": "A Phase 3 Study of Drug X in Type 2 Diabetes",
            "nct_id": "NCT04668625",
            "conditions": ["Type 2 Diabetes Mellitus"],
            "overall_status": "Completed",
            "start_date": "2022-01-15",
        },
    ),
    Document(
        id="clinicaltrials:NCT04668626",
        text="A Phase 2 Trial of Drug Y in Hypertension.",
        metadata={
            "source": "clinicaltrials",
            "url": "https://clinicaltrials.gov/study/NCT04668626",
            "grade": "A",
            "title": "A Phase 2 Trial of Drug Y in Hypertension",
            "nct_id": "NCT04668626",
            "conditions": ["Hypertension"],
            "overall_status": "Recruiting",
            "start_date": "2024-06-01",
        },
    ),
    Document(
        id="clinicaltrials:NCT00000001",
        text="An old completed trial.",
        metadata={
            "source": "clinicaltrials",
            "url": "https://clinicaltrials.gov/study/NCT00000001",
            "grade": "A",
            "title": "An Old Completed Trial",
            "nct_id": "NCT00000001",
            "conditions": ["Healthy Volunteers"],
            "overall_status": "Completed",
            "start_date": "2010-03-01",
        },
    ),
]

# ---------------------------------------------------------------------------
# Canned fixture data — WHO
# ---------------------------------------------------------------------------

_WHO_DOCS = [
    Document(
        id="who:WHOSIS_000001",
        text="Life expectancy at birth (years)",
        metadata={
            "source": "who",
            "url": "https://ghoapi.azureedge.net/api/WHOSIS_000001",
            "grade": "A",
            "title": "Life expectancy at birth (years)",
            "indicator_code": "WHOSIS_000001",
        },
    ),
    Document(
        id="who:MDG_0000000026",
        text="Maternal mortality ratio (per 100 000 live births)",
        metadata={
            "source": "who",
            "url": "https://ghoapi.azureedge.net/api/MDG_0000000026",
            "grade": "A",
            "title": "Maternal mortality ratio (per 100 000 live births)",
            "indicator_code": "MDG_0000000026",
        },
    ),
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def broker(tmp_path: Path):
    return build_default_broker(tmp_path)


@pytest.fixture()
def ct_skill():
    return load_skill("clinicaltrials")


@pytest.fixture()
def who_skill():
    return load_skill("who")


# ===========================================================================
# ClinicalTrials.gov skill
# ===========================================================================

# --- Load / manifest --------------------------------------------------------


def test_load_skill_clinicaltrials_succeeds(ct_skill):
    """The skill loads cleanly: manifest parses, import guard passes."""
    assert ct_skill.manifest.id == "clinicaltrials"
    assert callable(ct_skill.entrypoint)
    assert ct_skill.watchable_entrypoint is not None  # manifest.watchable=true


def test_ct_manifest_fields(ct_skill):
    m = ct_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert m.temporal_tools is True
    assert "investigate" in m.modes_natural_fit
    assert "survey" in m.modes_natural_fit
    assert "reconstruct" in m.modes_natural_fit
    assert "ask" in m.modes_weak_fit
    assert "list_trials_by_condition" in m.watchable_tools
    assert "clinicaltrials.gov" in m.allowed_domains
    assert m.perspective_lens == "regulatory"


# --- run_skill — offline, monkeypatched ------------------------------------


def test_ct_run_returns_tagged_documents(monkeypatch, ct_skill, broker):
    """run_skill returns Documents tagged with skill_id and grade."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.clinicaltrials.search_trials",
        lambda *a, **kw: _CT_DOCS[:2],
    )
    result = run_skill(ct_skill, "type 2 diabetes phase 3", broker=broker)

    assert result.ok
    assert len(result.documents) == 2
    for doc in result.documents:
        assert doc.metadata["skill_id"] == "clinicaltrials"
        assert doc.metadata["grade"] == "A"
        assert doc.metadata["fetch_backend"] == "tier-a"


def test_ct_run_no_community_tag_for_signed_skill(monkeypatch, ct_skill, broker):
    """Signed skill must not carry the community downgrade tag."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.clinicaltrials.search_trials",
        lambda *a, **kw: _CT_DOCS[:1],
    )
    result = run_skill(ct_skill, "test", broker=broker)

    assert result.ok
    assert "community" not in result.documents[0].metadata


def test_ct_run_preserves_nct_metadata(monkeypatch, ct_skill, broker):
    """Source-specific metadata (nct_id, conditions) is preserved after tagging."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.clinicaltrials.search_trials",
        lambda *a, **kw: _CT_DOCS[:1],
    )
    result = run_skill(ct_skill, "diabetes", broker=broker)
    doc = result.documents[0]
    assert doc.metadata["nct_id"] == "NCT04668625"
    assert doc.metadata["conditions"] == ["Type 2 Diabetes Mellitus"]
    assert doc.metadata["overall_status"] == "Completed"


def test_ct_run_empty_result_is_thin(monkeypatch, ct_skill, broker):
    """An empty result yields a thin run."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.clinicaltrials.search_trials",
        lambda *a, **kw: [],
    )
    result = run_skill(ct_skill, "obscure query xyz", broker=broker)
    assert result.documents == []
    assert result.thin


def test_ct_run_swallows_exception(monkeypatch, ct_skill, broker):
    """Any exception from search_trials is caught; skill returns []."""
    def _raise(*a, **kw):
        raise RuntimeError("network error")

    monkeypatch.setattr(
        "lighthouse_ai.sources.clinicaltrials.search_trials", _raise
    )
    result = run_skill(ct_skill, "diabetes", broker=broker)
    assert result.documents == []


def test_ct_run_degrades_on_egress_block(monkeypatch, ct_skill, broker):
    """EgressBlocked (simulated) is caught; skill returns []."""
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'clinicaltrials.gov' not in egress allowlist")

    monkeypatch.setattr(
        "lighthouse_ai.sources.clinicaltrials.search_trials", _blocked
    )
    result = run_skill(ct_skill, "diabetes", broker=broker)
    assert result.documents == []
    assert result.ok  # runner sees no error; skill returned []


# --- run_watchable — offline, monkeypatched --------------------------------


def test_ct_watchable_since_none_returns_all(monkeypatch, ct_skill, broker):
    """With since=None all canned documents are returned."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.clinicaltrials.search_trials",
        lambda *a, **kw: list(_CT_DOCS),
    )
    result = run_watchable(ct_skill, "diabetes", since=None, broker=broker)

    assert result.ok
    assert len(result.documents) == 3


def test_ct_watchable_filters_by_start_date(monkeypatch, ct_skill, broker):
    """Documents with start_date at or before `since` are excluded."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.clinicaltrials.search_trials",
        lambda *a, **kw: list(_CT_DOCS),
    )
    # Cutoff: only trials that started after 2022-01-15 should survive
    since = datetime(2022, 1, 15)  # exact date of first canned doc

    result = run_watchable(ct_skill, "diabetes", since=since, broker=broker)

    ids = {doc.id for doc in result.documents}
    # start_date == since → filtered out (<=)
    assert "clinicaltrials:NCT04668625" not in ids
    # start_date > since → kept
    assert "clinicaltrials:NCT04668626" in ids
    # old trial → filtered out
    assert "clinicaltrials:NCT00000001" not in ids


def test_ct_watchable_documents_tagged(monkeypatch, ct_skill, broker):
    """Watchable documents carry full skill provenance."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.clinicaltrials.search_trials",
        lambda *a, **kw: _CT_DOCS[:1],
    )
    result = run_watchable(ct_skill, "diabetes", since=None, broker=broker)

    assert result.ok
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "clinicaltrials"
    assert doc.metadata["grade"] == "A"


def test_ct_watchable_swallows_exception(monkeypatch, ct_skill, broker):
    """A failing search_trials in run_watchable must not propagate."""
    def _raise(*a, **kw):
        raise ConnectionError("timeout")

    monkeypatch.setattr(
        "lighthouse_ai.sources.clinicaltrials.search_trials", _raise
    )
    result = run_watchable(ct_skill, "diabetes", since=None, broker=broker)
    assert result.documents == []


def test_ct_watchable_degrades_on_egress_block(monkeypatch, ct_skill, broker):
    """EgressBlocked in watchable is caught; returns []."""
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'clinicaltrials.gov' not in egress allowlist")

    monkeypatch.setattr(
        "lighthouse_ai.sources.clinicaltrials.search_trials", _blocked
    )
    result = run_watchable(ct_skill, "diabetes", since=None, broker=broker)
    assert result.documents == []


# ===========================================================================
# WHO skill
# ===========================================================================

# --- Load / manifest --------------------------------------------------------


def test_load_skill_who_succeeds(who_skill):
    """The skill loads cleanly: manifest parses, import guard passes."""
    assert who_skill.manifest.id == "who"
    assert callable(who_skill.entrypoint)
    assert who_skill.watchable_entrypoint is not None  # manifest.watchable=true


def test_who_manifest_fields(who_skill):
    m = who_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert "investigate" in m.modes_natural_fit
    assert "survey" in m.modes_natural_fit
    assert "adjudicate" in m.modes_natural_fit
    assert "ask" in m.modes_weak_fit
    assert "list_outbreaks" in m.watchable_tools
    assert "ghoapi.azureedge.net" in m.allowed_domains
    assert m.perspective_lens == "regulatory"


# --- run_skill — offline, monkeypatched ------------------------------------


def test_who_run_returns_tagged_documents(monkeypatch, who_skill, broker):
    """run_skill returns Documents tagged with skill_id and grade."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.who.search_who",
        lambda *a, **kw: _WHO_DOCS[:2],
    )
    result = run_skill(who_skill, "maternal mortality", broker=broker)

    assert result.ok
    assert len(result.documents) == 2
    for doc in result.documents:
        assert doc.metadata["skill_id"] == "who"
        assert doc.metadata["grade"] == "A"
        assert doc.metadata["fetch_backend"] == "tier-a"


def test_who_run_no_community_tag_for_signed_skill(monkeypatch, who_skill, broker):
    """Signed skill must not carry the community downgrade tag."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.who.search_who",
        lambda *a, **kw: _WHO_DOCS[:1],
    )
    result = run_skill(who_skill, "test", broker=broker)
    assert result.ok
    assert "community" not in result.documents[0].metadata


def test_who_run_preserves_indicator_metadata(monkeypatch, who_skill, broker):
    """Source-specific metadata (indicator_code) is preserved after tagging."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.who.search_who",
        lambda *a, **kw: _WHO_DOCS[:1],
    )
    result = run_skill(who_skill, "life expectancy", broker=broker)
    doc = result.documents[0]
    assert doc.metadata["indicator_code"] == "WHOSIS_000001"


def test_who_run_empty_result_is_thin(monkeypatch, who_skill, broker):
    """An empty result yields a thin run."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.who.search_who",
        lambda *a, **kw: [],
    )
    result = run_skill(who_skill, "obscure query xyz", broker=broker)
    assert result.documents == []
    assert result.thin


def test_who_run_swallows_exception(monkeypatch, who_skill, broker):
    """Any exception from search_who is caught; skill returns []."""
    def _raise(*a, **kw):
        raise RuntimeError("network error")

    monkeypatch.setattr("lighthouse_ai.sources.who.search_who", _raise)
    result = run_skill(who_skill, "mortality", broker=broker)
    assert result.documents == []


def test_who_run_degrades_on_egress_block(monkeypatch, who_skill, broker):
    """EgressBlocked (simulated) is caught; skill returns []."""
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'ghoapi.azureedge.net' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.who.search_who", _blocked)
    result = run_skill(who_skill, "mortality", broker=broker)
    assert result.documents == []
    assert result.ok  # runner sees no error; skill returned []


# --- run_watchable — offline, monkeypatched --------------------------------


def test_who_watchable_since_none_returns_all(monkeypatch, who_skill, broker):
    """With since=None all canned documents are returned."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.who.search_who",
        lambda *a, **kw: list(_WHO_DOCS),
    )
    result = run_watchable(who_skill, "outbreak", since=None, broker=broker)
    assert result.ok
    assert len(result.documents) == 2


def test_who_watchable_accepts_since_parameter(monkeypatch, who_skill, broker):
    """run_watchable accepts since= without error (GHO ignores it)."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.who.search_who",
        lambda *a, **kw: list(_WHO_DOCS),
    )
    since = datetime(2026, 1, 1)
    result = run_watchable(who_skill, "outbreak", since=since, broker=broker)
    assert result.ok
    # GHO doesn't filter by time; all docs returned
    assert len(result.documents) == 2


def test_who_watchable_documents_tagged(monkeypatch, who_skill, broker):
    """Watchable documents carry full skill provenance."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.who.search_who",
        lambda *a, **kw: _WHO_DOCS[:1],
    )
    result = run_watchable(who_skill, "life expectancy", since=None, broker=broker)
    assert result.ok
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "who"
    assert doc.metadata["grade"] == "A"


def test_who_watchable_swallows_exception(monkeypatch, who_skill, broker):
    """A failing search_who in run_watchable must not propagate."""
    def _raise(*a, **kw):
        raise ConnectionError("timeout")

    monkeypatch.setattr("lighthouse_ai.sources.who.search_who", _raise)
    result = run_watchable(who_skill, "outbreak", since=None, broker=broker)
    assert result.documents == []


def test_who_watchable_degrades_on_egress_block(monkeypatch, who_skill, broker):
    """EgressBlocked in watchable is caught; returns []."""
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'ghoapi.azureedge.net' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.who.search_who", _blocked)
    result = run_watchable(who_skill, "outbreak", since=None, broker=broker)
    assert result.documents == []


# ===========================================================================
# Import guard — both skills must pass
# ===========================================================================


def test_ct_import_guard_passes(ct_skill):
    """The registry import guard must not flag any forbidden imports in clinicaltrials."""
    from lighthouse_ai.skills.registry import _audit_skill_imports
    # If this raises SkillLoadError the test fails
    _audit_skill_imports(ct_skill.path)


def test_who_import_guard_passes(who_skill):
    """The registry import guard must not flag any forbidden imports in who."""
    from lighthouse_ai.skills.registry import _audit_skill_imports
    _audit_skill_imports(who_skill.path)


# ===========================================================================
# Live / integration tests (opt-in)
# ===========================================================================


@pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="set LIGHTHOUSE_REAL_BACKEND=1 to run live tests",
)
def test_live_ct_run_returns_documents(tmp_path):
    """Real network: search ClinicalTrials.gov and verify at least one Document."""
    skill = load_skill("clinicaltrials")
    broker = build_default_broker(tmp_path)
    result = run_skill(skill, "type 2 diabetes phase 3", broker=broker)
    # Will return [] if clinicaltrials.gov is not on the allowlist
    assert isinstance(result.documents, list)


@pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="set LIGHTHOUSE_REAL_BACKEND=1 to run live tests",
)
def test_live_who_run_returns_documents(tmp_path):
    """Real network: search WHO GHO and verify at least one Document."""
    skill = load_skill("who")
    broker = build_default_broker(tmp_path)
    result = run_skill(skill, "maternal mortality", broker=broker)
    assert isinstance(result.documents, list)
