"""Tests for GET /api/sources/health.

Verifies shape invariants and the status logic (ready / needs_key /
needs_trust) without asserting on specific skill IDs — the real library
contents may change and tests must stay green across additions.

All tests are offline-deterministic: no LLM, no network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lighthouse_ai.controlplane import create_app
from lighthouse_ai.governor.egress_proxy import DEFAULT_ALLOWED_DOMAINS
from lighthouse_ai.skills.registry import all_skills


@pytest.fixture
def client(migrated_paths):
    return TestClient(create_app(migrated_paths))


# ──────────────────────────── shape invariants ───────────────────────────────

def test_sources_health_returns_200(client):
    r = client.get("/api/sources/health")
    assert r.status_code == 200


def test_sources_health_top_level_shape(client):
    body = client.get("/api/sources/health").json()
    assert "sources" in body, "response must have 'sources' key"
    assert "summary" in body, "response must have 'summary' key"
    assert isinstance(body["sources"], list)
    assert isinstance(body["summary"], dict)


def test_sources_health_summary_keys(client):
    summary = client.get("/api/sources/health").json()["summary"]
    for key in ("ready", "needs_key", "needs_trust", "total"):
        assert key in summary, f"summary missing '{key}'"
    assert isinstance(summary["total"], int)
    assert isinstance(summary["ready"], int)
    assert isinstance(summary["needs_key"], int)
    assert isinstance(summary["needs_trust"], int)


def test_sources_health_counts_sum_to_total(client):
    """ready + needs_key + needs_trust must equal total."""
    body = client.get("/api/sources/health").json()
    s = body["summary"]
    assert s["ready"] + s["needs_key"] + s["needs_trust"] == s["total"]


def test_sources_health_source_row_shape(client):
    """Every source row must carry the required fields."""
    sources = client.get("/api/sources/health").json()["sources"]
    required = {"id", "name", "category", "tier", "status", "reason"}
    valid_statuses = {"ready", "needs_key", "needs_trust"}
    for src in sources:
        for key in required:
            assert key in src, f"source row missing '{key}': {src}"
        assert src["status"] in valid_statuses, (
            f"unexpected status {src['status']!r} in {src}"
        )


def test_sources_health_total_matches_all_skills(client):
    """The total count must equal the number of skills all_skills() returns."""
    total = client.get("/api/sources/health").json()["summary"]["total"]
    try:
        expected = len(all_skills())
    except Exception:
        expected = 0
    assert total == expected


# ─────────────────────── status-logic assertions ─────────────────────────────

def test_ready_sources_have_trusted_domains(client):
    """Every 'ready' source's declared domains are on the platform allowlist."""
    def _trusted(domain: str) -> bool:
        d = domain.lower().rstrip(".")
        if d in DEFAULT_ALLOWED_DOMAINS:
            return True
        return any(d.endswith("." + a) for a in DEFAULT_ALLOWED_DOMAINS)

    sources = client.get("/api/sources/health").json()["sources"]
    try:
        manifests = {m.id: m for m in all_skills()}
    except Exception:
        manifests = {}

    for src in sources:
        if src["status"] != "ready":
            continue
        m = manifests.get(src["id"])
        if m is None:
            continue
        for domain in m.allowed_domains:
            assert _trusted(domain), (
                f"skill {src['id']!r} marked ready but domain {domain!r} "
                "is not trusted"
            )


def test_needs_trust_has_untrusted_domain(client):
    """Any 'needs_trust' source has at least one domain not on the allowlist."""
    def _trusted(domain: str) -> bool:
        d = domain.lower().rstrip(".")
        if d in DEFAULT_ALLOWED_DOMAINS:
            return True
        return any(d.endswith("." + a) for a in DEFAULT_ALLOWED_DOMAINS)

    sources = client.get("/api/sources/health").json()["sources"]
    try:
        manifests = {m.id: m for m in all_skills()}
    except Exception:
        manifests = {}

    for src in sources:
        if src["status"] != "needs_trust":
            continue
        m = manifests.get(src["id"])
        if m is None:
            continue
        untrusted = [d for d in m.allowed_domains if not _trusted(d)]
        assert untrusted, (
            f"skill {src['id']!r} marked needs_trust but all its domains "
            "are already trusted"
        )


def test_needs_key_source_has_no_secret_configured(client, migrated_paths):
    """A source whose key is absent from SecretStore shows needs_key (if applicable).

    The endpoint checks domain trust before key presence, so a key-requiring
    source whose domains are also untrusted shows as needs_trust, not needs_key.
    This test verifies the invariant: every needs_key source (a) has a key in
    the catalogue, (b) has no secret configured, and (c) has all its domains
    trusted (otherwise it would be needs_trust instead).
    """
    from lighthouse_ai.governor.egress_proxy import DEFAULT_ALLOWED_DOMAINS
    from lighthouse_ai.secrets import SecretStore
    from lighthouse_ai.skills.registry import all_skills as _all_skills

    store = SecretStore(migrated_paths.data_dir)
    assert store.list() == [], "test fixture should start with no secrets"

    sources = client.get("/api/sources/health").json()["sources"]

    # Build catalogued key names so we can check without importing _SOURCE_KEY_CATALOGUE.
    key_catalogue = {
        s["source_id"]: s["key_name"]
        for s in client.get("/api/sources/keys").json()["sources"]
    }

    def _trusted(domain: str) -> bool:
        d = domain.lower().rstrip(".")
        if d in DEFAULT_ALLOWED_DOMAINS:
            return True
        return any(d.endswith("." + a) for a in DEFAULT_ALLOWED_DOMAINS)

    try:
        manifests = {m.id: m for m in _all_skills()}
    except Exception:
        manifests = {}

    for src in sources:
        if src["status"] != "needs_key":
            continue
        sid = src["id"]
        # Must be in the key catalogue.
        assert sid in key_catalogue, (
            f"{sid!r} has status needs_key but is not in /api/sources/keys"
        )
        # All its domains must be trusted (else it would be needs_trust).
        m = manifests.get(sid)
        if m and m.allowed_domains:
            untrusted = [d for d in m.allowed_domains if not _trusted(d)]
            assert not untrusted, (
                f"{sid!r} has status needs_key but has untrusted domains {untrusted} "
                "(should be needs_trust)"
            )


def test_arxiv_is_ready(client):
    """arXiv has a trusted domain and no key requirement — it must be ready."""
    sources = client.get("/api/sources/health").json()["sources"]
    arxiv = next((s for s in sources if s["id"] == "arxiv"), None)
    if arxiv is None:
        pytest.skip("arxiv skill not present in this library")
    assert arxiv["status"] == "ready", (
        f"expected arxiv to be ready, got {arxiv['status']!r}: {arxiv['reason']}"
    )


def test_reason_is_plain_language(client):
    """Reason strings must not contain internal jargon like 'egress' or 'manifest'."""
    sources = client.get("/api/sources/health").json()["sources"]
    jargon = ("egress", "manifest", "allowlist", "DEFAULT_ALLOWED")
    for src in sources:
        reason = src.get("reason", "")
        for word in jargon:
            assert word.lower() not in reason.lower(), (
                f"jargon word {word!r} found in reason for {src['id']!r}: {reason!r}"
            )
