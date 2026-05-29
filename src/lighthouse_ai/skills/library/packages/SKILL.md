# PyPI / npm / crates.io — Planner Guide

## When to use this skill

The `packages` skill is the right source when the research question concerns
**published software packages**: what versions exist, what a package's
dependencies are, whether a package is actively maintained, what its license
is, or whether a supply-chain vulnerability affects a specific version.

This one skill covers three registries under a unified interface:

| Registry | Language ecosystem | Auth needed |
|---|---|---|
| **PyPI** | Python | None (public API) |
| **npm** | JavaScript / Node.js / TypeScript | None (public API) |
| **crates.io** | Rust | None (public API) |

### packages vs GitHub

| Unit of research | Right skill | Why |
|---|---|---|
| Published package metadata, versions, deps | **packages** | Registry is authoritative for install-time facts |
| Source code, issues, releases (GitHub-hosted) | **github** | Canonical repo, not registry |
| Supply-chain vuln (GHSA) | **github** | GitHub Security Advisories live there |
| Supply-chain vuln (CVE + dependency version) | **both** | packages for which version; github for GHSA context |

---

## Egress requirements

These registries are NOT on the default Lighthouse egress allowlist.  Unlock
each one you need:

```
lighthouse trust add pypi.org
lighthouse trust add registry.npmjs.org
lighthouse trust add crates.io
```

The skill degrades gracefully (returns [] with a logged note) for any locked
registry.

---

## Query format

Pass a plain package name, or prefix with the registry name:

| Query | What happens |
|---|---|
| `"requests"` | Searches PyPI + npm + crates for "requests" |
| `"pypi:requests"` | Searches only PyPI |
| `"npm:react"` | Searches only npm |
| `"crates:tokio"` | Searches only crates.io |

---

## Tool playbook

### PyPI tools

| Task | Tool | Notes |
|---|---|---|
| Find a Python package | `pypi_search_package(query)` | Exact name lookup (PyPI has no search REST API) |
| Full metadata | `pypi_fetch_package_metadata(name)` | Version, author, license, requires_python |
| List all versions | `pypi_get_versions(name)` | Most recent 20 by default |
| List deps | `pypi_get_dependencies(name, version=None)` | `requires_dist` specifiers |
| Note on reverse deps | `pypi_get_dependents(name)` | PyPI has no public dependents API |
| Watch new releases | `pypi_list_recent_releases_for_package(name)` | Use `upload_time` for since-filter |

### npm tools

| Task | Tool | Notes |
|---|---|---|
| Search packages | `npm_search_package(query)` | Uses `/-/v1/search` |
| Full metadata | `npm_fetch_package_metadata(name)` | Latest version, license, repo, keywords |
| List all versions | `npm_get_versions(name)` | Sorted by publish time |
| List deps | `npm_get_dependencies(name, version=None)` | `dependencies` + `peerDependencies` |
| Note on reverse deps | `npm_get_dependents(name)` | npm has no public dependents API |
| Watch new releases | `npm_list_recent_releases_for_package(name)` | Use `published_at` for since-filter |

### crates.io tools

| Task | Tool | Notes |
|---|---|---|
| Search crates | `crates_search_package(query)` | Sorted by downloads |
| Full metadata | `crates_fetch_package_metadata(name)` | Downloads, repo, docs, categories |
| List all versions | `crates_get_versions(name)` | Includes `yanked` flag |
| List deps | `crates_get_dependencies(name, version)` | Requires explicit version |
| Reverse deps | `crates_get_dependents(name)` | crates.io exposes `reverse_dependencies` |
| Watch new releases | `crates_list_recent_releases_for_package(name)` | Use `created_at` for since-filter |

---

## Build-vs-buy / library evaluation workflow

For Decide-mode "should we use library X":

1. `run(ctx, "pypi:X")` — get latest version, license, requires_python.
2. `pypi_get_versions("X")` — check release cadence (time between versions).
3. `pypi_get_dependencies("X")` — audit dependency surface area.
4. Cross-reference with `github` skill: `search_repos("X")` → get stars, open
   issues, security advisories.
5. For Rust: `crates_get_dependents("X")` gives real reverse-dep data.

---

## Supply-chain vulnerability tracking workflow

For a dependency audit:

1. `pypi_get_dependencies("my_package")` — get full dep list.
2. For each dep: `pypi_get_versions(dep)` — check if the installed version is
   the latest (outdated = potential known-vuln exposure).
3. For each dep: use `github` skill `get_security_advisories(owner, repo)` for
   GHSA lookup.
4. Watch: `run_watchable(ctx, "pypi:requests", since=checkpoint)` triggers
   when a new version is published.

---

## Known biases and limitations

1. **PyPI has no public search REST API.** `pypi_search_package` does an exact
   name lookup.  For fuzzy / keyword package discovery use `npm_search_package`
   or `crates_search_package` (those have search endpoints) and then verify on
   PyPI.

2. **npm and PyPI have no public dependents API.** `get_dependents` for these
   registries returns a Document explaining the limitation.  Use
   `crates_get_dependents` for Rust reverse-dep data (crates.io has this).

3. **Yanked crates.** `crates_get_versions` includes yanked versions with
   `yanked: true`.  Yanked versions should not be treated as stable releases.

4. **Version ordering.** PyPI `get_versions` uses the release dict key order
   (upload order), not strict semantic version ordering.  The most-recently
   uploaded version is shown first, which is usually but not always the
   "latest" in semver terms.

5. **npm packument size.** Full npm packument responses for large packages
   (e.g. `lodash`, `typescript`) can be very large.  The adapter reads only
   version metadata, not the full file manifests, but the response can still
   exceed 1 MB.

---

## Watch mode notes

`run_watchable` watches for **new releases** of a named package.  Filter on:
- PyPI: `metadata["upload_time"]` (e.g. `"2024-03-15T10:00:00"`)
- npm: `metadata["published_at"]` (ISO 8601)
- crates.io: `metadata["created_at"]` (ISO 8601 with Z suffix)

Store the latest timestamp as the Watch checkpoint.  Typical cadences:
- Weekly for stable, slowly-updated packages.
- Daily for fast-moving packages or security-sensitive dependencies.
