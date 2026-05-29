# GitHub — Planner Guide

## When to use this skill

GitHub is the right primary source when the research question concerns
**open-source software repositories**: discovering popular projects for a
language or domain, auditing library choices, tracking releases and changelogs,
investigating open issues, checking license compatibility, auditing security
advisories, or examining commit history.

### Engineering wedge: GitHub vs PyPI/npm/crates.io

| Unit of research | Right skill | Why |
|---|---|---|
| Repository discovery, README, issues, GHSA | **GitHub** | Source repo, primary metadata, security advisories |
| Package install-time metadata, version history, dependencies | **packages** | PyPI / npm / crates.io registry records |
| Supply-chain vuln tracking | **both** | GitHub for GHSA; packages for dependency graph |

**Use GitHub for:**
- Finding the **canonical repository** for a library or tool
  (`search_repos`, `fetch_readme`).
- Checking **release notes** and tracking new releases watchably
  (`list_releases`).
- Auditing **open issues** — especially security or breaking-change issues
  (`list_recent_issues`).
- Retrieving the **dependency graph** (SBOM) for a specific repo
  (`get_dependency_graph`).
- Checking the **license** of a repository (`get_license`).
- Fetching **GitHub Security Advisories (GHSA)** for a project
  (`get_security_advisories`).
- Tracing **commit history** — for Reconstruct mode or authorship/provenance
  questions (`get_commit_history`).

**Do NOT use GitHub for:**
- Package registry metadata (install counts, latest stable version, package
  descriptions in the registry sense) — use the `packages` skill.
- Authoritative vulnerability databases — GHSA is a good first pass; follow
  up with NVD/MITRE for CVE details (v1.1).
- Private repositories (no token with appropriate scope).

---

## Authentication

Set a GitHub Personal Access Token (PAT) to raise the rate limit from 60
req/hr (unauthenticated) to 5 000 req/hr (authenticated):

```
lighthouse config set github.token <your_PAT>
```

Classic PAT scopes needed: `public_repo` for public repos; `security_events`
for security advisories on private repos; `repo` for private repo access.
Fine-grained PATs: read-only `Contents` + `Issues` + `Security advisories`
covers all v1 tool use cases.

---

## Egress

`api.github.com` and `github.com` are on the **default** Lighthouse egress
allowlist.  No `lighthouse trust add` is required.

---

## Translating a question into a GitHub query

### search_repos
Pass keywords, language qualifiers, or GitHub search syntax:
- `"rust async runtime"` — keyword search
- `"language:python topic:machine-learning stars:>1000"` — GitHub search syntax
- `"org:pytorch"` — all repos in an organisation

### Specific repo tools
Most tools take `owner` + `repo` as separate parameters derived from the
`full_name` field (`owner/repo`).  Always extract these from a prior
`search_repos` result or user-supplied full name.

---

## Tool playbook

| Task | Tool | Notes |
|---|---|---|
| Discover repos by keyword | `search_repos` | Returns stars, language, license, topics |
| Read project documentation | `fetch_readme` | First 4 000 chars of README |
| Track new releases | `list_releases` + Watch | `published_at` for time filtering |
| Monitor open issues | `list_recent_issues` + Watch | Excludes PRs; filter by `created_at` |
| Audit dependencies (SBOM) | `get_dependency_graph` | Requires Dependency Graph enabled |
| Check license | `get_license` | Returns SPDX ID + full license text |
| Security advisories | `get_security_advisories` | GHSA; includes CVE ID + severity |
| Commit history / authorship | `get_commit_history` + Watch | Filter by `since=` ISO timestamp |

### Library evaluation workflow (Decide mode)

1. `search_repos("topic:<domain> language:<lang>", max_results=10)` — candidate list.
2. For each candidate: `get_license(owner, repo)` — license compatibility gate.
3. `list_releases(owner, repo, max_results=5)` — release cadence signal.
4. `list_recent_issues(owner, repo, state="open")` — maintenance health signal.
5. `get_security_advisories(owner, repo)` — security posture check.
6. Output: ranked comparison table with license / stars / release cadence / open issues.

### Vulnerability tracking workflow (Watch mode)

Set up `run_watchable("owner/repo", since=last_checkpoint)` to monitor new
GHSA advisories and new issues labelled `security`.  Each Watch tick returns
new releases and issues after the checkpoint.

---

## Known biases and limitations

1. **Stars are popularity, not quality.** High star count correlates with
   marketing and network effects, not code correctness. Always pair star count
   with release cadence and open-issue health.

2. **Rate limits without auth.** 60 req/hr unauthenticated hits fast with
   multi-step tool sequences. Recommend prompting the user for a PAT early.

3. **Dependency graph requires feature enabled.** Some repos or org policies
   disable the Dependency Graph; `get_dependency_graph` returns [] for those.

4. **Security advisories are self-reported.** GHSA entries are submitted by
   maintainers or the GitHub Security Team; they may lag NVD/MITRE CVE
   publication. For critical vulnerability research, cross-check NVD (v1.1).

5. **Fork farms.** `search_repos` sorts by stars but includes forks. Use
   `"fork:false"` in the query to exclude forked repos.

6. **GitHub Actions / CI data.** This skill does not include CI/CD status or
   workflow data — that would require separate API calls not covered in v1.

---

## Watch mode notes

`run_watchable` defaults to watching **releases** when given `owner/repo`
format, filtering on `published_at`.  For issue watching, callers should
call `list_recent_issues` directly with a `since`-based filter on `created_at`.

Typical Watch cadences:
- New releases: daily for fast-moving projects, weekly for stable ones.
- Security advisories: daily for security-critical dependencies.
- Commit history: hourly for CI-style monitoring (not recommended for most
  research use cases).
