"""Unit tests for paths and directory bootstrap."""

from __future__ import annotations

from pathlib import Path

from lighthouse_ai.paths import default_replicas_dir, make_paths


def test_make_paths_defaults_to_dot_lighthouse():
    p = make_paths()
    assert p.data_dir.name == ".lighthouse"
    assert p.state_db == p.data_dir / "state.db"


def test_make_paths_honours_override(tmp_path: Path):
    p = make_paths(tmp_path)
    assert p.data_dir == tmp_path.resolve()
    assert p.state_db == p.data_dir / "state.db"


def test_ensure_creates_all_subdirs(tmp_path: Path):
    p = make_paths(tmp_path / "lh", tmp_path / "rep")
    p.ensure()
    for d in (
        p.corpus_dir,
        p.staging_dir,
        p.quarantine_dir,
        p.worm_dir,
        p.skills_dir,
        p.logs_dir,
        p.run_dir,
        p.replicas_dir,
    ):
        assert d.is_dir(), d


def test_all_dbs_returns_expected_paths(tmp_path: Path):
    p = make_paths(tmp_path)
    dbs = p.all_dbs()
    assert p.state_db in dbs
    assert p.reflections_db in dbs
    assert p.entity_hotness_db in dbs
    assert len(dbs) == 7


def test_paths_from_env_honors_env(tmp_path, monkeypatch):
    """Supervisor, CLI, and pipeline must all resolve the same data dir."""
    from lighthouse_ai.paths import paths_from_env

    monkeypatch.setenv("LIGHTHOUSE_DATA_DIR", str(tmp_path / "shared"))
    assert paths_from_env().data_dir == (tmp_path / "shared").resolve()


def test_paths_from_env_defaults_without_env(monkeypatch):
    from lighthouse_ai.paths import paths_from_env

    monkeypatch.delenv("LIGHTHOUSE_DATA_DIR", raising=False)
    assert paths_from_env().data_dir.name == ".lighthouse"


def test_default_replicas_dir_platform_specific():
    d = default_replicas_dir()
    import sys

    if sys.platform == "darwin":
        assert "Library/Application Support/Lighthouse" in str(d)
    elif sys.platform.startswith("linux"):
        assert str(d) == "/var/lighthouse/replicas"
