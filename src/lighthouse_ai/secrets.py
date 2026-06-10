"""OS keychain + TOML fallback for Lighthouse secrets.

Per design §30: secrets live in macOS Keychain / GNOME Keyring / KWallet /
Windows Credential Manager via the ``keyring`` package; an unencrypted
``~/.lighthouse/secrets.toml`` (mode 0600) is the fallback when no
keychain backend is available (rare on macOS/Linux but happens in CI).

Service name is fixed (``lighthouse``); the *account* is the key — the
audit chain secret, Langfuse API key, cloud LLM keys, etc.
"""

from __future__ import annotations

import os
import secrets as _stdlib_secrets
import stat
from pathlib import Path

try:
    import tomllib as _toml_read
except ImportError:  # pragma: no cover - py<3.11
    import tomli as _toml_read  # type: ignore[no-redef]

import tomli_w as _toml_write

SERVICE = "lighthouse"


# --- TOML fallback ------------------------------------------------------

def _fallback_path(data_dir: Path) -> Path:
    return data_dir / "secrets.toml"


def _read_fallback(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return _toml_read.load(fh).get("secrets", {})


def _write_fallback(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _toml_write.dumps({"secrets": data})
    # Write atomically + lock down perms to 0600.
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(body)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)


# --- public API ---------------------------------------------------------

class SecretStore:
    """Get/put/delete with keychain primary, TOML fallback."""

    def __init__(self, data_dir: Path, *, service: str = SERVICE,
                 keyring_module=None, prefer_keyring: bool = True):
        self.data_dir = data_dir
        self.service = service
        self._kr = keyring_module
        self._prefer = prefer_keyring

    def _keyring(self):
        if not self._prefer:
            return None
        if self._kr is None:
            try:
                import keyring as _kr
                self._kr = _kr
            except ImportError:
                return None
        return self._kr

    # --- core ops ---
    def get(self, key: str) -> str | None:
        kr = self._keyring()
        if kr is not None:
            try:
                value = kr.get_password(self.service, key)
                if value is not None:
                    return value
            except Exception:
                pass
        return _read_fallback(_fallback_path(self.data_dir)).get(key)

    def put(self, key: str, value: str) -> str:
        """Store ``value`` under ``key``. Returns the backend used: 'keyring' or 'file'."""
        kr = self._keyring()
        if kr is not None:
            try:
                kr.set_password(self.service, key, value)
                return "keyring"
            except Exception:
                pass
        path = _fallback_path(self.data_dir)
        existing = _read_fallback(path)
        existing[key] = value
        _write_fallback(path, existing)
        return "file"

    def delete(self, key: str) -> bool:
        """Remove ``key``. Returns True if it was present anywhere."""
        found = False
        kr = self._keyring()
        if kr is not None:
            try:
                if kr.get_password(self.service, key) is not None:
                    kr.delete_password(self.service, key)
                    found = True
            except Exception:
                pass
        path = _fallback_path(self.data_dir)
        existing = _read_fallback(path)
        if key in existing:
            del existing[key]
            _write_fallback(path, existing)
            found = True
        return found

    def list(self) -> list[str]:
        """List keys in the TOML fallback. Keyring backends don't reliably enumerate."""
        return sorted(_read_fallback(_fallback_path(self.data_dir)).keys())

    def backend_status(self) -> str:
        """Which backend a ``put`` would land in right now: 'keyring' or 'file'.

        Probes the keychain with a read-only ``get_password`` (never writes) so
        callers like ``lighthouse doctor`` can report the effective secret
        storage without mutating the user's keychain.
        """
        kr = self._keyring()
        if kr is not None:
            try:
                kr.get_password(self.service, "__lighthouse_doctor_probe__")
                return "keyring"
            except Exception:
                pass
        return "file"

    # --- convenience: random secret on first access ---
    def get_or_create(self, key: str, *, nbytes: int = 32) -> str:
        existing = self.get(key)
        if existing is not None:
            return existing
        fresh = _stdlib_secrets.token_hex(nbytes)
        self.put(key, fresh)
        return fresh


# Well-known keys (canonical names; document these in the README).
AUDIT_CHAIN_KEY = "audit.chain"
LANGFUSE_API_KEY = "langfuse.api_key"
