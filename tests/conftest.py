"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from lighthouse_ai.paths import Paths, make_paths
from lighthouse_ai.schema import kinds_for, migrate_all


@pytest.fixture
def tmp_paths(tmp_path: Path) -> Paths:
    paths = make_paths(tmp_path / "data", tmp_path / "replicas")
    paths.ensure()
    return paths


@pytest.fixture
def migrated_paths(tmp_paths: Paths) -> Paths:
    migrate_all(kinds_for(tmp_paths))
    return tmp_paths


@pytest.fixture
def broker(tmp_path: Path):
    """Default sandbox broker on a temp dir — shared by the skill-library suites.

    Files that need a bespoke broker (custom scanners) keep a local ``broker``
    fixture, which shadows this one by pytest's resolution order.
    """
    from lighthouse_ai.sandbox.broker import build_default_broker

    return build_default_broker(tmp_path)
