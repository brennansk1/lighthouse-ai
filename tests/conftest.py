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
