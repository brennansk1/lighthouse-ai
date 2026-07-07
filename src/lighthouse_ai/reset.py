"""Factory reset — wipe app data back to a fresh install.

What it clears: every row in every Lighthouse database (jobs, drafts, audit chain,
intents, positions, hypotheses, reflections, entity hotness), the sandbox
(uploads + workspace + metadata), the corpus / staging / quarantine / worm file
stores, and the on-disk config + cached hardware profile.

What it KEEPS: downloaded Ollama models (they live in Ollama, not Lighthouse) and
the DB *schemas* — the reset deletes rows rather than DB files, so the running
supervisor's open connections stay valid and consistent (no restart required;
the loops simply see empty tables on their next tick).

Destructive + irreversible. The API/CLI callers gate it behind an explicit
confirmation.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from .paths import Paths
from .persistence import open_db

log = structlog.get_logger(__name__)

#: sqlite internal tables we never touch (schema/autoindex bookkeeping).
_INTERNAL_TABLE_PREFIX = "sqlite_"


@dataclass
class ResetSummary:
    tables_cleared: int = 0
    rows_deleted: int = 0
    dirs_removed: list[str] = field(default_factory=list)
    files_removed: list[str] = field(default_factory=list)
    kept_models: bool = True

    def to_dict(self) -> dict:
        return {
            "tables_cleared": self.tables_cleared,
            "rows_deleted": self.rows_deleted,
            "dirs_removed": self.dirs_removed,
            "files_removed": self.files_removed,
            "kept_models": self.kept_models,
        }


def _wipe_db_rows(db_path: Path, summary: ResetSummary) -> None:
    if not db_path.exists():
        return
    conn = open_db(db_path)
    try:
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if not r[0].startswith(_INTERNAL_TABLE_PREFIX)
        ]
        # Defer FK enforcement so order-independent deletes don't trip references.
        conn.execute("PRAGMA foreign_keys = OFF")
        for t in tables:
            cur = conn.execute(f'DELETE FROM "{t}"')
            summary.tables_cleared += 1
            summary.rows_deleted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        # Reclaim space from the now-empty file.
        try:
            conn.execute("VACUUM")
        except Exception:  # pragma: no cover - VACUUM can fail mid-transaction
            pass
    finally:
        conn.close()


def factory_reset(paths: Paths, *, include_models: bool = False) -> ResetSummary:
    """Wipe all Lighthouse app data back to a fresh install.

    ``include_models`` is accepted for API symmetry but model deletion is NOT
    performed here (models live in Ollama, out of Lighthouse's data dir); the
    flag is recorded in the summary so the caller can act on it separately.
    """
    summary = ResetSummary(kept_models=not include_models)
    log.warning("factory_reset.start", data_dir=str(paths.data_dir), include_models=include_models)

    # 1. Clear every row from every core database (schema preserved).
    for db in paths.all_dbs():
        try:
            _wipe_db_rows(db, summary)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("factory_reset.db_error", db=str(db), error=str(exc))

    # 2. Remove the on-disk file stores (each is re-created empty by ensure()).
    #    The sandbox dir holds its own sandbox.db + the uploads/workspace zones.
    for d in (
        paths.data_dir / "sandbox",
        paths.corpus_dir,
        paths.staging_dir,
        paths.quarantine_dir,
        paths.worm_dir,
        paths.skills_dir,  # user-added skills only; the packaged library is in the wheel
    ):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            summary.dirs_removed.append(d.name)

    # 3. Remove user config + cached hardware profile (re-detected next run).
    for f in (paths.config_file, paths.hardware_file):
        if f.exists():
            try:
                f.unlink()
                summary.files_removed.append(f.name)
            except OSError:  # pragma: no cover - defensive
                pass

    # 4. Re-create the empty directory structure so the app keeps working.
    paths.ensure()

    log.warning("factory_reset.done", **summary.to_dict())
    return summary
