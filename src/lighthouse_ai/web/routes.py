"""Mount the design bundle on a FastAPI app and add the JSON dashboard API."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..governor import BUDGET_DEFAULTS, Governor
from ..paths import Paths
from ..persistence import open_db
from ..verification.positions import score_all
from .api import register_api
from .events import EventBus, sse_format


def _static_root() -> Path:
    return Path(str(resources.files(__package__) / "static"))


def attach_web(app: FastAPI, paths: Paths, bus: EventBus | None = None) -> EventBus:
    """Mount static design bundle at ``/ui`` and the JSON API under ``/api``.

    Returns the :class:`EventBus` so the supervisor can publish to it.
    """
    bus = bus or EventBus()
    app.state.event_bus = bus

    @app.get("/", include_in_schema=False)
    def _root() -> RedirectResponse:
        return RedirectResponse(url="/ui/", status_code=307)

    @app.get("/api/dashboard", tags=["dashboard"])
    def dashboard() -> dict[str, Any]:
        return _build_dashboard(paths)

    @app.get("/api/events", tags=["events"])
    async def events() -> StreamingResponse:
        # Bind the loop lazily on first SSE connect (avoids deprecated
        # on_event startup hooks; publish works inline before this anyway).
        bus.bind_loop(asyncio.get_running_loop())
        q = bus.subscribe()

        async def _stream():
            try:
                yield ": connected\n\n"
                while True:
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield sse_format(msg)
                    except TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                bus.unsubscribe(q)

        return StreamingResponse(_stream(), media_type="text/event-stream")

    # All the page endpoints.
    register_api(app, paths, bus)

    # The static mount must be LAST — it grabs every URL under /ui/.
    app.mount("/ui", StaticFiles(directory=str(_static_root()), html=True),
              name="ui")
    return bus


# ---------------------------------------------------------------- payload --

def _build_dashboard(paths: Paths) -> dict[str, Any]:
    """Assemble the shape the React MOCK in ``home-shared.jsx`` expects."""
    now = datetime.now()
    out: dict[str, Any] = {
        "date": now.strftime("%A · %d %B %Y"),
        "generated_at": now.isoformat(timespec="seconds"),
        "greeting": "Good morning",
    }

    out["jobs"] = _read_jobs(paths)
    out["calibration"] = _read_calibration(paths)
    out["budget"] = _read_budget(paths)
    out["alerts"] = _build_alerts(paths, out)
    out["lead"] = _lead_from_jobs(out.get("jobs") or [])
    out["digest"] = _digest_from_jobs(out.get("jobs") or [])
    return out


def _lead_from_jobs(jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the most-progressed finished/review job as the dashboard lead."""
    candidates = [j for j in jobs if j.get("status") == "review"]
    if not candidates:
        return None
    j = candidates[0]
    return {
        "title": j.get("topic", "(untitled)"),
        "dek": f"Draft ready for review · {j.get('mode')} · {j.get('depth')}.",
        "wep": {"phrase": "likely", "class": "likely", "band": "0.60–0.90"},
        "topic": j.get("topic", ""),
        "sources": 0,
        "duration": j.get("eta", "—"),
    }


def _digest_from_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Surface running jobs as the digest stream until Mode D is wired."""
    out: list[dict[str, Any]] = []
    for j in jobs:
        if j.get("status") != "running":
            continue
        out.append({
            "topic": j.get("topic", "—"),
            "delta": f"{j.get('mode')} · {int(j.get('progress', 0) * 100)}% complete",
            "wep": {"phrase": "likely", "class": "likely"},
            "srcs": 0,
        })
    return out


def _read_jobs(paths: Paths) -> list[dict[str, Any]]:
    if not paths.state_db.exists():
        return []
    try:
        conn = open_db(paths.state_db)
        rows = conn.execute(
            "SELECT id, mode, status, metadata_json FROM jobs "
            "ORDER BY updated_at DESC LIMIT 20"
        ).fetchall()
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass
    out: list[dict[str, Any]] = []
    for jid, mode, status, mj in rows:
        md = json.loads(mj) if mj else {}
        out.append({
            "id": jid, "mode": mode, "status": status,
            "topic": md.get("topic", "(unnamed)"),
            "progress": float(md.get("progress", 0.0)),
            "eta": md.get("eta", "—"),
            "budget": float(md.get("budget", 0.0)),
            "depth": md.get("depth", "Standard"),
        })
    return out


def _read_calibration(paths: Paths) -> dict[str, Any]:
    if not paths.positions_db.exists():
        return {"brier": 0.0, "delta": 0.0, "resolved": 0, "pending": 0,
                "domains": [], "trend": []}
    try:
        metrics = score_all(paths.positions_db)
    except Exception:
        metrics = {"n": 0, "mean_brier": 0.0}
    return {
        "brier": round(float(metrics.get("mean_brier", 0.0)), 3),
        "delta": 0.0,
        "resolved": int(metrics.get("n", 0)),
        "pending": 0,
        "domains": [],
        "trend": [],
    }


def _read_budget(paths: Paths) -> dict[str, Any]:
    try:
        g = Governor(paths.state_db, BUDGET_DEFAULTS)
        rem = g.remaining()
    except Exception:
        return {"cloud": None, "tokens": None}
    return {
        "cloud": {
            "used": round(BUDGET_DEFAULTS.monthly_usd - rem["usd"]["monthly"], 2),
            "cap": BUDGET_DEFAULTS.monthly_usd,
            "period": "month",
        },
        "tokens": {
            "used": round((BUDGET_DEFAULTS.daily_tokens - rem["tokens"]["daily"]) / 1e6, 2),
            "cap": BUDGET_DEFAULTS.daily_tokens / 1e6,
            "period": "today",
            "unit": "M",
        },
        "tier": g.tier(),
    }


def _build_alerts(paths: Paths, dashboard: dict[str, Any]) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    budget = dashboard.get("budget", {}) or {}
    cloud = budget.get("cloud")
    if cloud and cloud["cap"]:
        pct = (cloud["used"] / cloud["cap"]) * 100
        if pct > 70:
            alerts.append({
                "kind": "budget",
                "text": f"Monthly cloud budget at {pct:.0f}%",
                "topic": "",
            })
    return alerts
