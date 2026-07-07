"""Offline tests for the SL5 U.S. federal government skill family.

Covers:
  1. Skill loading — all four skills load successfully (manifest parses,
     import guard passes, entrypoints are callable).
  2. run_skill returns Documents tagged with skill_id and grade.
  3. EgressBlocked degrades gracefully — skill returns [] with no exception.
  4. run_watchable works including since-based filtering.
  5. Adapter exceptions are swallowed; skill returns [].
  6. Manifest fields are correctly declared (signed, temporal_tools,
     output_shape, watchable, etc.).
  7. No forbidden imports in skill.py files (import guard audit).
  8. discover_skills() includes all four SL5 skill IDs.

All HTTP is monkeypatched on the adapter module functions — no real network.
No datetime.now() at import; all fixtures are deterministic and offline.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.skills import discover_skills, load_skill, run_skill, run_watchable

# ---------------------------------------------------------------------------
# Canned fixture data — Federal Register
# ---------------------------------------------------------------------------

_FR_DOCS = [
    Document(
        id="fedreg:2024-05678",
        text="National Ambient Air Quality Standards for Particulate Matter. This rule revises the NAAQS for PM2.5.",
        metadata={
            "source": "federal_register",
            "url": "https://www.federalregister.gov/documents/2024/02/07/2024-05678/",
            "grade": "A",
            "title": "National Ambient Air Quality Standards for Particulate Matter",
            "document_number": "2024-05678",
            "document_type": "Rule",
            "agency_names": ["Environmental Protection Agency"],
            "publication_date": "2024-02-07",
            "citation": "89 FR 16202",
        },
    ),
    Document(
        id="fedreg:2024-10000",
        text="Proposed Rule on Clean Water Regulations.",
        metadata={
            "source": "federal_register",
            "url": "https://www.federalregister.gov/documents/2024/05/01/2024-10000/",
            "grade": "A",
            "title": "Proposed Rule on Clean Water Regulations",
            "document_number": "2024-10000",
            "document_type": "Proposed Rule",
            "agency_names": ["Environmental Protection Agency"],
            "publication_date": "2024-05-01",
            "citation": "89 FR 36000",
        },
    ),
    Document(
        id="fedreg:2020-00001",
        text="An old rule from 2020.",
        metadata={
            "source": "federal_register",
            "url": "https://www.federalregister.gov/documents/2020/01/01/2020-00001/",
            "grade": "A",
            "title": "An Old Rule from 2020",
            "document_number": "2020-00001",
            "document_type": "Rule",
            "agency_names": ["Department of Justice"],
            "publication_date": "2020-01-01",
            "citation": "85 FR 100",
        },
    ),
]

# ---------------------------------------------------------------------------
# Canned fixture data — regulations.gov
# ---------------------------------------------------------------------------

_REGS_DOCS = [
    Document(
        id="regs:EPA-HQ-OAR-2022-0873",
        text="National Ambient Air Quality Standards for Particulate Matter",
        metadata={
            "source": "regulations_gov",
            "url": "https://www.regulations.gov/docket/EPA-HQ-OAR-2022-0873",
            "grade": "A",
            "title": "National Ambient Air Quality Standards for Particulate Matter",
            "docket_id": "EPA-HQ-OAR-2022-0873",
            "docket_type": "Rulemaking",
            "agency_id": "EPA",
            "last_modified": "2024-02-07T00:00:00Z",
        },
    ),
    Document(
        id="regs:doc:EPA-HQ-OAR-2022-0873-0001",
        text="Proposed Rule Document",
        metadata={
            "source": "regulations_gov",
            "url": "https://www.regulations.gov/document/EPA-HQ-OAR-2022-0873-0001",
            "grade": "A",
            "title": "Proposed Rule Document",
            "document_id": "EPA-HQ-OAR-2022-0873-0001",
            "document_type": "Proposed Rule",
            "agency_id": "EPA",
            "posted_date": "2023-01-27",
            "docket_id": "EPA-HQ-OAR-2022-0873",
        },
    ),
    Document(
        id="regs:doc:EPA-HQ-OAR-2022-0873-0002",
        text="Final Rule Document",
        metadata={
            "source": "regulations_gov",
            "url": "https://www.regulations.gov/document/EPA-HQ-OAR-2022-0873-0002",
            "grade": "A",
            "title": "Final Rule Document",
            "document_id": "EPA-HQ-OAR-2022-0873-0002",
            "document_type": "Rule",
            "agency_id": "EPA",
            "posted_date": "2024-02-07",
            "docket_id": "EPA-HQ-OAR-2022-0873",
        },
    ),
]

# ---------------------------------------------------------------------------
# Canned fixture data — GovInfo
# ---------------------------------------------------------------------------

_GOVINFO_DOCS = [
    Document(
        id="govinfo:CFR-2024-title40-vol6",
        text="Title 40 - Protection of Environment",
        metadata={
            "source": "govinfo",
            "url": "https://www.govinfo.gov/link/cfr/40/6",
            "grade": "A",
            "title": "Title 40 - Protection of Environment",
            "package_id": "CFR-2024-title40-vol6",
            "collection_code": "CFR",
            "date_issued": "2024-01-01",
            "doc_class": "CFR",
        },
    ),
    Document(
        id="govinfo:CREC-2024-04-15",
        text="Congressional Record - Daily Edition for April 15, 2024",
        metadata={
            "source": "govinfo",
            "url": "https://www.govinfo.gov/content/pkg/CREC-2024-04-15",
            "grade": "A",
            "title": "Congressional Record - Daily Edition for April 15, 2024",
            "package_id": "CREC-2024-04-15",
            "collection_code": "CREC",
            "date_issued": "2024-04-15",
            "doc_class": "CREC",
        },
    ),
    Document(
        id="govinfo:CREC-2020-01-01",
        text="Congressional Record - Daily Edition for January 1, 2020",
        metadata={
            "source": "govinfo",
            "url": "https://www.govinfo.gov/content/pkg/CREC-2020-01-01",
            "grade": "A",
            "title": "Congressional Record - Daily Edition for January 1, 2020",
            "package_id": "CREC-2020-01-01",
            "collection_code": "CREC",
            "date_issued": "2020-01-01",
            "doc_class": "CREC",
        },
    ),
]

# ---------------------------------------------------------------------------
# Canned fixture data — Congress.gov
# ---------------------------------------------------------------------------

_CONGRESS_DOCS = [
    Document(
        id="congress:118-HR-5376",
        text="Inflation Reduction Act of 2022. Latest action: Signed by President.",
        metadata={
            "source": "congress_gov",
            "url": "https://api.congress.gov/v3/bill/117/hr/5376",
            "grade": "A",
            "title": "Inflation Reduction Act of 2022",
            "bill_type": "HR",
            "bill_number": "5376",
            "congress": "117",
            "origin_chamber": "House",
            "latest_action_date": "2022-08-16",
            "latest_action_text": "Became Public Law No: 117-169.",
        },
    ),
    Document(
        id="congress:118-S-2299",
        text="Clean Energy Investment Act.",
        metadata={
            "source": "congress_gov",
            "url": "https://api.congress.gov/v3/bill/118/s/2299",
            "grade": "A",
            "title": "Clean Energy Investment Act",
            "bill_type": "S",
            "bill_number": "2299",
            "congress": "118",
            "origin_chamber": "Senate",
            "latest_action_date": "2024-06-01",
            "latest_action_text": "Referred to the Committee on Finance.",
        },
    ),
    Document(
        id="congress:117-HR-0001",
        text="An old bill from 2021.",
        metadata={
            "source": "congress_gov",
            "url": "https://api.congress.gov/v3/bill/117/hr/1",
            "grade": "A",
            "title": "An Old Bill from 2021",
            "bill_type": "HR",
            "bill_number": "1",
            "congress": "117",
            "origin_chamber": "House",
            "latest_action_date": "2021-01-04",
            "latest_action_text": "Referred to Committee.",
        },
    ),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fr_skill():
    return load_skill("federal_register")


@pytest.fixture()
def regs_skill():
    return load_skill("regulations_gov")


@pytest.fixture()
def govinfo_skill():
    return load_skill("govinfo")


@pytest.fixture()
def congress_skill():
    return load_skill("congress")


# ===========================================================================
# discover_skills — all four SL5 IDs present
# ===========================================================================


def test_discover_skills_includes_all_sl5_ids():
    """discover_skills() must include all four SL5 federal skill IDs."""
    manifests = discover_skills()
    for skill_id in ("federal_register", "regulations_gov", "govinfo", "congress"):
        assert skill_id in manifests, f"discover_skills() missing: {skill_id!r}"


# ===========================================================================
# Federal Register skill
# ===========================================================================

# --- Load / manifest --------------------------------------------------------


def test_load_skill_federal_register_succeeds(fr_skill):
    assert fr_skill.manifest.id == "federal_register"
    assert callable(fr_skill.entrypoint)
    assert fr_skill.watchable_entrypoint is not None


def test_fr_manifest_fields(fr_skill):
    m = fr_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert m.temporal_tools is True
    assert "investigate" in m.modes_natural_fit
    assert "survey" in m.modes_natural_fit
    assert "reconstruct" in m.modes_natural_fit
    assert "list_recent_in_agency" in m.watchable_tools
    assert "federalregister.gov" in m.allowed_domains
    assert m.perspective_lens == "regulatory"


# --- run_skill — offline, monkeypatched ------------------------------------


def test_fr_run_returns_tagged_documents(monkeypatch, fr_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.federal_register.search_rules",
        lambda *a, **kw: _FR_DOCS[:2],
    )
    result = run_skill(fr_skill, "EPA clean air", broker=broker)
    assert result.ok
    assert len(result.documents) == 2
    for doc in result.documents:
        assert doc.metadata["skill_id"] == "federal_register"
        assert doc.metadata["grade"] == "A"
        assert doc.metadata["fetch_backend"] == "tier-a"


def test_fr_run_no_community_tag_for_signed_skill(monkeypatch, fr_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.federal_register.search_rules",
        lambda *a, **kw: _FR_DOCS[:1],
    )
    result = run_skill(fr_skill, "test", broker=broker)
    assert result.ok
    assert "community" not in result.documents[0].metadata


def test_fr_run_preserves_metadata(monkeypatch, fr_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.federal_register.search_rules",
        lambda *a, **kw: _FR_DOCS[:1],
    )
    result = run_skill(fr_skill, "air quality", broker=broker)
    doc = result.documents[0]
    assert doc.metadata["document_number"] == "2024-05678"
    assert doc.metadata["document_type"] == "Rule"
    assert doc.metadata["agency_names"] == ["Environmental Protection Agency"]
    assert doc.metadata["publication_date"] == "2024-02-07"


def test_fr_run_empty_result_is_thin(monkeypatch, fr_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.federal_register.search_rules",
        lambda *a, **kw: [],
    )
    result = run_skill(fr_skill, "obscure xyz", broker=broker)
    assert result.documents == []
    assert result.thin


def test_fr_run_swallows_exception(monkeypatch, fr_skill, broker):
    def _raise(*a, **kw):
        raise RuntimeError("network error")

    monkeypatch.setattr("lighthouse_ai.sources.federal_register.search_rules", _raise)
    result = run_skill(fr_skill, "air quality", broker=broker)
    assert result.documents == []


def test_fr_run_degrades_on_egress_block(monkeypatch, fr_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'federalregister.gov' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.federal_register.search_rules", _blocked)
    result = run_skill(fr_skill, "air quality", broker=broker)
    assert result.documents == []
    assert result.ok


# --- run_watchable — offline, monkeypatched --------------------------------


def test_fr_watchable_since_none_returns_all(monkeypatch, fr_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.federal_register.list_recent_in_agency",
        lambda *a, **kw: list(_FR_DOCS),
    )
    result = run_watchable(fr_skill, "epa", since=None, broker=broker)
    assert result.ok
    assert len(result.documents) == 3


def test_fr_watchable_filters_by_publication_date(monkeypatch, fr_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.federal_register.list_recent_in_agency",
        lambda *a, **kw: list(_FR_DOCS),
    )
    since = datetime(2024, 2, 7)  # exact date of first doc
    result = run_watchable(fr_skill, "epa", since=since, broker=broker)
    ids = {doc.id for doc in result.documents}
    # publication_date == since → filtered out (<=)
    assert "fedreg:2024-05678" not in ids
    # publication_date > since → kept
    assert "fedreg:2024-10000" in ids
    # old doc → filtered out
    assert "fedreg:2020-00001" not in ids


def test_fr_watchable_documents_tagged(monkeypatch, fr_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.federal_register.list_recent_in_agency",
        lambda *a, **kw: _FR_DOCS[:1],
    )
    result = run_watchable(fr_skill, "epa", since=None, broker=broker)
    assert result.ok
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "federal_register"
    assert doc.metadata["grade"] == "A"


def test_fr_watchable_swallows_exception(monkeypatch, fr_skill, broker):
    def _raise(*a, **kw):
        raise ConnectionError("timeout")

    monkeypatch.setattr("lighthouse_ai.sources.federal_register.list_recent_in_agency", _raise)
    result = run_watchable(fr_skill, "epa", since=None, broker=broker)
    assert result.documents == []


def test_fr_watchable_degrades_on_egress_block(monkeypatch, fr_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("federalregister.gov not in allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.federal_register.list_recent_in_agency", _blocked)
    result = run_watchable(fr_skill, "epa", since=None, broker=broker)
    assert result.documents == []


# --- import guard -----------------------------------------------------------


def test_fr_import_guard_passes(fr_skill):
    from lighthouse_ai.skills.registry import _audit_skill_imports

    _audit_skill_imports(fr_skill.path)


# ===========================================================================
# regulations.gov skill
# ===========================================================================

# --- Load / manifest --------------------------------------------------------


def test_load_skill_regulations_gov_succeeds(regs_skill):
    assert regs_skill.manifest.id == "regulations_gov"
    assert callable(regs_skill.entrypoint)
    assert regs_skill.watchable_entrypoint is not None


def test_regs_manifest_fields(regs_skill):
    m = regs_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert m.temporal_tools is True
    assert "investigate" in m.modes_natural_fit
    assert "survey" in m.modes_natural_fit
    assert "track_docket_activity" in m.watchable_tools
    assert "api.regulations.gov" in m.allowed_domains
    assert m.perspective_lens == "regulatory"


# --- run_skill — offline, monkeypatched ------------------------------------


def test_regs_run_returns_tagged_documents(monkeypatch, regs_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.regulations_gov.search_dockets",
        lambda *a, **kw: _REGS_DOCS[:2],
    )
    result = run_skill(regs_skill, "EPA particulate matter", broker=broker)
    assert result.ok
    assert len(result.documents) == 2
    for doc in result.documents:
        assert doc.metadata["skill_id"] == "regulations_gov"
        assert doc.metadata["fetch_backend"] == "tier-a"


def test_regs_run_preserves_metadata(monkeypatch, regs_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.regulations_gov.search_dockets",
        lambda *a, **kw: _REGS_DOCS[:1],
    )
    result = run_skill(regs_skill, "particulate matter", broker=broker)
    doc = result.documents[0]
    assert doc.metadata["docket_id"] == "EPA-HQ-OAR-2022-0873"
    assert doc.metadata["agency_id"] == "EPA"


def test_regs_run_empty_result_is_thin(monkeypatch, regs_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.regulations_gov.search_dockets",
        lambda *a, **kw: [],
    )
    result = run_skill(regs_skill, "obscure xyz", broker=broker)
    assert result.documents == []
    assert result.thin


def test_regs_run_swallows_exception(monkeypatch, regs_skill, broker):
    def _raise(*a, **kw):
        raise RuntimeError("network error")

    monkeypatch.setattr("lighthouse_ai.sources.regulations_gov.search_dockets", _raise)
    result = run_skill(regs_skill, "epa", broker=broker)
    assert result.documents == []


def test_regs_run_degrades_on_egress_block(monkeypatch, regs_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'api.regulations.gov' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.regulations_gov.search_dockets", _blocked)
    result = run_skill(regs_skill, "epa", broker=broker)
    assert result.documents == []
    assert result.ok


# --- run_watchable — offline, monkeypatched --------------------------------


def test_regs_watchable_since_none_returns_all(monkeypatch, regs_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.regulations_gov.track_docket_activity",
        lambda *a, **kw: list(_REGS_DOCS[1:]),  # doc records (index 1,2)
    )
    result = run_watchable(regs_skill, "EPA-HQ-OAR-2022-0873", since=None, broker=broker)
    assert result.ok
    assert len(result.documents) == 2


def test_regs_watchable_filters_by_posted_date(monkeypatch, regs_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.regulations_gov.track_docket_activity",
        lambda *a, **kw: list(_REGS_DOCS[1:]),
    )
    since = datetime(2024, 2, 7)  # exact date of final rule
    result = run_watchable(regs_skill, "EPA-HQ-OAR-2022-0873", since=since, broker=broker)
    ids = {doc.id for doc in result.documents}
    # posted_date == since → filtered out
    assert "regs:doc:EPA-HQ-OAR-2022-0873-0002" not in ids
    # posted_date < since → filtered out
    assert "regs:doc:EPA-HQ-OAR-2022-0873-0001" not in ids


def test_regs_watchable_documents_tagged(monkeypatch, regs_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.regulations_gov.track_docket_activity",
        lambda *a, **kw: _REGS_DOCS[1:2],
    )
    result = run_watchable(regs_skill, "EPA-HQ-OAR-2022-0873", since=None, broker=broker)
    assert result.ok
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "regulations_gov"


def test_regs_watchable_swallows_exception(monkeypatch, regs_skill, broker):
    def _raise(*a, **kw):
        raise ConnectionError("timeout")

    monkeypatch.setattr("lighthouse_ai.sources.regulations_gov.track_docket_activity", _raise)
    result = run_watchable(regs_skill, "EPA-HQ-OAR-2022-0873", since=None, broker=broker)
    assert result.documents == []


def test_regs_watchable_degrades_on_egress_block(monkeypatch, regs_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("api.regulations.gov not in allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.regulations_gov.track_docket_activity", _blocked)
    result = run_watchable(regs_skill, "EPA-HQ-OAR-2022-0873", since=None, broker=broker)
    assert result.documents == []


# --- import guard -----------------------------------------------------------


def test_regs_import_guard_passes(regs_skill):
    from lighthouse_ai.skills.registry import _audit_skill_imports

    _audit_skill_imports(regs_skill.path)


# ===========================================================================
# GovInfo skill
# ===========================================================================

# --- Load / manifest --------------------------------------------------------


def test_load_skill_govinfo_succeeds(govinfo_skill):
    assert govinfo_skill.manifest.id == "govinfo"
    assert callable(govinfo_skill.entrypoint)
    assert govinfo_skill.watchable_entrypoint is not None


def test_govinfo_manifest_fields(govinfo_skill):
    m = govinfo_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert m.temporal_tools is True
    assert "investigate" in m.modes_natural_fit
    assert "survey" in m.modes_natural_fit
    assert "reconstruct" in m.modes_natural_fit
    assert "list_recent_in_collection" in m.watchable_tools
    assert "api.govinfo.gov" in m.allowed_domains
    assert m.perspective_lens == "regulatory"


# --- run_skill — offline, monkeypatched ------------------------------------


def test_govinfo_run_returns_tagged_documents(monkeypatch, govinfo_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.govinfo.search_collection",
        lambda *a, **kw: _GOVINFO_DOCS[:2],
    )
    result = run_skill(govinfo_skill, "Clean Air Act CFR title 40", broker=broker)
    assert result.ok
    assert len(result.documents) == 2
    for doc in result.documents:
        assert doc.metadata["skill_id"] == "govinfo"
        assert doc.metadata["grade"] == "A"
        assert doc.metadata["fetch_backend"] == "tier-a"


def test_govinfo_run_preserves_metadata(monkeypatch, govinfo_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.govinfo.search_collection",
        lambda *a, **kw: _GOVINFO_DOCS[:1],
    )
    result = run_skill(govinfo_skill, "CFR title 40", broker=broker)
    doc = result.documents[0]
    assert doc.metadata["package_id"] == "CFR-2024-title40-vol6"
    assert doc.metadata["collection_code"] == "CFR"
    assert doc.metadata["date_issued"] == "2024-01-01"


def test_govinfo_run_empty_result_is_thin(monkeypatch, govinfo_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.govinfo.search_collection",
        lambda *a, **kw: [],
    )
    result = run_skill(govinfo_skill, "obscure xyz", broker=broker)
    assert result.documents == []
    assert result.thin


def test_govinfo_run_swallows_exception(monkeypatch, govinfo_skill, broker):
    def _raise(*a, **kw):
        raise RuntimeError("network error")

    monkeypatch.setattr("lighthouse_ai.sources.govinfo.search_collection", _raise)
    result = run_skill(govinfo_skill, "CFR", broker=broker)
    assert result.documents == []


def test_govinfo_run_degrades_on_egress_block(monkeypatch, govinfo_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'api.govinfo.gov' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.govinfo.search_collection", _blocked)
    result = run_skill(govinfo_skill, "CFR", broker=broker)
    assert result.documents == []
    assert result.ok


# --- run_watchable — offline, monkeypatched --------------------------------


def test_govinfo_watchable_since_none_returns_all(monkeypatch, govinfo_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.govinfo.list_recent_in_collection",
        lambda *a, **kw: list(_GOVINFO_DOCS),
    )
    result = run_watchable(govinfo_skill, "CREC", since=None, broker=broker)
    assert result.ok
    assert len(result.documents) == 3


def test_govinfo_watchable_filters_by_date_issued(monkeypatch, govinfo_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.govinfo.list_recent_in_collection",
        lambda *a, **kw: list(_GOVINFO_DOCS),
    )
    since = datetime(2024, 4, 15)  # exact date of second doc
    result = run_watchable(govinfo_skill, "CREC", since=since, broker=broker)
    ids = {doc.id for doc in result.documents}
    # date_issued == since → filtered out
    assert "govinfo:CREC-2024-04-15" not in ids
    # old doc → filtered out
    assert "govinfo:CREC-2020-01-01" not in ids
    # CFR doc (date_issued < since) → filtered out
    assert "govinfo:CFR-2024-title40-vol6" not in ids


def test_govinfo_watchable_documents_tagged(monkeypatch, govinfo_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.govinfo.list_recent_in_collection",
        lambda *a, **kw: _GOVINFO_DOCS[1:2],
    )
    result = run_watchable(govinfo_skill, "CREC", since=None, broker=broker)
    assert result.ok
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "govinfo"
    assert doc.metadata["grade"] == "A"


def test_govinfo_watchable_swallows_exception(monkeypatch, govinfo_skill, broker):
    def _raise(*a, **kw):
        raise ConnectionError("timeout")

    monkeypatch.setattr("lighthouse_ai.sources.govinfo.list_recent_in_collection", _raise)
    result = run_watchable(govinfo_skill, "CREC", since=None, broker=broker)
    assert result.documents == []


def test_govinfo_watchable_degrades_on_egress_block(monkeypatch, govinfo_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("api.govinfo.gov not in allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.govinfo.list_recent_in_collection", _blocked)
    result = run_watchable(govinfo_skill, "CREC", since=None, broker=broker)
    assert result.documents == []


# --- import guard -----------------------------------------------------------


def test_govinfo_import_guard_passes(govinfo_skill):
    from lighthouse_ai.skills.registry import _audit_skill_imports

    _audit_skill_imports(govinfo_skill.path)


# ===========================================================================
# Congress.gov skill
# ===========================================================================

# --- Load / manifest --------------------------------------------------------


def test_load_skill_congress_succeeds(congress_skill):
    assert congress_skill.manifest.id == "congress"
    assert callable(congress_skill.entrypoint)
    assert congress_skill.watchable_entrypoint is not None


def test_congress_manifest_fields(congress_skill):
    m = congress_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert m.temporal_tools is True
    assert "investigate" in m.modes_natural_fit
    assert "survey" in m.modes_natural_fit
    assert "watch" in m.modes_natural_fit
    assert "track_committee" in m.watchable_tools
    assert "api.congress.gov" in m.allowed_domains
    assert m.perspective_lens == "regulatory"


# --- run_skill — offline, monkeypatched ------------------------------------


def test_congress_run_returns_tagged_documents(monkeypatch, congress_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.congress_gov.search_bills",
        lambda *a, **kw: _CONGRESS_DOCS[:2],
    )
    result = run_skill(congress_skill, "clean energy tax credits", broker=broker)
    assert result.ok
    assert len(result.documents) == 2
    for doc in result.documents:
        assert doc.metadata["skill_id"] == "congress"
        assert doc.metadata["grade"] == "A"
        assert doc.metadata["fetch_backend"] == "tier-a"


def test_congress_run_no_community_tag_for_signed_skill(monkeypatch, congress_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.congress_gov.search_bills",
        lambda *a, **kw: _CONGRESS_DOCS[:1],
    )
    result = run_skill(congress_skill, "test", broker=broker)
    assert result.ok
    assert "community" not in result.documents[0].metadata


def test_congress_run_preserves_metadata(monkeypatch, congress_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.congress_gov.search_bills",
        lambda *a, **kw: _CONGRESS_DOCS[:1],
    )
    result = run_skill(congress_skill, "inflation", broker=broker)
    doc = result.documents[0]
    assert doc.metadata["bill_type"] == "HR"
    assert doc.metadata["bill_number"] == "5376"
    assert doc.metadata["congress"] == "117"
    assert doc.metadata["latest_action_date"] == "2022-08-16"


def test_congress_run_empty_result_is_thin(monkeypatch, congress_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.congress_gov.search_bills",
        lambda *a, **kw: [],
    )
    result = run_skill(congress_skill, "obscure xyz", broker=broker)
    assert result.documents == []
    assert result.thin


def test_congress_run_swallows_exception(monkeypatch, congress_skill, broker):
    def _raise(*a, **kw):
        raise RuntimeError("network error")

    monkeypatch.setattr("lighthouse_ai.sources.congress_gov.search_bills", _raise)
    result = run_skill(congress_skill, "clean energy", broker=broker)
    assert result.documents == []


def test_congress_run_degrades_on_egress_block(monkeypatch, congress_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'api.congress.gov' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.congress_gov.search_bills", _blocked)
    result = run_skill(congress_skill, "clean energy", broker=broker)
    assert result.documents == []
    assert result.ok


# --- run_watchable — offline, monkeypatched --------------------------------


def test_congress_watchable_since_none_returns_all(monkeypatch, congress_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.congress_gov.track_committee",
        lambda *a, **kw: list(_CONGRESS_DOCS),
    )
    result = run_watchable(congress_skill, "hsju00", since=None, broker=broker)
    assert result.ok
    assert len(result.documents) == 3


def test_congress_watchable_filters_by_action_date(monkeypatch, congress_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.congress_gov.track_committee",
        lambda *a, **kw: list(_CONGRESS_DOCS),
    )
    since = datetime(2022, 8, 16)  # exact date of first doc
    result = run_watchable(congress_skill, "hsju00", since=since, broker=broker)
    ids = {doc.id for doc in result.documents}
    # latest_action_date == since → filtered out
    assert "congress:118-HR-5376" not in ids
    # later date → kept
    assert "congress:118-S-2299" in ids
    # old → filtered out
    assert "congress:117-HR-0001" not in ids


def test_congress_watchable_documents_tagged(monkeypatch, congress_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.congress_gov.track_committee",
        lambda *a, **kw: _CONGRESS_DOCS[:1],
    )
    result = run_watchable(congress_skill, "hsju00", since=None, broker=broker)
    assert result.ok
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "congress"
    assert doc.metadata["grade"] == "A"


def test_congress_watchable_swallows_exception(monkeypatch, congress_skill, broker):
    def _raise(*a, **kw):
        raise ConnectionError("timeout")

    monkeypatch.setattr("lighthouse_ai.sources.congress_gov.track_committee", _raise)
    result = run_watchable(congress_skill, "hsju00", since=None, broker=broker)
    assert result.documents == []


def test_congress_watchable_degrades_on_egress_block(monkeypatch, congress_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("api.congress.gov not in allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.congress_gov.track_committee", _blocked)
    result = run_watchable(congress_skill, "hsju00", since=None, broker=broker)
    assert result.documents == []


# --- import guard -----------------------------------------------------------


def test_congress_import_guard_passes(congress_skill):
    from lighthouse_ai.skills.registry import _audit_skill_imports

    _audit_skill_imports(congress_skill.path)


# ===========================================================================
# Live / integration tests (opt-in)
# ===========================================================================


@pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="set LIGHTHOUSE_REAL_BACKEND=1 to run live tests",
)
def test_live_federal_register(tmp_path):
    skill = load_skill("federal_register")
    broker = build_default_broker(tmp_path)
    result = run_skill(skill, "EPA clean air", broker=broker)
    assert isinstance(result.documents, list)


@pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="set LIGHTHOUSE_REAL_BACKEND=1 to run live tests",
)
def test_live_govinfo(tmp_path):
    skill = load_skill("govinfo")
    broker = build_default_broker(tmp_path)
    result = run_skill(skill, "Clean Air Act", broker=broker)
    assert isinstance(result.documents, list)
