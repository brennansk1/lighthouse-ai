"""GitHub source adapter — GitHub REST API v3.

Provides tools for researching repositories, releases, issues, security
advisories, dependency graphs, commit history, licenses, and README content
using the public GitHub REST API (api.github.com).

**Authentication:** Pass a Personal Access Token (PAT) via the ``token``
parameter or ``GITHUB_TOKEN`` env var.  Unauthenticated callers are limited
to 60 req/hr; authenticated callers get 5 000 req/hr.  The skill wrapping
this adapter documents the config key: ``lighthouse config set github.token
<PAT>`` and gracefully returns [] with a log note on EgressBlocked.

**Egress note:** ``api.github.com`` and ``github.com`` are on the DEFAULT
Lighthouse platform allowlist.  No trust-add is needed for live fetches.

The adapter is httpx-based and client-injectable for respx-testable offline
tests.  When ``client`` is omitted a short-lived ``httpx.Client`` is opened
and closed per call.
"""

from __future__ import annotations

import httpx

from ..rag.chunker import Document

_API_BASE = "https://api.github.com"
_HEADERS = {
    "User-Agent": "Lighthouse/0.1",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _auth_headers(token: str | None) -> dict[str, str]:
    h = dict(_HEADERS)
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _make_client(token: str | None, timeout: float) -> httpx.Client:
    return httpx.Client(headers=_auth_headers(token), timeout=timeout)


# ---------------------------------------------------------------------------
# search_repos
# ---------------------------------------------------------------------------

def search_repos(
    query: str,
    *,
    max_results: int = 5,
    token: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Search GitHub repositories and return up to ``max_results`` Documents.

    Uses ``/search/repositories``.  Returns Documents with ``full_name``,
    ``description``, ``url``, ``stars``, ``language``, ``license``,
    ``pushed_at``, ``topics``.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    owns = client is None
    if client is None:
        client = _make_client(token, timeout)
    try:
        resp = client.get(
            f"{_API_BASE}/search/repositories",
            params={"q": query, "per_page": max_results, "sort": "stars", "order": "desc"},
        )
        resp.raise_for_status()
        items = resp.json().get("items") or []
        out: list[Document] = []
        for item in items:
            full_name = item.get("full_name", "")
            title = full_name
            desc = item.get("description") or ""
            text = f"{title}: {desc}".strip(": ") if desc else title
            lic = (item.get("license") or {}).get("spdx_id") or ""
            out.append(Document(
                id=f"github:repo:{full_name}",
                text=text,
                metadata={
                    "source": "github",
                    "type": "repo",
                    "url": item.get("html_url", ""),
                    "grade": "A",
                    "full_name": full_name,
                    "description": desc,
                    "stars": item.get("stargazers_count", 0),
                    "language": item.get("language") or "",
                    "license": lic,
                    "pushed_at": item.get("pushed_at") or "",
                    "topics": item.get("topics") or [],
                },
            ))
        return out
    finally:
        if owns:
            client.close()


# ---------------------------------------------------------------------------
# fetch_readme
# ---------------------------------------------------------------------------

def fetch_readme(
    owner: str,
    repo: str,
    *,
    token: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Fetch the decoded README for ``owner/repo``.

    Uses ``/repos/{owner}/{repo}/readme``.  Returns a single-element list on
    success or ``[]`` when the repo has no README (404).

    Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    owns = client is None
    if client is None:
        client = _make_client(token, timeout)
    try:
        resp = client.get(f"{_API_BASE}/repos/{owner}/{repo}/readme")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        import base64  # stdlib — allowed in sources
        content_b64 = data.get("content", "")
        content = base64.b64decode(content_b64.replace("\n", "")).decode("utf-8", errors="replace")
        full_name = f"{owner}/{repo}"
        return [Document(
            id=f"github:readme:{full_name}",
            text=content[:4000],  # truncate for Document text field
            metadata={
                "source": "github",
                "type": "readme",
                "url": data.get("html_url", ""),
                "grade": "A",
                "full_name": full_name,
                "sha": data.get("sha", ""),
                "size": data.get("size", 0),
            },
        )]
    finally:
        if owns:
            client.close()


# ---------------------------------------------------------------------------
# list_releases  (watchable by published_at)
# ---------------------------------------------------------------------------

def list_releases(
    owner: str,
    repo: str,
    *,
    max_results: int = 10,
    token: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """List recent releases for ``owner/repo``.

    Uses ``/repos/{owner}/{repo}/releases``.  Each Document carries
    ``tag_name``, ``name``, ``published_at``, ``prerelease``, ``url``.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    owns = client is None
    if client is None:
        client = _make_client(token, timeout)
    try:
        resp = client.get(
            f"{_API_BASE}/repos/{owner}/{repo}/releases",
            params={"per_page": max_results},
        )
        resp.raise_for_status()
        out: list[Document] = []
        for rel in resp.json():
            tag = rel.get("tag_name", "")
            name = rel.get("name") or tag
            body = (rel.get("body") or "")[:500]
            text = f"{name}: {body}".strip(": ") if body else name
            out.append(Document(
                id=f"github:release:{owner}/{repo}:{tag}",
                text=text,
                metadata={
                    "source": "github",
                    "type": "release",
                    "url": rel.get("html_url", ""),
                    "grade": "A",
                    "full_name": f"{owner}/{repo}",
                    "tag_name": tag,
                    "name": name,
                    "published_at": rel.get("published_at") or "",
                    "prerelease": rel.get("prerelease", False),
                    "draft": rel.get("draft", False),
                },
            ))
        return out
    finally:
        if owns:
            client.close()


# ---------------------------------------------------------------------------
# list_recent_issues  (watchable by created_at)
# ---------------------------------------------------------------------------

def list_recent_issues(
    owner: str,
    repo: str,
    *,
    state: str = "open",
    max_results: int = 10,
    token: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """List recent issues for ``owner/repo``.

    Uses ``/repos/{owner}/{repo}/issues?state=open&sort=created&direction=desc``.
    Excludes pull-requests (GitHub's issues endpoint returns both; we filter by
    ``pull_request`` key absence).

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    owns = client is None
    if client is None:
        client = _make_client(token, timeout)
    try:
        resp = client.get(
            f"{_API_BASE}/repos/{owner}/{repo}/issues",
            params={
                "state": state,
                "sort": "created",
                "direction": "desc",
                "per_page": max_results,
            },
        )
        resp.raise_for_status()
        out: list[Document] = []
        for issue in resp.json():
            if "pull_request" in issue:
                continue  # skip PRs
            number = issue.get("number", 0)
            title = issue.get("title", "")
            body = (issue.get("body") or "")[:300]
            text = f"#{number} {title}: {body}".strip(": ") if body else f"#{number} {title}"
            labels = [lbl.get("name", "") for lbl in (issue.get("labels") or [])]
            out.append(Document(
                id=f"github:issue:{owner}/{repo}:{number}",
                text=text,
                metadata={
                    "source": "github",
                    "type": "issue",
                    "url": issue.get("html_url", ""),
                    "grade": "A",
                    "full_name": f"{owner}/{repo}",
                    "number": number,
                    "title": title,
                    "state": issue.get("state", ""),
                    "created_at": issue.get("created_at") or "",
                    "updated_at": issue.get("updated_at") or "",
                    "labels": labels,
                    "user": (issue.get("user") or {}).get("login", ""),
                },
            ))
        return out
    finally:
        if owns:
            client.close()


# ---------------------------------------------------------------------------
# get_dependency_graph
# ---------------------------------------------------------------------------

def get_dependency_graph(
    owner: str,
    repo: str,
    *,
    token: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Fetch the SBOM dependency list for ``owner/repo`` via the Dependency Graph API.

    Uses ``/repos/{owner}/{repo}/dependency-graph/sbom`` (requires GitHub
    Dependency Graph to be enabled on the repo).  Returns one Document per
    dependency package.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    owns = client is None
    if client is None:
        client = _make_client(token, timeout)
    try:
        resp = client.get(
            f"{_API_BASE}/repos/{owner}/{repo}/dependency-graph/sbom",
        )
        resp.raise_for_status()
        data = resp.json()
        sbom = data.get("sbom") or {}
        packages = sbom.get("packages") or []
        out: list[Document] = []
        for pkg in packages:
            name = pkg.get("name", "")
            version = pkg.get("versionInfo") or ""
            license_str = " ".join(pkg.get("licenseConcluded") or []) if isinstance(
                pkg.get("licenseConcluded"), list
            ) else (pkg.get("licenseConcluded") or "")
            text = f"{name} {version}".strip() if version else name
            out.append(Document(
                id=f"github:dep:{owner}/{repo}:{name}",
                text=text,
                metadata={
                    "source": "github",
                    "type": "dependency",
                    "url": f"https://github.com/{owner}/{repo}/network/dependencies",
                    "grade": "A",
                    "full_name": f"{owner}/{repo}",
                    "package_name": name,
                    "version": version,
                    "license": license_str,
                },
            ))
        return out
    finally:
        if owns:
            client.close()


# ---------------------------------------------------------------------------
# get_license
# ---------------------------------------------------------------------------

def get_license(
    owner: str,
    repo: str,
    *,
    token: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Fetch the license information for ``owner/repo``.

    Uses ``/repos/{owner}/{repo}/license``.  Returns a single-element list on
    success or ``[]`` when no license file is found (404).

    Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    owns = client is None
    if client is None:
        client = _make_client(token, timeout)
    try:
        resp = client.get(f"{_API_BASE}/repos/{owner}/{repo}/license")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        import base64
        lic = data.get("license") or {}
        content_b64 = data.get("content", "")
        content = base64.b64decode(content_b64.replace("\n", "")).decode("utf-8", errors="replace")
        spdx = lic.get("spdx_id") or ""
        full_name = f"{owner}/{repo}"
        return [Document(
            id=f"github:license:{full_name}",
            text=f"{spdx}\n{content[:2000]}".strip(),
            metadata={
                "source": "github",
                "type": "license",
                "url": data.get("html_url", ""),
                "grade": "A",
                "full_name": full_name,
                "spdx_id": spdx,
                "license_name": lic.get("name") or "",
                "sha": data.get("sha", ""),
            },
        )]
    finally:
        if owns:
            client.close()


# ---------------------------------------------------------------------------
# get_security_advisories  (GHSA)
# ---------------------------------------------------------------------------

def get_security_advisories(
    owner: str,
    repo: str,
    *,
    max_results: int = 10,
    token: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """List published security advisories (GHSA) for ``owner/repo``.

    Uses ``/repos/{owner}/{repo}/security-advisories``.  Returns Documents
    with ``ghsa_id``, ``cve_id``, ``severity``, ``published_at``,
    ``cvss_score``.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    owns = client is None
    if client is None:
        client = _make_client(token, timeout)
    try:
        resp = client.get(
            f"{_API_BASE}/repos/{owner}/{repo}/security-advisories",
            params={"per_page": max_results},
        )
        resp.raise_for_status()
        out: list[Document] = []
        for adv in resp.json():
            ghsa_id = adv.get("ghsa_id") or ""
            summary = adv.get("summary") or ""
            desc = (adv.get("description") or "")[:400]
            text = f"{ghsa_id}: {summary}: {desc}".strip(": ")
            cvss = (adv.get("cvss") or {})
            out.append(Document(
                id=f"github:advisory:{ghsa_id}" if ghsa_id else f"github:advisory:{owner}/{repo}",
                text=text,
                metadata={
                    "source": "github",
                    "type": "security_advisory",
                    "url": adv.get("html_url", ""),
                    "grade": "A",
                    "full_name": f"{owner}/{repo}",
                    "ghsa_id": ghsa_id,
                    "cve_id": adv.get("cve_id") or "",
                    "severity": adv.get("severity") or "",
                    "published_at": adv.get("published_at") or "",
                    "cvss_score": cvss.get("score"),
                    "cvss_vector": cvss.get("vector_string") or "",
                },
            ))
        return out
    finally:
        if owns:
            client.close()


# ---------------------------------------------------------------------------
# get_commit_history  (watchable by commit date)
# ---------------------------------------------------------------------------

def get_commit_history(
    owner: str,
    repo: str,
    *,
    max_results: int = 20,
    since: str | None = None,
    path: str | None = None,
    token: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Fetch recent commits for ``owner/repo``.

    Uses ``/repos/{owner}/{repo}/commits``.  Pass ``since`` as an ISO 8601
    timestamp to get only commits after that time (Watch pattern).

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    owns = client is None
    if client is None:
        client = _make_client(token, timeout)
    try:
        params: dict[str, str | int] = {"per_page": max_results}
        if since:
            params["since"] = since
        if path:
            params["path"] = path
        resp = client.get(
            f"{_API_BASE}/repos/{owner}/{repo}/commits",
            params=params,
        )
        resp.raise_for_status()
        out: list[Document] = []
        for commit in resp.json():
            sha = commit.get("sha", "")[:12]
            c = commit.get("commit") or {}
            message = (c.get("message") or "")[:300]
            author = (c.get("author") or {})
            author_name = author.get("name") or ""
            commit_date = author.get("date") or ""
            text = f"{sha}: {message}".strip(": ")
            out.append(Document(
                id=f"github:commit:{owner}/{repo}:{sha}",
                text=text,
                metadata={
                    "source": "github",
                    "type": "commit",
                    "url": (commit.get("html_url") or ""),
                    "grade": "A",
                    "full_name": f"{owner}/{repo}",
                    "sha": commit.get("sha", ""),
                    "message": message,
                    "author": author_name,
                    "committed_at": commit_date,
                },
            ))
        return out
    finally:
        if owns:
            client.close()
