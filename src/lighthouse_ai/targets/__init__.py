"""Built-in effector target adapters.

Each target module exposes an ``applier(intent) -> None`` and registers
itself when imported via :func:`register_default_targets`. Real sprints add
Qdrant, Logseq, Zotero, filesystem, audit. Sprint 2 ships ``test_target``
and ``audit`` — the only two we need to validate the framework.
"""

from __future__ import annotations

from . import audit as _audit
from . import test_target as _test_target


def register_default_targets(*, audit_db_path=None) -> None:
    """Register the built-in target appliers + compensators."""
    _test_target.install()
    if audit_db_path is not None:
        _audit.install(audit_db_path)
