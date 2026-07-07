"""FastAPI control plane bound to 127.0.0.1:8765.

Per design §4: single FastAPI app exposes health, governor state, job index,
and (later) SSE/WS feeds. Sprint 1 only requires /health and a /governor
stub; subsequent sprints flesh out /jobs, /governor (real), /sandbox,
/dashboard, etc.

We expose ``create_app`` so the supervisor and tests can mount with their
own paths.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from . import __version__
from .paths import Paths, make_paths
from .persistence import integrity_check, open_db


def _supervisor_status(state_db: Path) -> dict[str, Any]:
    if not state_db.exists():
        return {"status": "uninitialized", "pid": None, "started_at": None}
    try:
        conn = open_db(state_db)
        try:
            row = conn.execute(
                "SELECT status, pid, started_at FROM supervisor_state WHERE id = 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.OperationalError:
        return {"status": "unmigrated", "pid": None, "started_at": None}
    if not row:
        return {"status": "unknown", "pid": None, "started_at": None}
    status, pid, started_at = row
    return {"status": status, "pid": pid, "started_at": started_at}


def _db_health(paths: Paths) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kind, p in {
        "state": paths.state_db,
        "audit": paths.audit_db,
        "intents": paths.intents_db,
        "positions": paths.positions_db,
        "hypotheses": paths.hypotheses_db,
    }.items():
        if not p.exists():
            out[kind] = {"present": False}
            continue
        try:
            conn = open_db(p)
            try:
                check = integrity_check(conn)
            finally:
                conn.close()
            out[kind] = {"present": True, "integrity_check": check, "size_bytes": p.stat().st_size}
        except Exception as exc:  # pragma: no cover - defensive
            out[kind] = {"present": True, "error": repr(exc)}
    return out


def _litestream_lag(paths: Paths) -> dict[str, Any]:
    """Best-effort replica freshness: youngest file mtime per replica dir."""
    if not paths.replicas_dir.exists():
        return {"present": False}
    out: dict[str, Any] = {"present": True, "replicas": {}}
    now = time.time()
    for sub in paths.replicas_dir.iterdir():
        if not sub.is_dir():
            continue
        youngest = 0.0
        for f in sub.rglob("*"):
            if f.is_file():
                youngest = max(youngest, f.stat().st_mtime)
        out["replicas"][sub.name] = {
            "youngest_mtime": youngest or None,
            "lag_seconds": round(now - youngest, 2) if youngest else None,
        }
    out["binary_installed"] = shutil.which("litestream") is not None
    return out


def create_app(paths: Paths | None = None, *, started_at: float | None = None) -> FastAPI:
    p = paths or make_paths()
    boot = started_at if started_at is not None else time.time()
    app = FastAPI(title="Lighthouse Control Plane", version=__version__)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "version": __version__,
            "uptime_seconds": round(time.time() - boot, 2),
            "supervisor": _supervisor_status(p.state_db),
            "databases": _db_health(p),
            "litestream": _litestream_lag(p),
        }

    @app.get("/governor")
    def governor() -> dict[str, Any]:
        depth = 0
        if p.intents_db.exists():
            try:
                conn = open_db(p.intents_db)
                try:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM intents WHERE status IN ('pending','in_flight')"
                    ).fetchone()
                    depth = int(row[0])
                finally:
                    conn.close()
            except sqlite3.OperationalError:
                depth = 0
        return {
            "outbox_depth": depth,
            "degradation_tier": "green",  # real impl: Sprint 3
            "kill_switched": False,
        }

    # Note: the richer ``/api/health`` (combining doctor + governor +
    # storage) is registered by ``attach_web`` → ``register_api``. The
    # legacy ``/health`` endpoint above stays for backwards-compatible
    # supervisor health checks.

    # Mount the design-bundle web UI at /ui/ and redirect / → /ui/.
    # The mount must happen after every API route is registered so the
    # StaticFiles catch-all doesn't shadow them.
    from .web import attach_web

    attach_web(app, p)

    return app
