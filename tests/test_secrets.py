"""Tests for the keychain + TOML fallback secret store."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from lighthouse_ai.secrets import (
    AUDIT_CHAIN_KEY,
    SERVICE,
    SecretStore,
)


class _FakeKeyring:
    """Minimal keyring API surface: get/set/delete by (service, key)."""

    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}
        self.set_calls = 0
        self.get_calls = 0
        self.delete_calls = 0

    def get_password(self, service, key):
        self.get_calls += 1
        return self._store.get((service, key))

    def set_password(self, service, key, value):
        self.set_calls += 1
        self._store[(service, key)] = value

    def delete_password(self, service, key):
        self.delete_calls += 1
        del self._store[(service, key)]


@pytest.fixture
def store_kr(tmp_path: Path) -> tuple[SecretStore, _FakeKeyring]:
    kr = _FakeKeyring()
    return SecretStore(tmp_path, keyring_module=kr), kr


@pytest.fixture
def store_file(tmp_path: Path) -> SecretStore:
    """Store with prefer_keyring=False — always uses file."""
    return SecretStore(tmp_path, prefer_keyring=False)


# --- keyring-primary path ---


def test_put_and_get_via_keyring(store_kr):
    s, kr = store_kr
    backend = s.put("k1", "v1")
    assert backend == "keyring"
    assert s.get("k1") == "v1"
    assert kr.set_calls == 1


def test_delete_removes_from_keyring(store_kr):
    s, kr = store_kr
    s.put("k", "v")
    assert s.delete("k") is True
    assert s.get("k") is None


def test_delete_missing_returns_false(store_kr):
    s, _ = store_kr
    assert s.delete("nope") is False


def test_get_or_create_returns_existing(store_kr):
    s, _ = store_kr
    s.put("k", "existing")
    assert s.get_or_create("k") == "existing"


def test_get_or_create_generates_when_missing(store_kr):
    s, kr = store_kr
    v = s.get_or_create("k", nbytes=16)
    assert len(v) == 32  # token_hex returns 2x nbytes
    assert kr._store[(SERVICE, "k")] == v


# --- file fallback path ---


def test_put_uses_file_when_keyring_disabled(store_file, tmp_path):
    store_file.put("k1", "v1")
    p = tmp_path / "secrets.toml"
    assert p.exists()
    text = p.read_text()
    assert "k1" in text and "v1" in text


def test_file_fallback_is_mode_0600(store_file, tmp_path):
    store_file.put("k", "v")
    p = tmp_path / "secrets.toml"
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode & stat.S_IRUSR  # readable by owner
    assert not (mode & stat.S_IRGRP)  # not group
    assert not (mode & stat.S_IROTH)  # not other


def test_get_falls_back_to_file_when_keyring_misses(store_kr, tmp_path):
    """Pre-existing TOML row is visible even if keyring has no entry."""
    s, kr = store_kr
    # Write directly via a file-only store to seed the file.
    file_only = SecretStore(tmp_path, prefer_keyring=False)
    file_only.put("legacy", "from-file")
    # keyring-primary store also sees the file fallback.
    assert s.get("legacy") == "from-file"


def test_delete_removes_from_file_fallback(store_file):
    store_file.put("k", "v")
    assert store_file.delete("k") is True
    assert store_file.get("k") is None


def test_list_returns_file_keys(store_file):
    store_file.put("a", "1")
    store_file.put("b", "2")
    assert store_file.list() == ["a", "b"]


# --- error-tolerance ---


class _BrokenKeyring:
    def get_password(self, *args, **kw):
        raise RuntimeError("locked")

    def set_password(self, *args, **kw):
        raise RuntimeError("locked")

    def delete_password(self, *args, **kw):
        raise RuntimeError("locked")


def test_put_falls_back_to_file_when_keyring_raises(tmp_path):
    s = SecretStore(tmp_path, keyring_module=_BrokenKeyring())
    backend = s.put("k", "v")
    assert backend == "file"
    assert s.get("k") == "v"


def test_audit_chain_canonical_key_constant():
    # Sanity: the well-known constants are stable identifiers other modules
    # import — changing them is a breaking change.
    assert AUDIT_CHAIN_KEY == "audit.chain"


# --- audit chain integration --------------------------------------------


def test_audit_append_with_explicit_secret_unchanged(migrated_paths):
    """Pre-Sprint-21 callers still work."""
    from lighthouse_ai.verification.audit_chain import append_event, verify_audit_chain

    secret = b"x" * 32
    seq = append_event(
        migrated_paths.audit_db, actor="t", event_type="e", payload={"v": 1}, secret=secret
    )
    assert seq >= 1
    assert verify_audit_chain(migrated_paths.audit_db, secret=secret) == []


def test_audit_append_pulls_from_secret_store_when_secret_none(migrated_paths):
    """secret=None + data_dir → SecretStore mints/loads the chain key."""
    from lighthouse_ai.verification.audit_chain import (
        append_event,
        resolve_secret,
        verify_audit_chain,
    )

    append_event(
        migrated_paths.audit_db,
        actor="t",
        event_type="e",
        payload={"v": 1},
        data_dir=migrated_paths.data_dir,
    )
    # The minted secret is the one verify_audit_chain expects.
    resolved = resolve_secret(None, data_dir=migrated_paths.data_dir)
    assert verify_audit_chain(migrated_paths.audit_db, secret=resolved) == []


def test_audit_append_consistent_secret_across_calls(migrated_paths):
    """Multiple append_event(secret=None) calls share the same minted key."""
    from lighthouse_ai.verification.audit_chain import (
        append_event,
        resolve_secret,
        verify_audit_chain,
    )

    for i in range(3):
        append_event(
            migrated_paths.audit_db,
            actor="t",
            event_type="e",
            payload={"i": i},
            data_dir=migrated_paths.data_dir,
        )
    secret = resolve_secret(None, data_dir=migrated_paths.data_dir)
    assert verify_audit_chain(migrated_paths.audit_db, secret=secret) == []


def test_resolve_secret_requires_data_dir_when_no_explicit():
    from lighthouse_ai.verification.audit_chain import resolve_secret

    with pytest.raises(ValueError):
        resolve_secret(None)
