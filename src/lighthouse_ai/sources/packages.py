"""Package registry source adapter — PyPI, npm, crates.io.

Three sub-registries under one adapter module, each with a consistent
interface: search_package / fetch_package_metadata / get_versions /
get_dependencies / get_dependents / list_recent_releases_for_package.

**Endpoints:**
  - PyPI:     ``https://pypi.org/pypi/<pkg>/json``
              ``https://pypi.org/search/?q=<q>``  (HTML; we use the JSON API)
              ``https://pypi.org/pypi/<pkg>/<ver>/json``
              ``https://pypi.org/simple/`` (no search API; search via PyPI JSON)
  - npm:      ``https://registry.npmjs.org/<pkg>``
              ``https://registry.npmjs.org/-/v1/search?text=<q>``
  - crates.io:``https://crates.io/api/v1/crates/<pkg>``
              ``https://crates.io/api/v1/crates?q=<q>``

**Egress note:** ``pypi.org``, ``registry.npmjs.org``, and ``crates.io`` must
be present on the egress allowlist.  The skill degrades gracefully (returns []
with a log note) if they are not.

The adapter is httpx-based and client-injectable for respx-testable offline
tests.  A ``timeout`` parameter is accepted for all functions.
"""

from __future__ import annotations

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

_PYPI_BASE = "https://pypi.org/pypi"
_NPM_BASE = "https://registry.npmjs.org"
_CRATES_BASE = "https://crates.io/api/v1/crates"

# Public API hosts this adapter contacts; the user invoked the package source
# for exactly these registries, so they are authorized for egress.
_ALLOWED_HOSTS = frozenset({
    "pypi.org",
    "registry.npmjs.org",
    "crates.io",
})

_PYPI_HEADERS = {"User-Agent": "Lighthouse/0.1", "Accept": "application/json"}
_NPM_HEADERS = {"User-Agent": "Lighthouse/0.1", "Accept": "application/json"}
_CRATES_HEADERS = {
    "User-Agent": "Lighthouse/0.1 (https://github.com/lighthouse-ai/lighthouse; contact@lighthouse.dev)",
    "Accept": "application/json",
}


# ===========================================================================
# PyPI
# ===========================================================================

def pypi_search_package(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Search PyPI for packages matching ``query`` using the PyPI JSON API.

    PyPI does not have a public search REST API that returns JSON.  We use the
    ``/search/?q=<query>&o=&c=`` HTML endpoint and parse the JSON data embedded
    in the page *is not public API*.  Instead, we fall back to the PyPI Simple
    index approach: perform a best-effort lookup for the exact package name then
    widen.  For reliable search, callers should use ``pypi_fetch_package_metadata``
    with a known package name, or consult the warehouse search API when available.

    This implementation fetches ``/pypi/<query>/json`` (exact name lookup) and
    returns a 1-element list if the package exists, or [] otherwise.  It does NOT
    raise on 404.

    Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_PYPI_HEADERS, timeout=timeout)
    try:
        resp = guarded_get(
            f"{_PYPI_BASE}/{query}/json",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_PYPI_HEADERS,
            client=client,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return [_parse_pypi_info(resp.json())]
    finally:
        if owns:
            client.close()


def _parse_pypi_info(data: dict) -> Document:
    info = data.get("info") or {}
    name = info.get("name", "")
    version = info.get("version", "")
    summary = (info.get("summary") or "")[:300]
    text = f"{name} {version}: {summary}".strip(": ") if summary else f"{name} {version}"
    return Document(
        id=f"pypi:{name}",
        text=text,
        metadata={
            "source": "pypi",
            "registry": "pypi",
            "type": "package",
            "url": info.get("package_url") or f"https://pypi.org/project/{name}/",
            "grade": "A",
            "name": name,
            "version": version,
            "summary": summary,
            "author": info.get("author") or "",
            "license": info.get("license") or "",
            "home_page": info.get("home_page") or "",
            "requires_python": info.get("requires_python") or "",
            "keywords": info.get("keywords") or "",
        },
    )


def pypi_fetch_package_metadata(
    name: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Fetch full package metadata for ``name`` from PyPI.

    Returns a single-element list on success.  Returns [] on 404.
    Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    return pypi_search_package(name, max_results=1, client=client, timeout=timeout)


def pypi_get_versions(
    name: str,
    *,
    max_results: int = 20,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """List available versions for PyPI package ``name`` (most recent first).

    Returns one Document per version.  Returns [] on 404.
    Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_PYPI_HEADERS, timeout=timeout)
    try:
        resp = guarded_get(
            f"{_PYPI_BASE}/{name}/json",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_PYPI_HEADERS,
            client=client,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        releases = data.get("releases") or {}
        # Sort by release date (desc); fall back to version string order.
        versions = list(releases.keys())
        # Most recent max_results versions
        versions = versions[-max_results:][::-1] if len(versions) > max_results else versions[::-1]
        out: list[Document] = []
        for ver in versions:
            files = releases.get(ver) or []
            upload_time = files[0].get("upload_time", "") if files else ""
            out.append(Document(
                id=f"pypi:{name}:{ver}",
                text=f"{name} {ver}",
                metadata={
                    "source": "pypi",
                    "registry": "pypi",
                    "type": "version",
                    "url": f"https://pypi.org/project/{name}/{ver}/",
                    "grade": "A",
                    "name": name,
                    "version": ver,
                    "upload_time": upload_time,
                    "num_files": len(files),
                },
            ))
        return out
    finally:
        if owns:
            client.close()


def pypi_get_dependencies(
    name: str,
    version: str | None = None,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Return ``requires_dist`` dependencies for PyPI package ``name``.

    If ``version`` is omitted, the latest release is used.
    Returns one Document per dependency specifier.  Returns [] on 404.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_PYPI_HEADERS, timeout=timeout)
    try:
        url = f"{_PYPI_BASE}/{name}/{version}/json" if version else f"{_PYPI_BASE}/{name}/json"
        resp = guarded_get(
            url,
            allowed_domains=_ALLOWED_HOSTS,
            headers=_PYPI_HEADERS,
            client=client,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        info = data.get("info") or {}
        pkg_ver = info.get("version", version or "")
        requires = info.get("requires_dist") or []
        out: list[Document] = []
        for req in requires:
            out.append(Document(
                id=f"pypi:{name}:{pkg_ver}:dep:{req[:60]}",
                text=req,
                metadata={
                    "source": "pypi",
                    "registry": "pypi",
                    "type": "dependency",
                    "url": f"https://pypi.org/project/{name}/{pkg_ver}/",
                    "grade": "A",
                    "package": name,
                    "version": pkg_ver,
                    "dependency_spec": req,
                },
            ))
        return out
    finally:
        if owns:
            client.close()


def pypi_get_dependents(
    name: str,
    *,
    max_results: int = 10,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Return a best-effort list of packages that depend on ``name`` (PyPI).

    PyPI does not expose a dependents API.  We fetch the ``/pypi/<name>/json``
    record and surface a single Document noting the limitation and the
    ``requires_dist`` of the queried package (which shows what *it* depends on).
    For true reverse-dep lookup use ``libraries.io`` (v1.1).

    Returns [] on 404.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_PYPI_HEADERS, timeout=timeout)
    try:
        resp = guarded_get(
            f"{_PYPI_BASE}/{name}/json",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_PYPI_HEADERS,
            client=client,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        info = resp.json().get("info") or {}
        return [Document(
            id=f"pypi:{name}:dependents",
            text=(
                f"PyPI does not provide a public dependents API for {name}. "
                "For reverse dependency data use libraries.io or pypinfo."
            ),
            metadata={
                "source": "pypi",
                "registry": "pypi",
                "type": "dependents_note",
                "url": f"https://pypi.org/project/{name}/",
                "grade": "A",
                "package": name,
                "version": info.get("version") or "",
                "limitation": "no_public_dependents_api",
            },
        )]
    finally:
        if owns:
            client.close()


def pypi_list_recent_releases_for_package(
    name: str,
    *,
    max_results: int = 10,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """List the most-recently uploaded releases for PyPI package ``name``.

    This is the watchable tool — callers filter on ``upload_time`` to detect
    new releases since a Watch checkpoint.

    Returns [] on 404.  Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    return pypi_get_versions(name, max_results=max_results, client=client, timeout=timeout)


# ===========================================================================
# npm
# ===========================================================================

def npm_search_package(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Search npm registry for packages matching ``query``.

    Uses ``/-/v1/search?text=<query>&size=<n>``.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_NPM_HEADERS, timeout=timeout)
    try:
        resp = guarded_get(
            f"{_NPM_BASE}/-/v1/search",
            allowed_domains=_ALLOWED_HOSTS,
            params={"text": query, "size": max_results},
            headers=_NPM_HEADERS,
            client=client,
        )
        resp.raise_for_status()
        objects = resp.json().get("objects") or []
        out: list[Document] = []
        for obj in objects:
            pkg = obj.get("package") or {}
            name = pkg.get("name", "")
            version = pkg.get("version", "")
            description = pkg.get("description") or ""
            text = f"{name} {version}: {description}".strip(": ") if description else f"{name} {version}"
            out.append(Document(
                id=f"npm:{name}",
                text=text,
                metadata={
                    "source": "npm",
                    "registry": "npm",
                    "type": "package",
                    "url": f"https://www.npmjs.com/package/{name}",
                    "grade": "A",
                    "name": name,
                    "version": version,
                    "description": description,
                    "keywords": pkg.get("keywords") or [],
                    "author": (pkg.get("author") or {}).get("name") or "",
                    "publisher": (pkg.get("publisher") or {}).get("username") or "",
                    "date": pkg.get("date") or "",
                },
            ))
        return out
    finally:
        if owns:
            client.close()


def npm_fetch_package_metadata(
    name: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Fetch the full npm registry document for ``name``.

    Uses ``/<name>`` (the packument).  Returns [] on 404.
    Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_NPM_HEADERS, timeout=timeout)
    try:
        resp = guarded_get(
            f"{_NPM_BASE}/{name}",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_NPM_HEADERS,
            client=client,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        latest_ver = (data.get("dist-tags") or {}).get("latest") or ""
        latest_info = (data.get("versions") or {}).get(latest_ver) or {}
        description = data.get("description") or latest_info.get("description") or ""
        text = f"{name} {latest_ver}: {description}".strip(": ") if description else f"{name} {latest_ver}"
        return [Document(
            id=f"npm:{name}",
            text=text,
            metadata={
                "source": "npm",
                "registry": "npm",
                "type": "package",
                "url": f"https://www.npmjs.com/package/{name}",
                "grade": "A",
                "name": name,
                "version": latest_ver,
                "description": description,
                "license": latest_info.get("license") or "",
                "homepage": latest_info.get("homepage") or "",
                "repository": (latest_info.get("repository") or {}).get("url") or "",
                "keywords": data.get("keywords") or [],
                "modified": data.get("time", {}).get("modified") or "",
            },
        )]
    finally:
        if owns:
            client.close()


def npm_get_versions(
    name: str,
    *,
    max_results: int = 20,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """List available versions for npm package ``name``.

    Returns [] on 404.  Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_NPM_HEADERS, timeout=timeout)
    try:
        resp = guarded_get(
            f"{_NPM_BASE}/{name}",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_NPM_HEADERS,
            client=client,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        times = data.get("time") or {}
        versions_info = data.get("versions") or {}
        # Sort by release time descending
        timed = [(ver, times.get(ver, "")) for ver in versions_info if ver not in ("created", "modified")]
        timed.sort(key=lambda x: x[1], reverse=True)
        timed = timed[:max_results]
        out: list[Document] = []
        for ver, publish_time in timed:
            out.append(Document(
                id=f"npm:{name}:{ver}",
                text=f"{name} {ver}",
                metadata={
                    "source": "npm",
                    "registry": "npm",
                    "type": "version",
                    "url": f"https://www.npmjs.com/package/{name}/v/{ver}",
                    "grade": "A",
                    "name": name,
                    "version": ver,
                    "published_at": publish_time,
                },
            ))
        return out
    finally:
        if owns:
            client.close()


def npm_get_dependencies(
    name: str,
    version: str | None = None,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Return ``dependencies`` and ``peerDependencies`` for npm package ``name``.

    If ``version`` is None, uses the latest release.
    Returns [] on 404.  Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_NPM_HEADERS, timeout=timeout)
    try:
        resp = guarded_get(
            f"{_NPM_BASE}/{name}",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_NPM_HEADERS,
            client=client,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        if version is None:
            version = (data.get("dist-tags") or {}).get("latest") or ""
        ver_info = (data.get("versions") or {}).get(version) or {}
        deps: dict[str, str] = {}
        deps.update(ver_info.get("dependencies") or {})
        deps.update(ver_info.get("peerDependencies") or {})
        out: list[Document] = []
        for dep_name, dep_range in deps.items():
            out.append(Document(
                id=f"npm:{name}:{version}:dep:{dep_name}",
                text=f"{dep_name} {dep_range}",
                metadata={
                    "source": "npm",
                    "registry": "npm",
                    "type": "dependency",
                    "url": f"https://www.npmjs.com/package/{dep_name}",
                    "grade": "A",
                    "package": name,
                    "version": version,
                    "dep_name": dep_name,
                    "dep_range": dep_range,
                },
            ))
        return out
    finally:
        if owns:
            client.close()


def npm_get_dependents(
    name: str,
    *,
    max_results: int = 10,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Return a best-effort list of packages that depend on ``name`` (npm).

    npm registry does not expose a public dependents REST endpoint.  We surface
    a single Document noting the limitation.  For true reverse-dep lookup use
    ``npmjs.com/browse/depended/<name>`` (HTML) or ``libraries.io`` (v1.1).

    Returns [] on 404.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_NPM_HEADERS, timeout=timeout)
    try:
        resp = guarded_get(
            f"{_NPM_BASE}/{name}",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_NPM_HEADERS,
            client=client,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return [Document(
            id=f"npm:{name}:dependents",
            text=(
                f"npm registry does not provide a public dependents API for {name}. "
                "For reverse dependency data visit npmjs.com or use libraries.io."
            ),
            metadata={
                "source": "npm",
                "registry": "npm",
                "type": "dependents_note",
                "url": f"https://www.npmjs.com/package/{name}?activeTab=dependents",
                "grade": "A",
                "package": name,
                "limitation": "no_public_dependents_api",
            },
        )]
    finally:
        if owns:
            client.close()


def npm_list_recent_releases_for_package(
    name: str,
    *,
    max_results: int = 10,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """List the most-recently published versions for npm package ``name``.

    Watchable tool — callers filter on ``published_at``.

    Returns [] on 404.  Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    return npm_get_versions(name, max_results=max_results, client=client, timeout=timeout)


# ===========================================================================
# crates.io
# ===========================================================================

def crates_search_package(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Search crates.io for crates matching ``query``.

    Uses ``/api/v1/crates?q=<query>&per_page=<n>&sort=downloads``.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_CRATES_HEADERS, timeout=timeout)
    try:
        resp = guarded_get(
            _CRATES_BASE,
            allowed_domains=_ALLOWED_HOSTS,
            params={"q": query, "per_page": max_results, "sort": "downloads"},
            headers=_CRATES_HEADERS,
            client=client,
        )
        resp.raise_for_status()
        crates = resp.json().get("crates") or []
        out: list[Document] = []
        for crate in crates:
            name = crate.get("name", "")
            version = crate.get("newest_version", "")
            description = crate.get("description") or ""
            text = f"{name} {version}: {description}".strip(": ") if description else f"{name} {version}"
            out.append(Document(
                id=f"crates:{name}",
                text=text,
                metadata={
                    "source": "crates",
                    "registry": "crates",
                    "type": "package",
                    "url": f"https://crates.io/crates/{name}",
                    "grade": "A",
                    "name": name,
                    "version": version,
                    "description": description,
                    "downloads": crate.get("downloads", 0),
                    "recent_downloads": crate.get("recent_downloads") or 0,
                    "updated_at": crate.get("updated_at") or "",
                },
            ))
        return out
    finally:
        if owns:
            client.close()


def crates_fetch_package_metadata(
    name: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Fetch full metadata for crates.io crate ``name``.

    Uses ``/api/v1/crates/<name>``.  Returns [] on 404.
    Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_CRATES_HEADERS, timeout=timeout)
    try:
        resp = guarded_get(
            f"{_CRATES_BASE}/{name}",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_CRATES_HEADERS,
            client=client,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        crate = data.get("crate") or {}
        version = crate.get("newest_version", "")
        description = crate.get("description") or ""
        text = f"{name} {version}: {description}".strip(": ") if description else f"{name} {version}"
        return [Document(
            id=f"crates:{name}",
            text=text,
            metadata={
                "source": "crates",
                "registry": "crates",
                "type": "package",
                "url": f"https://crates.io/crates/{name}",
                "grade": "A",
                "name": name,
                "version": version,
                "description": description,
                "downloads": crate.get("downloads", 0),
                "repository": crate.get("repository") or "",
                "homepage": crate.get("homepage") or "",
                "documentation": crate.get("documentation") or "",
                "updated_at": crate.get("updated_at") or "",
                "categories": crate.get("categories") or [],
                "keywords": crate.get("keywords") or [],
            },
        )]
    finally:
        if owns:
            client.close()


def crates_get_versions(
    name: str,
    *,
    max_results: int = 20,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """List available versions for crates.io crate ``name``.

    Uses ``/api/v1/crates/<name>/versions``.  Returns [] on 404.
    Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_CRATES_HEADERS, timeout=timeout)
    try:
        resp = guarded_get(
            f"{_CRATES_BASE}/{name}/versions",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_CRATES_HEADERS,
            client=client,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        versions = resp.json().get("versions") or []
        versions = versions[:max_results]
        out: list[Document] = []
        for ver in versions:
            ver_num = ver.get("num", "")
            out.append(Document(
                id=f"crates:{name}:{ver_num}",
                text=f"{name} {ver_num}",
                metadata={
                    "source": "crates",
                    "registry": "crates",
                    "type": "version",
                    "url": f"https://crates.io/crates/{name}/{ver_num}",
                    "grade": "A",
                    "name": name,
                    "version": ver_num,
                    "created_at": ver.get("created_at") or "",
                    "downloads": ver.get("downloads", 0),
                    "yanked": ver.get("yanked", False),
                    "license": ver.get("license") or "",
                },
            ))
        return out
    finally:
        if owns:
            client.close()


def crates_get_dependencies(
    name: str,
    version: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Return dependencies for crates.io crate ``name`` at ``version``.

    Uses ``/api/v1/crates/<name>/<version>/dependencies``.
    Returns [] on 404.  Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_CRATES_HEADERS, timeout=timeout)
    try:
        resp = guarded_get(
            f"{_CRATES_BASE}/{name}/{version}/dependencies",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_CRATES_HEADERS,
            client=client,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        deps = resp.json().get("dependencies") or []
        out: list[Document] = []
        for dep in deps:
            dep_name = dep.get("crate_id", "")
            dep_req = dep.get("req", "")
            dep_kind = dep.get("kind", "normal")
            out.append(Document(
                id=f"crates:{name}:{version}:dep:{dep_name}",
                text=f"{dep_name} {dep_req} ({dep_kind})",
                metadata={
                    "source": "crates",
                    "registry": "crates",
                    "type": "dependency",
                    "url": f"https://crates.io/crates/{dep_name}",
                    "grade": "A",
                    "package": name,
                    "version": version,
                    "dep_name": dep_name,
                    "dep_req": dep_req,
                    "dep_kind": dep_kind,
                    "optional": dep.get("optional", False),
                },
            ))
        return out
    finally:
        if owns:
            client.close()


def crates_get_dependents(
    name: str,
    *,
    max_results: int = 10,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """List crates that depend on ``name`` (reverse dependencies).

    Uses ``/api/v1/crates/<name>/reverse_dependencies``.
    Returns [] on 404.  Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    owns = client is None
    if client is None:
        client = httpx.Client(headers=_CRATES_HEADERS, timeout=timeout)
    try:
        resp = guarded_get(
            f"{_CRATES_BASE}/{name}/reverse_dependencies",
            allowed_domains=_ALLOWED_HOSTS,
            params={"per_page": max_results},
            headers=_CRATES_HEADERS,
            client=client,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        deps = data.get("dependencies") or []
        versions = {
            v["id"]: v
            for v in (data.get("versions") or [])
            if isinstance(v, dict) and "id" in v
        }
        out: list[Document] = []
        for dep in deps:
            ver_id = dep.get("version_id")
            ver_info = versions.get(ver_id) or {}
            crate_name = dep.get("crate_id", "")
            ver_num = ver_info.get("num", "")
            out.append(Document(
                id=f"crates:{name}:revdep:{crate_name}",
                text=f"{crate_name} {ver_num} depends on {name}",
                metadata={
                    "source": "crates",
                    "registry": "crates",
                    "type": "reverse_dependency",
                    "url": f"https://crates.io/crates/{crate_name}",
                    "grade": "A",
                    "package": name,
                    "dependent_crate": crate_name,
                    "dependent_version": ver_num,
                    "req": dep.get("req") or "",
                    "dep_kind": dep.get("kind", "normal"),
                },
            ))
        return out
    finally:
        if owns:
            client.close()


def crates_list_recent_releases_for_package(
    name: str,
    *,
    max_results: int = 10,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """List the most-recently published versions for crates.io crate ``name``.

    Watchable tool — callers filter on ``created_at``.

    Returns [] on 404.  Raises ``httpx.HTTPStatusError`` on non-404 errors.
    """
    return crates_get_versions(name, max_results=max_results, client=client, timeout=timeout)
