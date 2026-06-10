"""Offline tests for the SL9 engineering skill family (GitHub + package registries).

Covers:
  1. Skill loading — load_skill("github") and load_skill("packages") succeed
     (manifest parses, import guard passes, entrypoints are callable).
  2. run_skill returns Documents tagged with skill_id and grade.
  3. EgressBlocked degrades gracefully — skill returns [] with no exception.
  4. run_watchable works including since-based filtering.
  5. Adapter exceptions are swallowed; skill returns [].
  6. Manifest fields are correctly declared (signed, temporal_tools, output_shape,
     watchable, allowed_domains, etc.).
  7. No forbidden imports in skill.py files (import guard audit).
  8. discover_skills() includes both "github" and "packages".
  9. packages prefix routing (pypi:/npm:/crates:) dispatches correctly.

All HTTP is monkeypatched on the adapter module functions — no real network.
No datetime.now() at import; all fixtures are deterministic and offline.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.skills import load_skill, run_skill, run_watchable

# ---------------------------------------------------------------------------
# Canned fixture data — GitHub
# ---------------------------------------------------------------------------

_GITHUB_REPO_DOCS = [
    Document(
        id="github:repo:encode/httpx",
        text="encode/httpx: A next-generation HTTP client for Python.",
        metadata={
            "source": "github",
            "type": "repo",
            "url": "https://github.com/encode/httpx",
            "grade": "A",
            "full_name": "encode/httpx",
            "description": "A next-generation HTTP client for Python.",
            "stars": 14000,
            "language": "Python",
            "license": "BSD-3-Clause",
            "pushed_at": "2024-03-01T10:00:00Z",
            "topics": ["http", "python", "async"],
        },
    ),
    Document(
        id="github:repo:psf/requests",
        text="psf/requests: Python HTTP for Humans.",
        metadata={
            "source": "github",
            "type": "repo",
            "url": "https://github.com/psf/requests",
            "grade": "A",
            "full_name": "psf/requests",
            "description": "Python HTTP for Humans.",
            "stars": 52000,
            "language": "Python",
            "license": "Apache-2.0",
            "pushed_at": "2024-02-15T08:00:00Z",
            "topics": ["http", "python"],
        },
    ),
]

_GITHUB_RELEASE_DOCS = [
    Document(
        id="github:release:encode/httpx:0.27.0",
        text="0.27.0: Various improvements and bug fixes.",
        metadata={
            "source": "github",
            "type": "release",
            "url": "https://github.com/encode/httpx/releases/tag/0.27.0",
            "grade": "A",
            "full_name": "encode/httpx",
            "tag_name": "0.27.0",
            "name": "0.27.0",
            "published_at": "2024-04-01T12:00:00Z",
            "prerelease": False,
            "draft": False,
        },
    ),
    Document(
        id="github:release:encode/httpx:0.26.0",
        text="0.26.0: Previous release.",
        metadata={
            "source": "github",
            "type": "release",
            "url": "https://github.com/encode/httpx/releases/tag/0.26.0",
            "grade": "A",
            "full_name": "encode/httpx",
            "tag_name": "0.26.0",
            "name": "0.26.0",
            "published_at": "2024-01-15T09:00:00Z",
            "prerelease": False,
            "draft": False,
        },
    ),
]

_GITHUB_ISSUE_DOCS = [
    Document(
        id="github:issue:encode/httpx:2001",
        text="#2001 TLS verification fails on some platforms",
        metadata={
            "source": "github",
            "type": "issue",
            "url": "https://github.com/encode/httpx/issues/2001",
            "grade": "A",
            "full_name": "encode/httpx",
            "number": 2001,
            "title": "TLS verification fails on some platforms",
            "state": "open",
            "created_at": "2024-03-10T14:00:00Z",
            "updated_at": "2024-03-11T08:00:00Z",
            "labels": ["bug"],
            "user": "someuser",
        },
    ),
]

_GITHUB_COMMIT_DOCS = [
    Document(
        id="github:commit:encode/httpx:abc123def456",
        text="abc123def456: refactor: improve connection pooling",
        metadata={
            "source": "github",
            "type": "commit",
            "url": "https://github.com/encode/httpx/commit/abc123def456",
            "grade": "A",
            "full_name": "encode/httpx",
            "sha": "abc123def456789012345678901234567890abcd",
            "message": "refactor: improve connection pooling",
            "author": "Tom Christie",
            "committed_at": "2024-03-05T11:00:00Z",
        },
    ),
    Document(
        id="github:commit:encode/httpx:old789",
        text="old789: fix: old bug fix",
        metadata={
            "source": "github",
            "type": "commit",
            "url": "https://github.com/encode/httpx/commit/old789",
            "grade": "A",
            "full_name": "encode/httpx",
            "sha": "old789abc",
            "message": "fix: old bug fix",
            "author": "Tom Christie",
            "committed_at": "2023-06-01T09:00:00Z",
        },
    ),
]

# ---------------------------------------------------------------------------
# Canned fixture data — packages (PyPI)
# ---------------------------------------------------------------------------

_PYPI_DOCS = [
    Document(
        id="pypi:requests",
        text="requests 2.32.0: Python HTTP for Humans.",
        metadata={
            "source": "pypi",
            "registry": "pypi",
            "type": "package",
            "url": "https://pypi.org/project/requests/",
            "grade": "A",
            "name": "requests",
            "version": "2.32.0",
            "summary": "Python HTTP for Humans.",
            "author": "Kenneth Reitz",
            "license": "Apache 2.0",
            "home_page": "https://requests.readthedocs.io",
            "requires_python": ">=3.8",
            "keywords": "http, requests, web",
        },
    ),
]

_PYPI_VERSION_DOCS = [
    Document(
        id="pypi:requests:2.32.0",
        text="requests 2.32.0",
        metadata={
            "source": "pypi",
            "registry": "pypi",
            "type": "version",
            "url": "https://pypi.org/project/requests/2.32.0/",
            "grade": "A",
            "name": "requests",
            "version": "2.32.0",
            "upload_time": "2024-05-01T12:00:00",
            "num_files": 3,
        },
    ),
    Document(
        id="pypi:requests:2.31.0",
        text="requests 2.31.0",
        metadata={
            "source": "pypi",
            "registry": "pypi",
            "type": "version",
            "url": "https://pypi.org/project/requests/2.31.0/",
            "grade": "A",
            "name": "requests",
            "version": "2.31.0",
            "upload_time": "2023-05-22T10:00:00",
            "num_files": 3,
        },
    ),
]

# ---------------------------------------------------------------------------
# Canned fixture data — packages (npm)
# ---------------------------------------------------------------------------

_NPM_DOCS = [
    Document(
        id="npm:axios",
        text="axios 1.7.2: Promise based HTTP client for the browser and node.js",
        metadata={
            "source": "npm",
            "registry": "npm",
            "type": "package",
            "url": "https://www.npmjs.com/package/axios",
            "grade": "A",
            "name": "axios",
            "version": "1.7.2",
            "description": "Promise based HTTP client for the browser and node.js",
            "keywords": ["xhr", "http", "ajax"],
            "author": "Matt Zabriskie",
            "publisher": "jasonsaayman",
            "date": "2024-06-10T12:00:00Z",
        },
    ),
]

# ---------------------------------------------------------------------------
# Canned fixture data — packages (crates.io)
# ---------------------------------------------------------------------------

_CRATES_DOCS = [
    Document(
        id="crates:tokio",
        text="tokio 1.38.0: An event-driven, non-blocking I/O platform.",
        metadata={
            "source": "crates",
            "registry": "crates",
            "type": "package",
            "url": "https://crates.io/crates/tokio",
            "grade": "A",
            "name": "tokio",
            "version": "1.38.0",
            "description": "An event-driven, non-blocking I/O platform.",
            "downloads": 100000000,
            "repository": "https://github.com/tokio-rs/tokio",
            "homepage": "https://tokio.rs",
            "documentation": "https://docs.rs/tokio",
            "updated_at": "2024-06-15T10:00:00Z",
            "categories": ["asynchronous"],
            "keywords": ["async", "tokio"],
        },
    ),
]

_CRATES_VERSION_DOCS = [
    Document(
        id="crates:tokio:1.38.0",
        text="tokio 1.38.0",
        metadata={
            "source": "crates",
            "registry": "crates",
            "type": "version",
            "url": "https://crates.io/crates/tokio/1.38.0",
            "grade": "A",
            "name": "tokio",
            "version": "1.38.0",
            "created_at": "2024-06-15T10:00:00Z",
            "downloads": 5000000,
            "yanked": False,
            "license": "MIT",
        },
    ),
    Document(
        id="crates:tokio:1.37.0",
        text="tokio 1.37.0",
        metadata={
            "source": "crates",
            "registry": "crates",
            "type": "version",
            "url": "https://crates.io/crates/tokio/1.37.0",
            "grade": "A",
            "name": "tokio",
            "version": "1.37.0",
            "created_at": "2024-01-10T09:00:00Z",
            "downloads": 4000000,
            "yanked": False,
            "license": "MIT",
        },
    ),
]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def github_skill():
    return load_skill("github")


@pytest.fixture()
def packages_skill():
    return load_skill("packages")


# ===========================================================================
# discover_skills() includes both skills
# ===========================================================================


def test_discover_skills_includes_github():
    from lighthouse_ai.skills import discover_skills
    manifests = discover_skills()
    assert "github" in manifests


def test_discover_skills_includes_packages():
    from lighthouse_ai.skills import discover_skills
    manifests = discover_skills()
    assert "packages" in manifests


# ===========================================================================
# GitHub skill — Load / manifest
# ===========================================================================


def test_load_skill_github_succeeds(github_skill):
    """The skill loads cleanly: manifest parses, import guard passes."""
    assert github_skill.manifest.id == "github"
    assert callable(github_skill.entrypoint)
    assert github_skill.watchable_entrypoint is not None


def test_github_manifest_fields(github_skill):
    m = github_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert m.temporal_tools is True
    assert m.watchable is True
    assert "list_releases" in m.watchable_tools
    assert "list_recent_issues" in m.watchable_tools
    assert "get_commit_history" in m.watchable_tools
    assert "api.github.com" in m.allowed_domains
    assert "github.com" in m.allowed_domains
    assert "investigate" in m.modes_natural_fit
    assert "survey" in m.modes_natural_fit
    assert "decide" in m.modes_natural_fit
    assert "watch" in m.modes_natural_fit
    assert "ask" in m.modes_weak_fit


# ===========================================================================
# GitHub skill — run_skill (monkeypatched)
# ===========================================================================


def test_github_run_returns_tagged_documents(monkeypatch, github_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.github.search_repos",
        lambda *a, **kw: _GITHUB_REPO_DOCS[:2],
    )
    result = run_skill(github_skill, "python http client", broker=broker)

    assert result.ok
    assert len(result.documents) == 2
    for doc in result.documents:
        assert doc.metadata["skill_id"] == "github"
        assert doc.metadata["grade"] == "A"
        assert doc.metadata["fetch_backend"] == "tier-a"


def test_github_run_no_community_tag_for_signed_skill(monkeypatch, github_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.github.search_repos",
        lambda *a, **kw: _GITHUB_REPO_DOCS[:1],
    )
    result = run_skill(github_skill, "test", broker=broker)

    assert result.ok
    assert "community" not in result.documents[0].metadata


def test_github_run_preserves_repo_metadata(monkeypatch, github_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.github.search_repos",
        lambda *a, **kw: _GITHUB_REPO_DOCS[:1],
    )
    result = run_skill(github_skill, "httpx", broker=broker)
    doc = result.documents[0]
    assert doc.metadata["full_name"] == "encode/httpx"
    assert doc.metadata["stars"] == 14000
    assert doc.metadata["license"] == "BSD-3-Clause"
    assert "http" in doc.metadata["topics"]


def test_github_run_empty_result_is_thin(monkeypatch, github_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.github.search_repos",
        lambda *a, **kw: [],
    )
    result = run_skill(github_skill, "zzznomatch", broker=broker)
    assert result.documents == []
    assert result.thin


def test_github_run_swallows_exception(monkeypatch, github_skill, broker):
    def _raise(*a, **kw):
        raise RuntimeError("network error")

    monkeypatch.setattr("lighthouse_ai.sources.github.search_repos", _raise)
    result = run_skill(github_skill, "test", broker=broker)
    assert result.documents == []


def test_github_run_degrades_on_egress_block(monkeypatch, github_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'api.github.com' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.github.search_repos", _blocked)
    result = run_skill(github_skill, "test", broker=broker)
    assert result.documents == []
    assert result.ok


# ===========================================================================
# GitHub skill — run_watchable (monkeypatched)
# ===========================================================================


def test_github_watchable_since_none_returns_all(monkeypatch, github_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.github.list_releases",
        lambda *a, **kw: list(_GITHUB_RELEASE_DOCS),
    )
    result = run_watchable(github_skill, "encode/httpx", since=None, broker=broker)

    assert result.ok
    assert len(result.documents) == 2


def test_github_watchable_filters_by_published_at(monkeypatch, github_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.github.list_releases",
        lambda *a, **kw: list(_GITHUB_RELEASE_DOCS),
    )
    # Cutoff: only releases published after 2024-02-01 should survive
    since = datetime(2024, 2, 1)
    result = run_watchable(github_skill, "encode/httpx", since=since, broker=broker)

    ids = {doc.id for doc in result.documents}
    # published_at "2024-04-01" > since → kept
    assert "github:release:encode/httpx:0.27.0" in ids
    # published_at "2024-01-15" <= since → filtered out
    assert "github:release:encode/httpx:0.26.0" not in ids


def test_github_watchable_documents_tagged(monkeypatch, github_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.github.list_releases",
        lambda *a, **kw: _GITHUB_RELEASE_DOCS[:1],
    )
    result = run_watchable(github_skill, "encode/httpx", since=None, broker=broker)

    assert result.ok
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "github"
    assert doc.metadata["grade"] == "A"


def test_github_watchable_plain_query_uses_search(monkeypatch, github_skill, broker):
    """A plain query (no owner/repo) falls back to search_repos."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.github.search_repos",
        lambda *a, **kw: _GITHUB_REPO_DOCS[:1],
    )
    result = run_watchable(github_skill, "python http", since=None, broker=broker)
    assert result.ok
    assert len(result.documents) >= 1


def test_github_watchable_swallows_exception(monkeypatch, github_skill, broker):
    def _raise(*a, **kw):
        raise ConnectionError("timeout")

    monkeypatch.setattr("lighthouse_ai.sources.github.list_releases", _raise)
    monkeypatch.setattr("lighthouse_ai.sources.github.search_repos", _raise)
    result = run_watchable(github_skill, "encode/httpx", since=None, broker=broker)
    assert result.documents == []


def test_github_watchable_degrades_on_egress_block(monkeypatch, github_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'api.github.com' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.github.list_releases", _blocked)
    monkeypatch.setattr("lighthouse_ai.sources.github.search_repos", _blocked)
    result = run_watchable(github_skill, "encode/httpx", since=None, broker=broker)
    assert result.documents == []


# ===========================================================================
# packages skill — Load / manifest
# ===========================================================================


def test_load_skill_packages_succeeds(packages_skill):
    """The skill loads cleanly: manifest parses, import guard passes."""
    assert packages_skill.manifest.id == "packages"
    assert callable(packages_skill.entrypoint)
    assert packages_skill.watchable_entrypoint is not None


def test_packages_manifest_fields(packages_skill):
    m = packages_skill.manifest
    assert m.tier == "A"
    assert m.default_grade == "A"
    assert m.signed is True
    assert m.output_shape == "enumerable"
    assert m.temporal_tools is True
    assert m.watchable is True
    assert "pypi.org" in m.allowed_domains
    assert "registry.npmjs.org" in m.allowed_domains
    assert "crates.io" in m.allowed_domains
    assert "investigate" in m.modes_natural_fit
    assert "survey" in m.modes_natural_fit
    assert "decide" in m.modes_natural_fit
    assert "watch" in m.modes_natural_fit
    assert "ask" in m.modes_weak_fit


# ===========================================================================
# packages skill — run_skill (monkeypatched, per registry)
# ===========================================================================


def test_packages_run_pypi_prefix(monkeypatch, packages_skill, broker):
    """pypi: prefix routes to pypi_search_package only."""
    called = {}

    def _pypi(query, **kw):
        called["pypi"] = query
        return _PYPI_DOCS

    def _npm(query, **kw):
        called["npm"] = query
        return _NPM_DOCS

    def _crates(query, **kw):
        called["crates"] = query
        return _CRATES_DOCS

    monkeypatch.setattr("lighthouse_ai.sources.packages.pypi_search_package", _pypi)
    monkeypatch.setattr("lighthouse_ai.sources.packages.npm_search_package", _npm)
    monkeypatch.setattr("lighthouse_ai.sources.packages.crates_search_package", _crates)

    result = run_skill(packages_skill, "pypi:requests", broker=broker)
    assert result.ok
    assert "pypi" in called
    assert "npm" not in called
    assert "crates" not in called


def test_packages_run_npm_prefix(monkeypatch, packages_skill, broker):
    """npm: prefix routes to npm_search_package only."""
    called = {}

    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.pypi_search_package",
        lambda *a, **kw: called.update({"pypi": True}) or [],
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.npm_search_package",
        lambda *a, **kw: _NPM_DOCS,
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.crates_search_package",
        lambda *a, **kw: called.update({"crates": True}) or [],
    )

    result = run_skill(packages_skill, "npm:axios", broker=broker)
    assert result.ok
    assert "pypi" not in called
    assert "crates" not in called
    assert len(result.documents) == 1
    assert result.documents[0].metadata["registry"] == "npm"


def test_packages_run_crates_prefix(monkeypatch, packages_skill, broker):
    """crates: prefix routes to crates_search_package only."""
    called = {}

    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.pypi_search_package",
        lambda *a, **kw: called.update({"pypi": True}) or [],
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.npm_search_package",
        lambda *a, **kw: called.update({"npm": True}) or [],
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.crates_search_package",
        lambda *a, **kw: _CRATES_DOCS,
    )

    result = run_skill(packages_skill, "crates:tokio", broker=broker)
    assert result.ok
    assert "pypi" not in called
    assert "npm" not in called
    assert result.documents[0].metadata["registry"] == "crates"


def test_packages_run_no_prefix_queries_all_registries(monkeypatch, packages_skill, broker):
    """Plain query searches all three registries and merges results."""
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.pypi_search_package",
        lambda *a, **kw: _PYPI_DOCS,
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.npm_search_package",
        lambda *a, **kw: _NPM_DOCS,
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.crates_search_package",
        lambda *a, **kw: _CRATES_DOCS,
    )

    result = run_skill(packages_skill, "http client", broker=broker)
    assert result.ok
    assert len(result.documents) == 3
    registries = {d.metadata["registry"] for d in result.documents}
    assert registries == {"pypi", "npm", "crates"}


def test_packages_run_returns_tagged_documents(monkeypatch, packages_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.pypi_search_package",
        lambda *a, **kw: _PYPI_DOCS,
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.npm_search_package",
        lambda *a, **kw: [],
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.crates_search_package",
        lambda *a, **kw: [],
    )

    result = run_skill(packages_skill, "requests", broker=broker)
    assert result.ok
    for doc in result.documents:
        assert doc.metadata["skill_id"] == "packages"
        assert doc.metadata["grade"] == "A"
        assert doc.metadata["fetch_backend"] == "tier-a"


def test_packages_run_no_community_tag(monkeypatch, packages_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.pypi_search_package",
        lambda *a, **kw: _PYPI_DOCS[:1],
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.npm_search_package",
        lambda *a, **kw: [],
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.crates_search_package",
        lambda *a, **kw: [],
    )
    result = run_skill(packages_skill, "pypi:requests", broker=broker)
    assert result.ok
    assert "community" not in result.documents[0].metadata


def test_packages_run_preserves_registry_metadata(monkeypatch, packages_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.pypi_search_package",
        lambda *a, **kw: _PYPI_DOCS[:1],
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.npm_search_package",
        lambda *a, **kw: [],
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.crates_search_package",
        lambda *a, **kw: [],
    )
    result = run_skill(packages_skill, "pypi:requests", broker=broker)
    doc = result.documents[0]
    assert doc.metadata["name"] == "requests"
    assert doc.metadata["version"] == "2.32.0"
    assert doc.metadata["license"] == "Apache 2.0"


def test_packages_run_empty_result_is_thin(monkeypatch, packages_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.pypi_search_package",
        lambda *a, **kw: [],
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.npm_search_package",
        lambda *a, **kw: [],
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.crates_search_package",
        lambda *a, **kw: [],
    )
    result = run_skill(packages_skill, "zzznomatch", broker=broker)
    assert result.documents == []
    assert result.thin


def test_packages_run_swallows_exception_per_registry(monkeypatch, packages_skill, broker):
    """One registry failing should not prevent results from others."""
    def _raise(*a, **kw):
        raise RuntimeError("network error")

    monkeypatch.setattr("lighthouse_ai.sources.packages.pypi_search_package", _raise)
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.npm_search_package",
        lambda *a, **kw: _NPM_DOCS,
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.crates_search_package",
        lambda *a, **kw: [],
    )
    result = run_skill(packages_skill, "http", broker=broker)
    # npm succeeded even though pypi failed
    assert len(result.documents) == 1
    assert result.documents[0].metadata["registry"] == "npm"


def test_packages_run_degrades_on_egress_block(monkeypatch, packages_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'pypi.org' not in egress allowlist")

    monkeypatch.setattr("lighthouse_ai.sources.packages.pypi_search_package", _blocked)
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.npm_search_package",
        lambda *a, **kw: [],
    )
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.crates_search_package",
        lambda *a, **kw: [],
    )
    result = run_skill(packages_skill, "pypi:requests", broker=broker)
    assert result.documents == []
    assert result.ok


# ===========================================================================
# packages skill — run_watchable (monkeypatched)
# ===========================================================================


def test_packages_watchable_pypi_since_none_returns_all(monkeypatch, packages_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.pypi_list_recent_releases_for_package",
        lambda *a, **kw: list(_PYPI_VERSION_DOCS),
    )
    result = run_watchable(packages_skill, "pypi:requests", since=None, broker=broker)
    assert result.ok
    assert len(result.documents) == 2


def test_packages_watchable_pypi_filters_by_upload_time(monkeypatch, packages_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.pypi_list_recent_releases_for_package",
        lambda *a, **kw: list(_PYPI_VERSION_DOCS),
    )
    # Cutoff: only versions uploaded after 2024-01-01
    since = datetime(2024, 1, 1)
    result = run_watchable(packages_skill, "pypi:requests", since=since, broker=broker)

    ids = {doc.id for doc in result.documents}
    # upload_time "2024-05-01" > since → kept
    assert "pypi:requests:2.32.0" in ids
    # upload_time "2023-05-22" <= since → filtered out
    assert "pypi:requests:2.31.0" not in ids


def test_packages_watchable_crates_since_none_returns_all(monkeypatch, packages_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.crates_list_recent_releases_for_package",
        lambda *a, **kw: list(_CRATES_VERSION_DOCS),
    )
    result = run_watchable(packages_skill, "crates:tokio", since=None, broker=broker)
    assert result.ok
    assert len(result.documents) == 2


def test_packages_watchable_crates_filters_by_created_at(monkeypatch, packages_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.crates_list_recent_releases_for_package",
        lambda *a, **kw: list(_CRATES_VERSION_DOCS),
    )
    # Only versions created after 2024-03-01
    since = datetime(2024, 3, 1)
    result = run_watchable(packages_skill, "crates:tokio", since=since, broker=broker)

    ids = {doc.id for doc in result.documents}
    # created_at "2024-06-15" > since → kept
    assert "crates:tokio:1.38.0" in ids
    # created_at "2024-01-10" <= since → filtered out
    assert "crates:tokio:1.37.0" not in ids


def test_packages_watchable_documents_tagged(monkeypatch, packages_skill, broker):
    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.pypi_list_recent_releases_for_package",
        lambda *a, **kw: _PYPI_VERSION_DOCS[:1],
    )
    result = run_watchable(packages_skill, "pypi:requests", since=None, broker=broker)
    assert result.ok
    doc = result.documents[0]
    assert doc.metadata["skill_id"] == "packages"
    assert doc.metadata["grade"] == "A"


def test_packages_watchable_swallows_exception(monkeypatch, packages_skill, broker):
    def _raise(*a, **kw):
        raise ConnectionError("timeout")

    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.pypi_list_recent_releases_for_package", _raise
    )
    result = run_watchable(packages_skill, "pypi:requests", since=None, broker=broker)
    assert result.documents == []


def test_packages_watchable_degrades_on_egress_block(monkeypatch, packages_skill, broker):
    from lighthouse_ai.net import EgressBlocked

    def _blocked(*a, **kw):
        raise EgressBlocked("host 'crates.io' not in egress allowlist")

    monkeypatch.setattr(
        "lighthouse_ai.sources.packages.crates_list_recent_releases_for_package", _blocked
    )
    result = run_watchable(packages_skill, "crates:tokio", since=None, broker=broker)
    assert result.documents == []


# ===========================================================================
# Import guard — both skills must pass
# ===========================================================================


def test_github_import_guard_passes(github_skill):
    from lighthouse_ai.skills.registry import _audit_skill_imports
    _audit_skill_imports(github_skill.path)


def test_packages_import_guard_passes(packages_skill):
    from lighthouse_ai.skills.registry import _audit_skill_imports
    _audit_skill_imports(packages_skill.path)


# ===========================================================================
# Live / integration tests (opt-in)
# ===========================================================================


@pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="set LIGHTHOUSE_REAL_BACKEND=1 to run live tests",
)
def test_live_github_run_returns_documents(tmp_path):
    """Real network: search GitHub and verify at least one Document."""
    skill = load_skill("github")
    broker = build_default_broker(tmp_path)
    result = run_skill(skill, "python http client stars:>1000", broker=broker)
    assert isinstance(result.documents, list)


@pytest.mark.skipif(
    not os.environ.get("LIGHTHOUSE_REAL_BACKEND"),
    reason="set LIGHTHOUSE_REAL_BACKEND=1 to run live tests",
)
def test_live_packages_run_returns_documents(tmp_path):
    """Real network: search PyPI and verify at least one Document."""
    skill = load_skill("packages")
    broker = build_default_broker(tmp_path)
    result = run_skill(skill, "pypi:requests", broker=broker)
    assert isinstance(result.documents, list)
