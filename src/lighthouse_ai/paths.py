"""Filesystem paths used across the Lighthouse install.

User data lives under ``~/.lighthouse/``. Litestream replicas mirror to
``/var/lighthouse/replicas/`` on Linux and to a user-writable shadow
directory on macOS (``~/Library/Application Support/Lighthouse/replicas``)
where ``/var`` is not user-writable without sudo.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _expand(p: str | os.PathLike[str]) -> Path:
    return Path(os.path.expanduser(os.fspath(p))).resolve()


@dataclass(frozen=True)
class Paths:
    data_dir: Path
    config_file: Path
    hardware_file: Path
    state_db: Path
    audit_db: Path
    intents_db: Path
    positions_db: Path
    hypotheses_db: Path
    reflections_db: Path
    entity_hotness_db: Path
    corpus_dir: Path
    staging_dir: Path
    quarantine_dir: Path
    worm_dir: Path
    skills_dir: Path
    logs_dir: Path
    run_dir: Path
    pid_file: Path
    litestream_config: Path
    replicas_dir: Path

    def all_dbs(self) -> list[Path]:
        return [
            self.state_db,
            self.audit_db,
            self.intents_db,
            self.positions_db,
            self.hypotheses_db,
            self.reflections_db,
            self.entity_hotness_db,
        ]

    def ensure(self) -> None:
        for d in (
            self.data_dir,
            self.corpus_dir,
            self.staging_dir,
            self.quarantine_dir,
            self.worm_dir,
            self.skills_dir,
            self.logs_dir,
            self.run_dir,
            self.replicas_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


def default_replicas_dir() -> Path:
    if sys.platform == "darwin":
        return _expand("~/Library/Application Support/Lighthouse/replicas")
    return Path("/var/lighthouse/replicas")


def make_paths(
    data_dir: str | os.PathLike[str] | None = None,
    replicas_dir: str | os.PathLike[str] | None = None,
) -> Paths:
    base = _expand(data_dir) if data_dir else _expand("~/.lighthouse")
    replicas = _expand(replicas_dir) if replicas_dir else default_replicas_dir()
    return Paths(
        data_dir=base,
        config_file=base / "config.toml",
        hardware_file=base / "hardware.json",
        state_db=base / "state.db",
        audit_db=base / "audit.db",
        intents_db=base / "intents.db",
        positions_db=base / "positions.db",
        hypotheses_db=base / "hypotheses.db",
        reflections_db=base / "reflections.db",
        entity_hotness_db=base / "entity_hotness.db",
        corpus_dir=base / "corpus",
        staging_dir=base / "staging",
        quarantine_dir=base / "quarantine",
        worm_dir=base / "worm",
        skills_dir=base / "skills",
        logs_dir=base / "logs",
        run_dir=base / "run",
        pid_file=base / "run" / "supervisor.pid",
        litestream_config=base / "litestream.yml",
        replicas_dir=replicas,
    )


def paths_from_env() -> Paths:
    """Build :class:`Paths` honoring ``$LIGHTHOUSE_DATA_DIR``.

    Single source of truth so the CLI, the supervisor, and the research
    pipeline all agree on which data dir they're operating on.
    """
    data = os.environ.get("LIGHTHOUSE_DATA_DIR")
    return make_paths(data) if data else make_paths()
