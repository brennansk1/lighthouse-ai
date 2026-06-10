"""Offline tests for the SL8 economic-data skill family.

Covers all 6 skills: fred, bea, bls, world_bank, oecd, census.

For each skill:
  1. Skill loads successfully (manifest parses, import guard passes, entrypoints callable).
  2. Manifest fields are correctly declared (tier A, signed, temporal_tools, output_shape, etc.).
  3. run() returns Documents tagged with skill_id and grade via monkeypatched adapters.
  4. run() swallows exceptions gracefully (returns []).
  5. EgressBlocked degrades gracefully (returns [], result.ok=True).
  6. Empty result from adapter yields a thin run.
  7. No community tag on signed skills.
  8. Source-specific metadata is preserved after tagging.
  9. Watchable skills (fred, bls) have run_watchable; non-watchable (bea, world_bank, oecd, census) do not.
  10. Import guard audit passes.

No datetime.now() at import. All fixtures are deterministic and offline.
"""

from __future__ import annotations

import os

import pytest

from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.skills import load_skill, run_skill, run_watchable

# ---------------------------------------------------------------------------
# Canned fixture data
# ---------------------------------------------------------------------------

_FRED_DOCS = [
    Document(
        id="fred:UNRATE",
        text="Unemployment Rate. The unemployment rate represents the number of unemployed.",
        metadata={
            "source": "fred",
            "url": "https://fred.stlouisfed.org/series/UNRATE",
            "grade": "A",
            "title": "Unemployment Rate",
            "series_id": "UNRATE",
            "frequency": "Monthly",
            "units": "Percent",
            "seasonal_adjustment": "Seasonally Adjusted",
            "observation_start": "1948-01-01",
            "observation_end": "2025-01-01",
        },
    ),
    Document(
        id="fred:GDPC1",
        text="Real Gross Domestic Product.",
        metadata={
            "source": "fred",
            "url": "https://fred.stlouisfed.org/series/GDPC1",
            "grade": "A",
            "title": "Real Gross Domestic Product",
            "series_id": "GDPC1",
            "frequency": "Quarterly",
            "units": "Billions of Chained 2017 Dollars",
            "seasonal_adjustment": "Seasonally Adjusted Annual Rate",
            "observation_start": "1947-01-01",
            "observation_end": "2024-07-01",
        },
    ),
]

_FRED_RELEASE_DOCS = [
    Document(
        id="fred:release:10",
        text="Employment Situation",
        metadata={
            "source": "fred",
            "url": "https://www.bls.gov/news.release/empsit.nr0.htm",
            "grade": "A",
            "title": "Employment Situation",
            "release_id": "10",
            "press_release": True,
        },
    ),
]

_BEA_DOCS = [
    Document(
        id="bea:dataset:NIPA",
        text="National Income and Product Accounts",
        metadata={
            "source": "bea",
            "url": "https://apps.bea.gov/api/data/?&UserID=KEY&method=GetData&DataSetName=NIPA",
            "grade": "A",
            "title": "National Income and Product Accounts",
            "dataset_name": "NIPA",
        },
    ),
]

_BLS_DOCS = [
    Document(
        id="bls:LNS14000000",
        text="BLS series: Unemployment Rate (LNS14000000)",
        metadata={
            "source": "bls",
            "url": "https://data.bls.gov/timeseries/LNS14000000",
            "grade": "A",
            "title": "Unemployment Rate",
            "series_id": "LNS14000000",
        },
    ),
]

_BLS_SURVEY_DOCS = [
    Document(
        id="bls:survey:CES",
        text="Current Employment Statistics",
        metadata={
            "source": "bls",
            "url": "https://www.bls.gov/ces/",
            "grade": "A",
            "title": "Current Employment Statistics",
            "survey_abbreviation": "CES",
        },
    ),
]

_WB_DOCS = [
    Document(
        id="worldbank:indicator:NY.GDP.MKTP.CD",
        text="GDP (current US$). GDP at purchaser's prices is the sum of gross value added.",
        metadata={
            "source": "world_bank",
            "url": "https://data.worldbank.org/indicator/NY.GDP.MKTP.CD",
            "grade": "A",
            "title": "GDP (current US$)",
            "indicator_id": "NY.GDP.MKTP.CD",
            "source_note": "GDP at purchaser's prices is the sum of gross value added.",
        },
    ),
]

_OECD_DOCS = [
    Document(
        id="oecd:dataset:OECD.SDD.NAD,DSD_NAMAIN1@DF_TABLE14",
        text="Productivity and ULC — National Accounts",
        metadata={
            "source": "oecd",
            "url": "https://data.oecd.org/",
            "grade": "A",
            "title": "Productivity and ULC — National Accounts",
            "dataset_id": "OECD.SDD.NAD,DSD_NAMAIN1@DF_TABLE14A,1.0",
        },
    ),
]

_CENSUS_DOCS = [
    Document(
        id="census:dataset:American Community Survey 5-Year Data",
        text="American Community Survey 5-Year Data. ACS 5-year estimates for all geographies",
        metadata={
            "source": "census",
            "url": "https://api.census.gov/data/2022/acs/acs5",
            "grade": "A",
            "title": "American Community Survey 5-Year Data",
            "dataset_id": "acs/acs5",
            "vintage": "2022",
        },
    ),
]

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fred_skill(monkeypatch):
    # FRED hard-requires a key; the runner now pre-flights it, so a configured
    # key is the precondition for these "skill runs + tags docs" tests.
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    return load_skill("fred")


@pytest.fixture()
def bea_skill(monkeypatch):
    monkeypatch.setenv("BEA_API_KEY", "test-key")
    return load_skill("bea")


@pytest.fixture()
def bls_skill():
    return load_skill("bls")


@pytest.fixture()
def world_bank_skill():
    return load_skill("world_bank")


@pytest.fixture()
def oecd_skill():
    return load_skill("oecd")


@pytest.fixture()
def census_skill():
    return load_skill("census")


# ===========================================================================
# FRED skill tests
# ===========================================================================


def test_load_skill_fred_succeeds(fred_skill):
    assert fred_skill.manifest.id == "fred"
    assert callable(fred_skill.entrypoint)
    assert fred_skill.watchable_entrypoint is not None


def test_fred_manifest_fields(fred_skill):
    m = fred_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert m.temporal_tools is True
    assert "investigate" in m.modes_natural_fit
    assert "survey" in m.modes_natural_fit
    assert "reconstruct" in m.modes_natural_fit
    assert "api.stlouisfed.org" in m.allowed_domains
    assert "list_releases" in m.watchable_tools


def test_fred_run_returns_tagged_documents(monkeypatch, fred_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.fred.search_series",
        lambda *a, **kw: _FRED_DOCS[:2],
    )
    result = run_skill(fred_skill, "unemployment rate", broker=broker)
    assert result.ok
    assert len(result.documents) == 2
    for doc in result.documents:
        assert doc.metadata["skill_id"] == "fred"
        assert doc.metadata["grade"] == "A"
        assert doc.metadata["fetch_backend"] == "tier-a"


def test_fred_declares_required_key(fred_skill):
    assert fred_skill.manifest.requires_key_env == ("FRED_API_KEY",)


def test_keyless_source_declares_no_required_key():
    # BLS works keyless (lower rate limit) — it must NOT be blocked by a pre-flight.
    assert load_skill("bls").manifest.requires_key_env == ()


def test_fred_preflight_short_circuits_without_key(monkeypatch, broker):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    skill = load_skill("fred")
    calls = {"n": 0}

    def _spy(*a, **k):
        calls["n"] += 1
        return []

    monkeypatch.setattr("lighthouse_ai.sources.fred.search_series", _spy)
    result = run_skill(skill, "unemployment", broker=broker)
    assert not result.ok
    assert "FRED_API_KEY" in result.error           # actionable, names the env var
    assert result.documents == []
    assert result.fetches == 0 and calls["n"] == 0   # never hit the network


def test_fred_run_no_community_tag(monkeypatch, fred_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.fred.search_series",
        lambda *a, **kw: _FRED_DOCS[:1],
    )
    result = run_skill(fred_skill, "test", broker=broker)
    assert "community" not in result.documents[0].metadata


def test_fred_run_preserves_series_metadata(monkeypatch, fred_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.fred.search_series",
        lambda *a, **kw: _FRED_DOCS[:1],
    )
    result = run_skill(fred_skill, "unemployment", broker=broker)
    doc = result.documents[0]
    assert doc.metadata["series_id"] == "UNRATE"
    assert doc.metadata["frequency"] == "Monthly"
    assert doc.metadata["units"] == "Percent"


def test_fred_run_empty_is_thin(monkeypatch, fred_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.fred.search_series",
        lambda *a, **kw: [],
    )
    result = run_skill(fred_skill, "obscure xyz", broker=broker)
    assert result.thin
    assert result.documents == []


def test_fred_run_swallows_exception(monkeypatch, fred_skill, broker):
    def _raise(*a, **kw):
        raise RuntimeError("network error")

    monkeypatch.setattr("lighthouse_ai.sources.fred.search_series", _raise)
    result = run_skill(fred_skill, "unemployment", broker=broker)
    assert result.documents == []


def test_fred_run_degrades_on_egress_block(monkeypatch, fred_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'api.stlouisfed.org' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.fred.search_series", _blocked)
    result = run_skill(fred_skill, "unemployment", broker=broker)
    assert result.documents == []
    assert result.ok


def test_fred_watchable_since_none_returns_all(monkeypatch, fred_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.fred.list_releases",
        lambda *a, **kw: list(_FRED_RELEASE_DOCS),
    )
    result = run_watchable(fred_skill, "employment", since=None, broker=broker)
    assert result.ok
    assert len(result.documents) == 1


def test_fred_watchable_documents_tagged(monkeypatch, fred_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.fred.list_releases",
        lambda *a, **kw: _FRED_RELEASE_DOCS[:1],
    )
    result = run_watchable(fred_skill, "employment", since=None, broker=broker)
    assert result.ok
    assert result.documents[0].metadata["skill_id"] == "fred"


def test_fred_watchable_swallows_exception(monkeypatch, fred_skill, broker):
    def _raise(*a, **kw):
        raise RuntimeError("timeout")

    monkeypatch.setattr("lighthouse_ai.sources.fred.list_releases", _raise)
    result = run_watchable(fred_skill, "employment", since=None, broker=broker)
    assert result.documents == []


def test_fred_import_guard_passes(fred_skill):
    from lighthouse_ai.skills.registry import _audit_skill_imports
    _audit_skill_imports(fred_skill.path)


# ===========================================================================
# BEA skill tests
# ===========================================================================


def test_load_skill_bea_succeeds(bea_skill):
    assert bea_skill.manifest.id == "bea"
    assert callable(bea_skill.entrypoint)


def test_bea_manifest_fields(bea_skill):
    m = bea_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert m.temporal_tools is True
    assert "investigate" in m.modes_natural_fit
    assert "apps.bea.gov" in m.allowed_domains


def test_bea_not_watchable(bea_skill):
    assert bea_skill.manifest.watchable is False


def test_bea_run_returns_tagged_documents(monkeypatch, bea_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.bea.search_dataset",
        lambda *a, **kw: _BEA_DOCS[:1],
    )
    result = run_skill(bea_skill, "GDP national accounts", broker=broker)
    assert result.ok
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "bea"
    assert doc.metadata["grade"] == "A"
    assert doc.metadata["fetch_backend"] == "tier-a"


def test_bea_run_preserves_metadata(monkeypatch, bea_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.bea.search_dataset",
        lambda *a, **kw: _BEA_DOCS[:1],
    )
    result = run_skill(bea_skill, "NIPA", broker=broker)
    assert result.documents[0].metadata["dataset_name"] == "NIPA"


def test_bea_run_empty_is_thin(monkeypatch, bea_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.bea.search_dataset",
        lambda *a, **kw: [],
    )
    result = run_skill(bea_skill, "obscure xyz", broker=broker)
    assert result.thin


def test_bea_run_swallows_exception(monkeypatch, bea_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.bea.search_dataset",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("down")),
    )
    result = run_skill(bea_skill, "GDP", broker=broker)
    assert result.documents == []


def test_bea_run_degrades_on_egress_block(monkeypatch, bea_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'apps.bea.gov' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.bea.search_dataset", _blocked)
    result = run_skill(bea_skill, "gdp", broker=broker)
    assert result.documents == []
    assert result.ok


def test_bea_import_guard_passes(bea_skill):
    from lighthouse_ai.skills.registry import _audit_skill_imports
    _audit_skill_imports(bea_skill.path)


# ===========================================================================
# BLS skill tests
# ===========================================================================


def test_load_skill_bls_succeeds(bls_skill):
    assert bls_skill.manifest.id == "bls"
    assert callable(bls_skill.entrypoint)
    assert bls_skill.watchable_entrypoint is not None


def test_bls_manifest_fields(bls_skill):
    m = bls_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert m.temporal_tools is True
    assert "investigate" in m.modes_natural_fit
    assert "api.bls.gov" in m.allowed_domains
    assert "list_releases" in m.watchable_tools


def test_bls_run_returns_tagged_documents(monkeypatch, bls_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.bls.search_series",
        lambda *a, **kw: _BLS_DOCS[:1],
    )
    result = run_skill(bls_skill, "unemployment rate", broker=broker)
    assert result.ok
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "bls"
    assert doc.metadata["grade"] == "A"
    assert doc.metadata["fetch_backend"] == "tier-a"


def test_bls_run_preserves_series_id(monkeypatch, bls_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.bls.search_series",
        lambda *a, **kw: _BLS_DOCS[:1],
    )
    result = run_skill(bls_skill, "unemployment", broker=broker)
    assert result.documents[0].metadata["series_id"] == "LNS14000000"


def test_bls_run_empty_is_thin(monkeypatch, bls_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.bls.search_series",
        lambda *a, **kw: [],
    )
    result = run_skill(bls_skill, "zzz", broker=broker)
    assert result.thin


def test_bls_run_swallows_exception(monkeypatch, bls_skill, broker):
    def _raise(*a, **kw):
        raise RuntimeError("error")

    monkeypatch.setattr("lighthouse_ai.sources.bls.search_series", _raise)
    result = run_skill(bls_skill, "cpi", broker=broker)
    assert result.documents == []


def test_bls_run_degrades_on_egress_block(monkeypatch, bls_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'api.bls.gov' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.bls.search_series", _blocked)
    result = run_skill(bls_skill, "employment", broker=broker)
    assert result.documents == []
    assert result.ok


def test_bls_watchable_returns_survey_docs(monkeypatch, bls_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.bls.list_releases",
        lambda *a, **kw: list(_BLS_SURVEY_DOCS),
    )
    result = run_watchable(bls_skill, "employment", since=None, broker=broker)
    assert result.ok
    assert len(result.documents) == 1
    assert result.documents[0].metadata["skill_id"] == "bls"


def test_bls_watchable_swallows_exception(monkeypatch, bls_skill, broker):
    def _raise(*a, **kw):
        raise RuntimeError("timeout")

    monkeypatch.setattr("lighthouse_ai.sources.bls.list_releases", _raise)
    result = run_watchable(bls_skill, "employment", since=None, broker=broker)
    assert result.documents == []


def test_bls_import_guard_passes(bls_skill):
    from lighthouse_ai.skills.registry import _audit_skill_imports
    _audit_skill_imports(bls_skill.path)


# ===========================================================================
# World Bank skill tests
# ===========================================================================


def test_load_skill_world_bank_succeeds(world_bank_skill):
    assert world_bank_skill.manifest.id == "world_bank"
    assert callable(world_bank_skill.entrypoint)


def test_world_bank_manifest_fields(world_bank_skill):
    m = world_bank_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert m.temporal_tools is True
    assert "investigate" in m.modes_natural_fit
    assert "api.worldbank.org" in m.allowed_domains


def test_world_bank_not_watchable(world_bank_skill):
    assert world_bank_skill.manifest.watchable is False


def test_world_bank_run_returns_tagged_documents(monkeypatch, world_bank_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.world_bank.search_indicator",
        lambda *a, **kw: _WB_DOCS[:1],
    )
    result = run_skill(world_bank_skill, "GDP current US dollars", broker=broker)
    assert result.ok
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "world_bank"
    assert doc.metadata["grade"] == "A"


def test_world_bank_run_preserves_indicator_id(monkeypatch, world_bank_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.world_bank.search_indicator",
        lambda *a, **kw: _WB_DOCS[:1],
    )
    result = run_skill(world_bank_skill, "GDP", broker=broker)
    assert result.documents[0].metadata["indicator_id"] == "NY.GDP.MKTP.CD"


def test_world_bank_run_empty_is_thin(monkeypatch, world_bank_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.world_bank.search_indicator",
        lambda *a, **kw: [],
    )
    result = run_skill(world_bank_skill, "zzz", broker=broker)
    assert result.thin


def test_world_bank_run_swallows_exception(monkeypatch, world_bank_skill, broker):
    def _raise(*a, **kw):
        raise RuntimeError("down")

    monkeypatch.setattr("lighthouse_ai.sources.world_bank.search_indicator", _raise)
    result = run_skill(world_bank_skill, "gdp", broker=broker)
    assert result.documents == []


def test_world_bank_run_degrades_on_egress_block(monkeypatch, world_bank_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'api.worldbank.org' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.world_bank.search_indicator", _blocked)
    result = run_skill(world_bank_skill, "gdp", broker=broker)
    assert result.documents == []
    assert result.ok


def test_world_bank_import_guard_passes(world_bank_skill):
    from lighthouse_ai.skills.registry import _audit_skill_imports
    _audit_skill_imports(world_bank_skill.path)


# ===========================================================================
# OECD skill tests
# ===========================================================================


def test_load_skill_oecd_succeeds(oecd_skill):
    assert oecd_skill.manifest.id == "oecd"
    assert callable(oecd_skill.entrypoint)


def test_oecd_manifest_fields(oecd_skill):
    m = oecd_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert m.temporal_tools is True
    assert "investigate" in m.modes_natural_fit
    assert "sdmx.oecd.org" in m.allowed_domains


def test_oecd_not_watchable(oecd_skill):
    assert oecd_skill.manifest.watchable is False


def test_oecd_run_returns_tagged_documents(monkeypatch, oecd_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.oecd.search_dataset",
        lambda *a, **kw: _OECD_DOCS[:1],
    )
    result = run_skill(oecd_skill, "labour productivity", broker=broker)
    assert result.ok
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "oecd"
    assert doc.metadata["grade"] == "A"


def test_oecd_run_preserves_dataset_id(monkeypatch, oecd_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.oecd.search_dataset",
        lambda *a, **kw: _OECD_DOCS[:1],
    )
    result = run_skill(oecd_skill, "productivity", broker=broker)
    assert "dataset_id" in result.documents[0].metadata


def test_oecd_run_empty_is_thin(monkeypatch, oecd_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.oecd.search_dataset",
        lambda *a, **kw: [],
    )
    result = run_skill(oecd_skill, "zzz", broker=broker)
    assert result.thin


def test_oecd_run_swallows_exception(monkeypatch, oecd_skill, broker):
    def _raise(*a, **kw):
        raise RuntimeError("error")

    monkeypatch.setattr("lighthouse_ai.sources.oecd.search_dataset", _raise)
    result = run_skill(oecd_skill, "gdp", broker=broker)
    assert result.documents == []


def test_oecd_run_degrades_on_egress_block(monkeypatch, oecd_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'sdmx.oecd.org' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.oecd.search_dataset", _blocked)
    result = run_skill(oecd_skill, "productivity", broker=broker)
    assert result.documents == []
    assert result.ok


def test_oecd_import_guard_passes(oecd_skill):
    from lighthouse_ai.skills.registry import _audit_skill_imports
    _audit_skill_imports(oecd_skill.path)


# ===========================================================================
# Census skill tests
# ===========================================================================


def test_load_skill_census_succeeds(census_skill):
    assert census_skill.manifest.id == "census"
    assert callable(census_skill.entrypoint)


def test_census_manifest_fields(census_skill):
    m = census_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert "investigate" in m.modes_natural_fit
    assert "api.census.gov" in m.allowed_domains


def test_census_not_watchable(census_skill):
    assert census_skill.manifest.watchable is False


def test_census_run_returns_tagged_documents(monkeypatch, census_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.census.search_dataset",
        lambda *a, **kw: _CENSUS_DOCS[:1],
    )
    result = run_skill(census_skill, "American Community Survey", broker=broker)
    assert result.ok
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "census"
    assert doc.metadata["grade"] == "A"
    assert doc.metadata["fetch_backend"] == "tier-a"


def test_census_run_preserves_metadata(monkeypatch, census_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.census.search_dataset",
        lambda *a, **kw: _CENSUS_DOCS[:1],
    )
    result = run_skill(census_skill, "acs", broker=broker)
    assert result.documents[0].metadata["vintage"] == "2022"


def test_census_run_empty_is_thin(monkeypatch, census_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.census.search_dataset",
        lambda *a, **kw: [],
    )
    result = run_skill(census_skill, "zzz", broker=broker)
    assert result.thin


def test_census_run_swallows_exception(monkeypatch, census_skill, broker):
    def _raise(*a, **kw):
        raise RuntimeError("down")

    monkeypatch.setattr("lighthouse_ai.sources.census.search_dataset", _raise)
    result = run_skill(census_skill, "demographics", broker=broker)
    assert result.documents == []


def test_census_run_degrades_on_egress_block(monkeypatch, census_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'api.census.gov' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.census.search_dataset", _blocked)
    result = run_skill(census_skill, "demographics", broker=broker)
    assert result.documents == []
    assert result.ok


def test_census_import_guard_passes(census_skill):
    from lighthouse_ai.skills.registry import _audit_skill_imports
    _audit_skill_imports(census_skill.path)


# ===========================================================================
# discover_skills — all 6 econ IDs present
# ===========================================================================


def test_discover_skills_includes_all_six_econ():
    from lighthouse_ai.skills import discover_skills
    manifests = discover_skills()
    econ_ids = {"fred", "bea", "bls", "world_bank", "oecd", "census"}
    found = econ_ids & set(manifests.keys())
    assert found == econ_ids, f"Missing: {econ_ids - found}"


# ===========================================================================
# Live / integration tests (opt-in)
# ===========================================================================


@pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="set LIGHTHOUSE_REAL_BACKEND=1 to run live tests",
)
def test_live_fred_run(tmp_path):
    skill = load_skill("fred")
    broker = build_default_broker(tmp_path)
    result = run_skill(skill, "unemployment rate", broker=broker)
    assert isinstance(result.documents, list)


@pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="set LIGHTHOUSE_REAL_BACKEND=1 to run live tests",
)
def test_live_world_bank_run(tmp_path):
    skill = load_skill("world_bank")
    broker = build_default_broker(tmp_path)
    result = run_skill(skill, "GDP per capita", broker=broker)
    assert isinstance(result.documents, list)
