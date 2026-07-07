"""Offline tests for the SL9 engineering source adapters.

All HTTP is respx-mocked; no real network is touched.  Each adapter function
is exercised directly (not through a skill) to verify parsing and interface
contract.

Test plan
---------
GitHub adapter:
- search_repos: returns list[Document] from valid /search/repositories response.
- search_repos: extracts full_name, stars, language, license, topics.
- search_repos: respects max_results via per_page param.
- search_repos: raises HTTPStatusError on 4xx/5xx.
- search_repos: uses injected client without closing it.
- fetch_readme: returns single Document with content.
- fetch_readme: returns [] on 404.
- fetch_readme: raises HTTPStatusError on non-404 errors.
- list_releases: returns Documents with tag_name, published_at, prerelease.
- list_releases: raises HTTPStatusError on 4xx/5xx.
- list_recent_issues: returns Documents; excludes PRs.
- list_recent_issues: raises HTTPStatusError on 4xx/5xx.
- get_dependency_graph: returns Documents with package_name, version.
- get_dependency_graph: raises HTTPStatusError on 4xx/5xx.
- get_license: returns single Document with spdx_id.
- get_license: returns [] on 404.
- get_security_advisories: returns Documents with ghsa_id, cve_id, severity.
- get_commit_history: returns Documents with sha, message, committed_at.
- get_commit_history: passes since= as query param.

packages adapter — PyPI:
- pypi_search_package: returns Document for valid exact-name response.
- pypi_search_package: returns [] on 404.
- pypi_search_package: raises HTTPStatusError on non-404 errors.
- pypi_fetch_package_metadata: delegates to pypi_search_package.
- pypi_get_versions: returns version Documents with upload_time.
- pypi_get_versions: returns [] on 404.
- pypi_get_dependencies: returns dep Documents with dependency_spec.
- pypi_get_dependents: returns limitation note Document.
- pypi_list_recent_releases_for_package: delegates to pypi_get_versions.
- pypi_*: uses injected client without closing it.

packages adapter — npm:
- npm_search_package: returns Documents from search response.
- npm_search_package: raises HTTPStatusError on 4xx/5xx.
- npm_fetch_package_metadata: returns single Document on valid response.
- npm_fetch_package_metadata: returns [] on 404.
- npm_get_versions: returns version Documents with published_at.
- npm_get_dependencies: returns dep Documents with dep_name.
- npm_get_dependents: returns limitation note Document.
- npm_list_recent_releases_for_package: delegates to npm_get_versions.
- npm_*: uses injected client without closing it.

packages adapter — crates.io:
- crates_search_package: returns Documents from search response.
- crates_search_package: raises HTTPStatusError on 4xx/5xx.
- crates_fetch_package_metadata: returns single Document.
- crates_fetch_package_metadata: returns [] on 404.
- crates_get_versions: returns version Documents with created_at, yanked.
- crates_get_versions: returns [] on 404.
- crates_get_dependencies: returns dep Documents with dep_name, dep_req.
- crates_get_dependents: returns reverse-dep Documents.
- crates_list_recent_releases_for_package: delegates to crates_get_versions.
- crates_*: uses injected client without closing it.
"""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from lighthouse_ai.rag.chunker import Document
from lighthouse_ai.sources.github import (
    fetch_readme,
    get_commit_history,
    get_dependency_graph,
    get_license,
    get_security_advisories,
    list_recent_issues,
    list_releases,
    search_repos,
)
from lighthouse_ai.sources.packages import (
    crates_fetch_package_metadata,
    crates_get_dependencies,
    crates_get_dependents,
    crates_get_versions,
    crates_list_recent_releases_for_package,
    crates_search_package,
    npm_fetch_package_metadata,
    npm_get_dependencies,
    npm_get_dependents,
    npm_get_versions,
    npm_list_recent_releases_for_package,
    npm_search_package,
    pypi_fetch_package_metadata,
    pypi_get_dependencies,
    pypi_get_dependents,
    pypi_get_versions,
    pypi_list_recent_releases_for_package,
    pypi_search_package,
)

# ---------------------------------------------------------------------------
# GitHub fixture data
# ---------------------------------------------------------------------------

_GH_SEARCH_JSON = {
    "total_count": 2,
    "incomplete_results": False,
    "items": [
        {
            "full_name": "encode/httpx",
            "description": "A next-generation HTTP client for Python.",
            "html_url": "https://github.com/encode/httpx",
            "stargazers_count": 14000,
            "language": "Python",
            "license": {"spdx_id": "BSD-3-Clause"},
            "pushed_at": "2024-03-01T10:00:00Z",
            "topics": ["http", "python", "async"],
        },
        {
            "full_name": "psf/requests",
            "description": "Python HTTP for Humans.",
            "html_url": "https://github.com/psf/requests",
            "stargazers_count": 52000,
            "language": "Python",
            "license": {"spdx_id": "Apache-2.0"},
            "pushed_at": "2024-02-15T08:00:00Z",
            "topics": ["http", "python"],
        },
    ],
}

_GH_README_JSON = {
    "content": base64.b64encode(b"# httpx\nA next-gen HTTP client.").decode() + "\n",
    "html_url": "https://github.com/encode/httpx/blob/main/README.md",
    "sha": "abc123",
    "size": 512,
}

_GH_RELEASES_JSON = [
    {
        "tag_name": "0.27.0",
        "name": "0.27.0",
        "html_url": "https://github.com/encode/httpx/releases/tag/0.27.0",
        "body": "Various improvements.",
        "published_at": "2024-04-01T12:00:00Z",
        "prerelease": False,
        "draft": False,
    },
    {
        "tag_name": "0.26.0",
        "name": "0.26.0",
        "html_url": "https://github.com/encode/httpx/releases/tag/0.26.0",
        "body": "Previous release.",
        "published_at": "2024-01-15T09:00:00Z",
        "prerelease": False,
        "draft": False,
    },
]

_GH_ISSUES_JSON = [
    {
        "number": 2001,
        "title": "TLS verification fails on some platforms",
        "html_url": "https://github.com/encode/httpx/issues/2001",
        "body": "Steps to reproduce...",
        "state": "open",
        "created_at": "2024-03-10T14:00:00Z",
        "updated_at": "2024-03-11T08:00:00Z",
        "labels": [{"name": "bug"}],
        "user": {"login": "someuser"},
    },
    {
        # This is a PR — should be excluded
        "number": 2002,
        "title": "Fix TLS",
        "html_url": "https://github.com/encode/httpx/pull/2002",
        "body": "Fixes #2001",
        "state": "open",
        "created_at": "2024-03-12T10:00:00Z",
        "updated_at": "2024-03-12T10:00:00Z",
        "labels": [],
        "user": {"login": "contributor"},
        "pull_request": {"url": "https://api.github.com/repos/encode/httpx/pulls/2002"},
    },
]

_GH_SBOM_JSON = {
    "sbom": {
        "packages": [
            {
                "name": "pip:httpcore",
                "versionInfo": "1.0.5",
                "licenseConcluded": "BSD-3-Clause",
            },
            {
                "name": "pip:certifi",
                "versionInfo": "2024.2.2",
                "licenseConcluded": "MPL-2.0",
            },
        ]
    }
}

_GH_LICENSE_JSON = {
    "content": base64.b64encode(b"MIT License\n\nCopyright (c) 2024").decode() + "\n",
    "html_url": "https://github.com/encode/httpx/blob/main/LICENSE",
    "sha": "def456",
    "license": {
        "spdx_id": "MIT",
        "name": "MIT License",
    },
}

_GH_ADVISORIES_JSON = [
    {
        "ghsa_id": "GHSA-xxxx-yyyy-zzzz",
        "cve_id": "CVE-2024-12345",
        "summary": "SSRF vulnerability in redirect handling",
        "description": "An attacker could ...",
        "html_url": "https://github.com/encode/httpx/security/advisories/GHSA-xxxx-yyyy-zzzz",
        "severity": "high",
        "published_at": "2024-03-01T10:00:00Z",
        "cvss": {"score": 8.1, "vector_string": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:L/A:N"},
    },
]

_GH_COMMITS_JSON = [
    {
        "sha": "abc123def456789012345678901234567890abcd",
        "html_url": "https://github.com/encode/httpx/commit/abc123def456",
        "commit": {
            "message": "refactor: improve connection pooling",
            "author": {"name": "Tom Christie", "date": "2024-03-05T11:00:00Z"},
        },
    },
    {
        "sha": "fffbbbaaa000111222333444555666777888999a",
        "html_url": "https://github.com/encode/httpx/commit/fffbbb",
        "commit": {
            "message": "fix: handle timeout edge case",
            "author": {"name": "Tom Christie", "date": "2024-02-20T09:00:00Z"},
        },
    },
]

# ---------------------------------------------------------------------------
# PyPI fixture data
# ---------------------------------------------------------------------------

_PYPI_PKG_JSON = {
    "info": {
        "name": "requests",
        "version": "2.32.0",
        "summary": "Python HTTP for Humans.",
        "author": "Kenneth Reitz",
        "license": "Apache 2.0",
        "home_page": "https://requests.readthedocs.io",
        "requires_python": ">=3.8",
        "keywords": "http requests web",
        "package_url": "https://pypi.org/project/requests/",
        "requires_dist": [
            "certifi>=2017.4.17",
            "charset-normalizer<4,>=2",
            "idna<4,>=2.5",
            "urllib3<3,>=1.21.1",
        ],
    },
    "releases": {
        "2.32.0": [
            {"upload_time": "2024-05-01T12:00:00", "filename": "requests-2.32.0-py3-none-any.whl"}
        ],
        "2.31.0": [
            {"upload_time": "2023-05-22T10:00:00", "filename": "requests-2.31.0-py3-none-any.whl"}
        ],
        "2.30.0": [
            {"upload_time": "2023-05-03T08:00:00", "filename": "requests-2.30.0-py3-none-any.whl"}
        ],
    },
}

# ---------------------------------------------------------------------------
# npm fixture data
# ---------------------------------------------------------------------------

_NPM_SEARCH_JSON = {
    "objects": [
        {
            "package": {
                "name": "axios",
                "version": "1.7.2",
                "description": "Promise based HTTP client for the browser and node.js",
                "keywords": ["xhr", "http", "ajax"],
                "date": "2024-06-10T12:00:00Z",
                "author": {"name": "Matt Zabriskie"},
                "publisher": {"username": "jasonsaayman"},
            }
        }
    ],
    "total": 1,
}

_NPM_PACKUMENT_JSON = {
    "name": "axios",
    "description": "Promise based HTTP client for the browser and node.js",
    "keywords": ["xhr", "http", "ajax"],
    "dist-tags": {"latest": "1.7.2"},
    "versions": {
        "1.7.2": {
            "name": "axios",
            "version": "1.7.2",
            "description": "Promise based HTTP client for the browser and node.js",
            "license": "MIT",
            "homepage": "https://axios-http.com/",
            "repository": {"url": "git+https://github.com/axios/axios.git"},
            "dependencies": {
                "follow-redirects": "^1.15.6",
                "form-data": "^4.0.0",
            },
            "peerDependencies": {},
        },
        "1.6.0": {
            "name": "axios",
            "version": "1.6.0",
            "description": "Promise based HTTP client",
            "license": "MIT",
            "dependencies": {"follow-redirects": "^1.15.0"},
        },
    },
    "time": {
        "modified": "2024-06-10T12:00:00Z",
        "1.7.2": "2024-06-10T12:00:00Z",
        "1.6.0": "2023-10-26T08:00:00Z",
    },
}

# ---------------------------------------------------------------------------
# crates.io fixture data
# ---------------------------------------------------------------------------

_CRATES_SEARCH_JSON = {
    "crates": [
        {
            "name": "tokio",
            "newest_version": "1.38.0",
            "description": "An event-driven, non-blocking I/O platform.",
            "downloads": 100000000,
            "recent_downloads": 5000000,
            "updated_at": "2024-06-15T10:00:00Z",
        }
    ],
    "meta": {"total": 1},
}

_CRATES_METADATA_JSON = {
    "crate": {
        "name": "tokio",
        "newest_version": "1.38.0",
        "description": "An event-driven, non-blocking I/O platform.",
        "downloads": 100000000,
        "repository": "https://github.com/tokio-rs/tokio",
        "homepage": "https://tokio.rs",
        "documentation": "https://docs.rs/tokio",
        "updated_at": "2024-06-15T10:00:00Z",
        "categories": [],
        "keywords": [],
    },
    "versions": [],
}

_CRATES_VERSIONS_JSON = {
    "versions": [
        {
            "num": "1.38.0",
            "created_at": "2024-06-15T10:00:00Z",
            "downloads": 5000000,
            "yanked": False,
            "license": "MIT",
        },
        {
            "num": "1.37.0",
            "created_at": "2024-01-10T09:00:00Z",
            "downloads": 4000000,
            "yanked": False,
            "license": "MIT",
        },
    ]
}

_CRATES_DEPS_JSON = {
    "dependencies": [
        {
            "crate_id": "mio",
            "req": "^0.8.1",
            "kind": "normal",
            "optional": False,
        },
        {
            "crate_id": "pin-project-lite",
            "req": "^0.2.0",
            "kind": "normal",
            "optional": False,
        },
    ]
}

_CRATES_REVDEPS_JSON = {
    "dependencies": [
        {
            "crate_id": "tokio",
            "version_id": 42,
            "req": "^1.0",
            "kind": "normal",
        }
    ],
    "versions": [
        {
            "id": 42,
            "num": "0.1.5",
        }
    ],
}

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mocked_http():
    with respx.mock(assert_all_called=False) as m:
        yield m


# ===========================================================================
# GitHub adapter tests
# ===========================================================================


def test_gh_search_returns_documents(mocked_http):
    mocked_http.get("https://api.github.com/search/repositories").respond(200, json=_GH_SEARCH_JSON)
    docs = search_repos("python http client")
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)


def test_gh_search_extracts_full_name(mocked_http):
    mocked_http.get("https://api.github.com/search/repositories").respond(200, json=_GH_SEARCH_JSON)
    docs = search_repos("python http client")
    assert docs[0].metadata["full_name"] == "encode/httpx"
    assert docs[0].id == "github:repo:encode/httpx"


def test_gh_search_extracts_stars(mocked_http):
    mocked_http.get("https://api.github.com/search/repositories").respond(200, json=_GH_SEARCH_JSON)
    docs = search_repos("python http client")
    assert docs[0].metadata["stars"] == 14000
    assert docs[1].metadata["stars"] == 52000


def test_gh_search_extracts_language_and_license(mocked_http):
    mocked_http.get("https://api.github.com/search/repositories").respond(200, json=_GH_SEARCH_JSON)
    docs = search_repos("python http client")
    assert docs[0].metadata["language"] == "Python"
    assert docs[0].metadata["license"] == "BSD-3-Clause"


def test_gh_search_extracts_topics(mocked_http):
    mocked_http.get("https://api.github.com/search/repositories").respond(200, json=_GH_SEARCH_JSON)
    docs = search_repos("python http")
    assert "async" in docs[0].metadata["topics"]


def test_gh_search_extracts_description_in_text(mocked_http):
    mocked_http.get("https://api.github.com/search/repositories").respond(200, json=_GH_SEARCH_JSON)
    docs = search_repos("http")
    assert "next-generation" in docs[0].text


def test_gh_search_metadata_grade_and_source(mocked_http):
    mocked_http.get("https://api.github.com/search/repositories").respond(200, json=_GH_SEARCH_JSON)
    doc = search_repos("http")[0]
    assert doc.metadata["source"] == "github"
    assert doc.metadata["grade"] == "A"
    assert doc.metadata["type"] == "repo"


def test_gh_search_respects_max_results(mocked_http):
    route = mocked_http.get("https://api.github.com/search/repositories").respond(
        200, json=_GH_SEARCH_JSON
    )
    search_repos("http", max_results=3)
    assert route.calls.last.request.url.params["per_page"] == "3"


def test_gh_search_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.github.com/search/repositories").respond(403)
    with pytest.raises(httpx.HTTPStatusError):
        search_repos("http")


def test_gh_search_uses_injected_client(mocked_http):
    mocked_http.get("https://api.github.com/search/repositories").respond(200, json=_GH_SEARCH_JSON)
    with httpx.Client() as client:
        docs = search_repos("http", client=client)
        assert len(docs) == 2
        assert not client.is_closed


def test_gh_fetch_readme_returns_document(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/readme").respond(
        200, json=_GH_README_JSON
    )
    docs = fetch_readme("encode", "httpx")
    assert len(docs) == 1
    assert "httpx" in docs[0].text
    assert docs[0].metadata["full_name"] == "encode/httpx"
    assert docs[0].metadata["type"] == "readme"


def test_gh_fetch_readme_returns_empty_on_404(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/readme").respond(404)
    docs = fetch_readme("encode", "httpx")
    assert docs == []


def test_gh_fetch_readme_raises_on_non_404(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/readme").respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        fetch_readme("encode", "httpx")


def test_gh_list_releases_returns_documents(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/releases").respond(
        200, json=_GH_RELEASES_JSON
    )
    docs = list_releases("encode", "httpx")
    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)


def test_gh_list_releases_extracts_tag_and_published_at(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/releases").respond(
        200, json=_GH_RELEASES_JSON
    )
    docs = list_releases("encode", "httpx")
    assert docs[0].metadata["tag_name"] == "0.27.0"
    assert docs[0].metadata["published_at"] == "2024-04-01T12:00:00Z"
    assert docs[0].metadata["prerelease"] is False


def test_gh_list_releases_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/releases").respond(404)
    with pytest.raises(httpx.HTTPStatusError):
        list_releases("encode", "httpx")


def test_gh_list_recent_issues_returns_documents(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/issues").respond(
        200, json=_GH_ISSUES_JSON
    )
    docs = list_recent_issues("encode", "httpx")
    # Should only return the issue, not the PR
    assert len(docs) == 1
    assert docs[0].metadata["type"] == "issue"
    assert docs[0].metadata["number"] == 2001


def test_gh_list_recent_issues_excludes_prs(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/issues").respond(
        200, json=_GH_ISSUES_JSON
    )
    docs = list_recent_issues("encode", "httpx")
    ids = [d.id for d in docs]
    assert "github:issue:encode/httpx:2002" not in ids


def test_gh_list_recent_issues_extracts_labels(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/issues").respond(
        200, json=_GH_ISSUES_JSON
    )
    docs = list_recent_issues("encode", "httpx")
    assert "bug" in docs[0].metadata["labels"]


def test_gh_list_recent_issues_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/issues").respond(403)
    with pytest.raises(httpx.HTTPStatusError):
        list_recent_issues("encode", "httpx")


def test_gh_get_dependency_graph_returns_documents(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/dependency-graph/sbom").respond(
        200, json=_GH_SBOM_JSON
    )
    docs = get_dependency_graph("encode", "httpx")
    assert len(docs) == 2
    assert docs[0].metadata["type"] == "dependency"
    assert docs[0].metadata["package_name"] == "pip:httpcore"
    assert docs[0].metadata["version"] == "1.0.5"


def test_gh_get_dependency_graph_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/dependency-graph/sbom").respond(403)
    with pytest.raises(httpx.HTTPStatusError):
        get_dependency_graph("encode", "httpx")


def test_gh_get_license_returns_document(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/license").respond(
        200, json=_GH_LICENSE_JSON
    )
    docs = get_license("encode", "httpx")
    assert len(docs) == 1
    assert docs[0].metadata["spdx_id"] == "MIT"
    assert docs[0].metadata["type"] == "license"
    assert "MIT License" in docs[0].text


def test_gh_get_license_returns_empty_on_404(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/license").respond(404)
    docs = get_license("encode", "httpx")
    assert docs == []


def test_gh_get_security_advisories_returns_documents(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/security-advisories").respond(
        200, json=_GH_ADVISORIES_JSON
    )
    docs = get_security_advisories("encode", "httpx")
    assert len(docs) == 1
    assert docs[0].metadata["ghsa_id"] == "GHSA-xxxx-yyyy-zzzz"
    assert docs[0].metadata["cve_id"] == "CVE-2024-12345"
    assert docs[0].metadata["severity"] == "high"
    assert docs[0].metadata["cvss_score"] == 8.1


def test_gh_get_security_advisories_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/security-advisories").respond(403)
    with pytest.raises(httpx.HTTPStatusError):
        get_security_advisories("encode", "httpx")


def test_gh_get_commit_history_returns_documents(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/commits").respond(
        200, json=_GH_COMMITS_JSON
    )
    docs = get_commit_history("encode", "httpx")
    assert len(docs) == 2
    assert docs[0].metadata["type"] == "commit"
    assert "refactor" in docs[0].metadata["message"]
    assert docs[0].metadata["author"] == "Tom Christie"
    assert docs[0].metadata["committed_at"] == "2024-03-05T11:00:00Z"


def test_gh_get_commit_history_passes_since_param(mocked_http):
    route = mocked_http.get("https://api.github.com/repos/encode/httpx/commits").respond(
        200, json=_GH_COMMITS_JSON
    )
    get_commit_history("encode", "httpx", since="2024-01-01T00:00:00Z")
    assert route.calls.last.request.url.params["since"] == "2024-01-01T00:00:00Z"


def test_gh_get_commit_history_raises_on_http_error(mocked_http):
    mocked_http.get("https://api.github.com/repos/encode/httpx/commits").respond(404)
    with pytest.raises(httpx.HTTPStatusError):
        get_commit_history("encode", "httpx")


# ===========================================================================
# packages adapter — PyPI
# ===========================================================================


def test_pypi_search_returns_document(mocked_http):
    mocked_http.get("https://pypi.org/pypi/requests/json").respond(200, json=_PYPI_PKG_JSON)
    docs = pypi_search_package("requests")
    assert len(docs) == 1
    assert isinstance(docs[0], Document)
    assert docs[0].metadata["name"] == "requests"
    assert docs[0].metadata["version"] == "2.32.0"
    assert docs[0].id == "pypi:requests"


def test_pypi_search_returns_empty_on_404(mocked_http):
    mocked_http.get("https://pypi.org/pypi/nonexistent/json").respond(404)
    docs = pypi_search_package("nonexistent")
    assert docs == []


def test_pypi_search_raises_on_non_404_error(mocked_http):
    mocked_http.get("https://pypi.org/pypi/requests/json").respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        pypi_search_package("requests")


def test_pypi_search_extracts_license_and_author(mocked_http):
    mocked_http.get("https://pypi.org/pypi/requests/json").respond(200, json=_PYPI_PKG_JSON)
    doc = pypi_search_package("requests")[0]
    assert doc.metadata["license"] == "Apache 2.0"
    assert doc.metadata["author"] == "Kenneth Reitz"
    assert doc.metadata["requires_python"] == ">=3.8"


def test_pypi_search_includes_summary_in_text(mocked_http):
    mocked_http.get("https://pypi.org/pypi/requests/json").respond(200, json=_PYPI_PKG_JSON)
    doc = pypi_search_package("requests")[0]
    assert "Humans" in doc.text


def test_pypi_search_metadata_source(mocked_http):
    mocked_http.get("https://pypi.org/pypi/requests/json").respond(200, json=_PYPI_PKG_JSON)
    doc = pypi_search_package("requests")[0]
    assert doc.metadata["source"] == "pypi"
    assert doc.metadata["registry"] == "pypi"
    assert doc.metadata["grade"] == "A"


def test_pypi_search_uses_injected_client(mocked_http):
    mocked_http.get("https://pypi.org/pypi/requests/json").respond(200, json=_PYPI_PKG_JSON)
    with httpx.Client() as client:
        docs = pypi_search_package("requests", client=client)
        assert len(docs) == 1
        assert not client.is_closed


def test_pypi_fetch_metadata_delegates_to_search(mocked_http):
    mocked_http.get("https://pypi.org/pypi/requests/json").respond(200, json=_PYPI_PKG_JSON)
    docs = pypi_fetch_package_metadata("requests")
    assert len(docs) == 1
    assert docs[0].metadata["name"] == "requests"


def test_pypi_get_versions_returns_version_documents(mocked_http):
    mocked_http.get("https://pypi.org/pypi/requests/json").respond(200, json=_PYPI_PKG_JSON)
    docs = pypi_get_versions("requests")
    assert len(docs) >= 2
    assert all(d.metadata["type"] == "version" for d in docs)
    assert all(d.metadata["source"] == "pypi" for d in docs)


def test_pypi_get_versions_extracts_upload_time(mocked_http):
    mocked_http.get("https://pypi.org/pypi/requests/json").respond(200, json=_PYPI_PKG_JSON)
    docs = pypi_get_versions("requests")
    upload_times = [d.metadata["upload_time"] for d in docs]
    # At least one version should have an upload_time
    assert any(t for t in upload_times)


def test_pypi_get_versions_returns_empty_on_404(mocked_http):
    mocked_http.get("https://pypi.org/pypi/nonexistent/json").respond(404)
    docs = pypi_get_versions("nonexistent")
    assert docs == []


def test_pypi_get_dependencies_returns_dep_documents(mocked_http):
    mocked_http.get("https://pypi.org/pypi/requests/json").respond(200, json=_PYPI_PKG_JSON)
    docs = pypi_get_dependencies("requests")
    assert len(docs) == 4
    assert all(d.metadata["type"] == "dependency" for d in docs)
    dep_specs = [d.metadata["dependency_spec"] for d in docs]
    assert any("certifi" in s for s in dep_specs)


def test_pypi_get_dependents_returns_limitation_note(mocked_http):
    mocked_http.get("https://pypi.org/pypi/requests/json").respond(200, json=_PYPI_PKG_JSON)
    docs = pypi_get_dependents("requests")
    assert len(docs) == 1
    assert docs[0].metadata["type"] == "dependents_note"
    assert "no_public_dependents_api" in docs[0].metadata["limitation"]


def test_pypi_get_dependents_returns_empty_on_404(mocked_http):
    mocked_http.get("https://pypi.org/pypi/nonexistent/json").respond(404)
    docs = pypi_get_dependents("nonexistent")
    assert docs == []


def test_pypi_list_recent_releases_delegates_to_get_versions(mocked_http):
    mocked_http.get("https://pypi.org/pypi/requests/json").respond(200, json=_PYPI_PKG_JSON)
    docs = pypi_list_recent_releases_for_package("requests")
    assert all(d.metadata["type"] == "version" for d in docs)


# ===========================================================================
# packages adapter — npm
# ===========================================================================


def test_npm_search_returns_documents(mocked_http):
    mocked_http.get("https://registry.npmjs.org/-/v1/search").respond(200, json=_NPM_SEARCH_JSON)
    docs = npm_search_package("axios")
    assert len(docs) == 1
    assert isinstance(docs[0], Document)
    assert docs[0].metadata["name"] == "axios"
    assert docs[0].metadata["version"] == "1.7.2"
    assert docs[0].id == "npm:axios"


def test_npm_search_extracts_description(mocked_http):
    mocked_http.get("https://registry.npmjs.org/-/v1/search").respond(200, json=_NPM_SEARCH_JSON)
    doc = npm_search_package("axios")[0]
    assert "HTTP client" in doc.text
    assert doc.metadata["description"] == "Promise based HTTP client for the browser and node.js"


def test_npm_search_extracts_keywords(mocked_http):
    mocked_http.get("https://registry.npmjs.org/-/v1/search").respond(200, json=_NPM_SEARCH_JSON)
    doc = npm_search_package("axios")[0]
    assert "http" in doc.metadata["keywords"]


def test_npm_search_metadata_source(mocked_http):
    mocked_http.get("https://registry.npmjs.org/-/v1/search").respond(200, json=_NPM_SEARCH_JSON)
    doc = npm_search_package("axios")[0]
    assert doc.metadata["source"] == "npm"
    assert doc.metadata["registry"] == "npm"
    assert doc.metadata["grade"] == "A"


def test_npm_search_respects_max_results(mocked_http):
    route = mocked_http.get("https://registry.npmjs.org/-/v1/search").respond(
        200, json=_NPM_SEARCH_JSON
    )
    npm_search_package("axios", max_results=7)
    assert route.calls.last.request.url.params["size"] == "7"


def test_npm_search_raises_on_http_error(mocked_http):
    mocked_http.get("https://registry.npmjs.org/-/v1/search").respond(503)
    with pytest.raises(httpx.HTTPStatusError):
        npm_search_package("axios")


def test_npm_search_uses_injected_client(mocked_http):
    mocked_http.get("https://registry.npmjs.org/-/v1/search").respond(200, json=_NPM_SEARCH_JSON)
    with httpx.Client() as client:
        docs = npm_search_package("axios", client=client)
        assert len(docs) == 1
        assert not client.is_closed


def test_npm_fetch_metadata_returns_document(mocked_http):
    mocked_http.get("https://registry.npmjs.org/axios").respond(200, json=_NPM_PACKUMENT_JSON)
    docs = npm_fetch_package_metadata("axios")
    assert len(docs) == 1
    assert docs[0].metadata["name"] == "axios"
    assert docs[0].metadata["version"] == "1.7.2"
    assert docs[0].metadata["license"] == "MIT"


def test_npm_fetch_metadata_returns_empty_on_404(mocked_http):
    mocked_http.get("https://registry.npmjs.org/nonexistent").respond(404)
    docs = npm_fetch_package_metadata("nonexistent")
    assert docs == []


def test_npm_get_versions_returns_version_documents(mocked_http):
    mocked_http.get("https://registry.npmjs.org/axios").respond(200, json=_NPM_PACKUMENT_JSON)
    docs = npm_get_versions("axios")
    assert len(docs) == 2
    assert all(d.metadata["type"] == "version" for d in docs)
    # Should be sorted newest first
    assert docs[0].metadata["version"] == "1.7.2"
    assert docs[0].metadata["published_at"] == "2024-06-10T12:00:00Z"


def test_npm_get_versions_returns_empty_on_404(mocked_http):
    mocked_http.get("https://registry.npmjs.org/nonexistent").respond(404)
    docs = npm_get_versions("nonexistent")
    assert docs == []


def test_npm_get_versions_uses_injected_client(mocked_http):
    mocked_http.get("https://registry.npmjs.org/axios").respond(200, json=_NPM_PACKUMENT_JSON)
    with httpx.Client() as client:
        docs = npm_get_versions("axios", client=client)
        assert len(docs) == 2
        assert not client.is_closed


def test_npm_get_dependencies_returns_dep_documents(mocked_http):
    mocked_http.get("https://registry.npmjs.org/axios").respond(200, json=_NPM_PACKUMENT_JSON)
    docs = npm_get_dependencies("axios")
    assert len(docs) == 2
    assert all(d.metadata["type"] == "dependency" for d in docs)
    dep_names = [d.metadata["dep_name"] for d in docs]
    assert "follow-redirects" in dep_names


def test_npm_get_dependents_returns_limitation_note(mocked_http):
    mocked_http.get("https://registry.npmjs.org/axios").respond(200, json=_NPM_PACKUMENT_JSON)
    docs = npm_get_dependents("axios")
    assert len(docs) == 1
    assert docs[0].metadata["type"] == "dependents_note"
    assert docs[0].metadata["limitation"] == "no_public_dependents_api"


def test_npm_list_recent_releases_delegates_to_get_versions(mocked_http):
    mocked_http.get("https://registry.npmjs.org/axios").respond(200, json=_NPM_PACKUMENT_JSON)
    docs = npm_list_recent_releases_for_package("axios")
    assert all(d.metadata["type"] == "version" for d in docs)


# ===========================================================================
# packages adapter — crates.io
# ===========================================================================


def test_crates_search_returns_documents(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates").respond(200, json=_CRATES_SEARCH_JSON)
    docs = crates_search_package("tokio")
    assert len(docs) == 1
    assert isinstance(docs[0], Document)
    assert docs[0].metadata["name"] == "tokio"
    assert docs[0].metadata["version"] == "1.38.0"
    assert docs[0].id == "crates:tokio"


def test_crates_search_extracts_downloads(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates").respond(200, json=_CRATES_SEARCH_JSON)
    doc = crates_search_package("tokio")[0]
    assert doc.metadata["downloads"] == 100000000
    assert doc.metadata["recent_downloads"] == 5000000


def test_crates_search_metadata_source(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates").respond(200, json=_CRATES_SEARCH_JSON)
    doc = crates_search_package("tokio")[0]
    assert doc.metadata["source"] == "crates"
    assert doc.metadata["registry"] == "crates"
    assert doc.metadata["grade"] == "A"


def test_crates_search_respects_max_results(mocked_http):
    route = mocked_http.get("https://crates.io/api/v1/crates").respond(
        200, json=_CRATES_SEARCH_JSON
    )
    crates_search_package("tokio", max_results=8)
    assert route.calls.last.request.url.params["per_page"] == "8"


def test_crates_search_raises_on_http_error(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates").respond(503)
    with pytest.raises(httpx.HTTPStatusError):
        crates_search_package("tokio")


def test_crates_search_uses_injected_client(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates").respond(200, json=_CRATES_SEARCH_JSON)
    with httpx.Client() as client:
        docs = crates_search_package("tokio", client=client)
        assert len(docs) == 1
        assert not client.is_closed


def test_crates_fetch_metadata_returns_document(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates/tokio").respond(
        200, json=_CRATES_METADATA_JSON
    )
    docs = crates_fetch_package_metadata("tokio")
    assert len(docs) == 1
    assert docs[0].metadata["name"] == "tokio"
    assert docs[0].metadata["version"] == "1.38.0"
    assert docs[0].metadata["repository"] == "https://github.com/tokio-rs/tokio"


def test_crates_fetch_metadata_returns_empty_on_404(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates/nonexistent").respond(404)
    docs = crates_fetch_package_metadata("nonexistent")
    assert docs == []


def test_crates_get_versions_returns_version_documents(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates/tokio/versions").respond(
        200, json=_CRATES_VERSIONS_JSON
    )
    docs = crates_get_versions("tokio")
    assert len(docs) == 2
    assert all(d.metadata["type"] == "version" for d in docs)
    assert docs[0].metadata["version"] == "1.38.0"
    assert docs[0].metadata["created_at"] == "2024-06-15T10:00:00Z"
    assert docs[0].metadata["yanked"] is False
    assert docs[0].metadata["license"] == "MIT"


def test_crates_get_versions_returns_empty_on_404(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates/nonexistent/versions").respond(404)
    docs = crates_get_versions("nonexistent")
    assert docs == []


def test_crates_get_versions_uses_injected_client(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates/tokio/versions").respond(
        200, json=_CRATES_VERSIONS_JSON
    )
    with httpx.Client() as client:
        docs = crates_get_versions("tokio", client=client)
        assert len(docs) == 2
        assert not client.is_closed


def test_crates_get_dependencies_returns_dep_documents(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates/tokio/1.38.0/dependencies").respond(
        200, json=_CRATES_DEPS_JSON
    )
    docs = crates_get_dependencies("tokio", "1.38.0")
    assert len(docs) == 2
    assert all(d.metadata["type"] == "dependency" for d in docs)
    dep_names = [d.metadata["dep_name"] for d in docs]
    assert "mio" in dep_names
    assert docs[0].metadata["dep_req"] == "^0.8.1"
    assert docs[0].metadata["dep_kind"] == "normal"


def test_crates_get_dependencies_returns_empty_on_404(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates/nonexistent/1.0.0/dependencies").respond(404)
    docs = crates_get_dependencies("nonexistent", "1.0.0")
    assert docs == []


def test_crates_get_dependents_returns_reverse_dep_documents(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates/tokio/reverse_dependencies").respond(
        200, json=_CRATES_REVDEPS_JSON
    )
    docs = crates_get_dependents("tokio")
    assert len(docs) == 1
    assert docs[0].metadata["type"] == "reverse_dependency"
    assert docs[0].metadata["package"] == "tokio"
    assert docs[0].metadata["req"] == "^1.0"


def test_crates_get_dependents_returns_empty_on_404(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates/nonexistent/reverse_dependencies").respond(404)
    docs = crates_get_dependents("nonexistent")
    assert docs == []


def test_crates_get_dependents_tolerates_version_without_id(mocked_http):
    """A versions entry missing the 'id' key must not raise KeyError."""
    payload = {
        "dependencies": [{"crate_id": "foo", "version_id": 99, "req": "^1.0", "kind": "normal"}],
        # Malformed: this version object has no "id" key.
        "versions": [{"num": "1.2.3"}],
    }
    mocked_http.get("https://crates.io/api/v1/crates/tokio/reverse_dependencies").respond(
        200, json=payload
    )
    docs = crates_get_dependents("tokio")
    assert len(docs) == 1
    assert docs[0].metadata["dependent_crate"] == "foo"
    # version_id 99 has no matching versions entry → blank dependent_version.
    assert docs[0].metadata["dependent_version"] == ""


def test_crates_list_recent_releases_delegates_to_get_versions(mocked_http):
    mocked_http.get("https://crates.io/api/v1/crates/tokio/versions").respond(
        200, json=_CRATES_VERSIONS_JSON
    )
    docs = crates_list_recent_releases_for_package("tokio")
    assert all(d.metadata["type"] == "version" for d in docs)
