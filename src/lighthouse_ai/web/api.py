"""JSON API for the seven dashboard pages (design webapp_tui_design.md §2, §4).

All endpoints are thin shims over existing Lighthouse modules. Read paths
are pure SQLite reads; write paths go through the outbox where a supervisor
is the single writer, but for the in-process dashboard (single user, single
machine) we apply the write directly and emit an audit + SSE event.

Registered onto the FastAPI app by ``register_api(app, paths)``.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..governor import BUDGET_DEFAULTS, Governor
from ..paths import Paths
from ..persistence import integrity_check, open_db
from ..verification.positions import score_all
from .events import EventBus

# ---- request bodies -------------------------------------------------------

class NewJob(BaseModel):
    mode: str
    topic: str
    depth: str = "Standard"


class ResolveBody(BaseModel):
    outcome: str  # "confirmed" | "refuted" | "defer"
    notes: str | None = None


class NewTopic(BaseModel):
    name: str
    mode: str = "Monitor"
    cadence: str = "continuous"
    sources: list[str] = []


class NewHypothesis(BaseModel):
    statement: str


class StatusBody(BaseModel):
    status: str


class RejectBody(BaseModel):
    reason: str


class SecretBody(BaseModel):
    key: str
    value: str


class ActBody(BaseModel):
    pass  # no payload required; act_on_reflection uses the stored reflection


class NotifyEventsBody(BaseModel):
    events: list[str]
    telegram_events: list[str] | None = None


# ---- helpers --------------------------------------------------------------

def _rows(conn, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cur = conn.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _json_field(d: dict[str, Any], key: str) -> dict[str, Any]:
    raw = d.pop(key, None)
    return json.loads(raw) if raw else {}


def _fire_notify(paths: "Paths", event: str, title: str, body: str, **data: Any) -> None:
    """Best-effort notification dispatch from the web API.

    Loads the [notifications] config, builds channels, applies per-channel
    Telegram template rendering, and dispatches.  Never raises.
    """
    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        cfg: dict[str, Any] = {}
        if paths.config_file.exists():
            with paths.config_file.open("rb") as fh:
                cfg = tomllib.load(fh).get("notifications", {})
        if not cfg:
            return
        from .notify import DesktopChannel, DiscordChannel, Notifier
        from .notify.telegram import TelegramChannel
        from .notify.telegram_templates import render as _tg_render

        tg_events: list[str] = cfg.get(
            "telegram_events", cfg.get("events", [])
        )
        channels: list[tuple[str, Any]] = [("desktop", DesktopChannel())]
        if cfg.get("discord_webhook_url"):
            channels.append(("discord", DiscordChannel(cfg["discord_webhook_url"])))
        if cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"):
            if not tg_events or event in tg_events:
                channels.append(("telegram", TelegramChannel(
                    bot_token=cfg["telegram_bot_token"],
                    chat_id=cfg["telegram_chat_id"],
                )))
        plain_chs = [(n, c) for n, c in channels if n != "telegram"]
        tg_chs = [(n, c) for n, c in channels if n == "telegram"]
        if plain_chs:
            Notifier(cfg, plain_chs).notify(event, title, body)
        if tg_chs:
            tg_title, tg_body = _tg_render(event, title, body, **data)
            Notifier(cfg, tg_chs).notify(event, tg_title, tg_body)
    except Exception:
        pass


# ---- registration ---------------------------------------------------------

def register_api(app: FastAPI, paths: Paths, bus: EventBus) -> None:
    # Lazily build the Governor on first use — constructing it eagerly would
    # create state.db as a side effect of merely mounting the API, which
    # surprises callers that expect an un-initialized data dir.
    _gov_cache: dict[str, Governor] = {}

    def gov_get() -> Governor:
        if "g" not in _gov_cache:
            _gov_cache["g"] = Governor(paths.state_db, BUDGET_DEFAULTS)
        return _gov_cache["g"]

    # ============================ JOBS =============================

    @app.get("/api/jobs", tags=["jobs"])
    def list_jobs(status: str | None = None, limit: int = 50) -> dict[str, Any]:
        conn = open_db(paths.state_db)
        try:
            if status:
                rows = _rows(conn, "SELECT * FROM jobs WHERE status=? "
                             "ORDER BY updated_at DESC LIMIT ?", (status, limit))
            else:
                rows = _rows(conn, "SELECT * FROM jobs ORDER BY updated_at DESC "
                             "LIMIT ?", (limit,))
        finally:
            conn.close()
        for r in rows:
            r["metadata"] = _json_field(r, "metadata_json")
        return {"jobs": rows}

    @app.get("/api/jobs/{job_id}", tags=["jobs"])
    def get_job(job_id: str) -> dict[str, Any]:
        conn = open_db(paths.state_db)
        try:
            rows = _rows(conn, "SELECT * FROM jobs WHERE id=?", (job_id,))
        finally:
            conn.close()
        if not rows:
            raise HTTPException(404, f"job {job_id} not found")
        job = rows[0]
        job["metadata"] = _json_field(job, "metadata_json")
        # Recent model calls for this job from the audit log.
        aconn = open_db(paths.audit_db)
        try:
            calls = _rows(aconn, "SELECT seq, ts, actor, payload_json FROM audit_events "
                          "WHERE event_type='model_call' ORDER BY seq DESC LIMIT 50")
        finally:
            aconn.close()
        for c in calls:
            p = _json_field(c, "payload_json")
            if p.get("job_id") == job_id:
                c["model"] = p.get("model")
                c["tokens"] = p.get("prompt_tokens", 0) + p.get("completion_tokens", 0)
        job["model_calls"] = [c for c in calls if c.get("model")]
        return job

    @app.post("/api/jobs", tags=["jobs"])
    def create_job(body: NewJob) -> dict[str, Any]:
        import uuid
        jid = uuid.uuid4().hex[:6]
        meta = {"topic": body.topic, "progress": 0.0, "depth": body.depth,
                "eta": "queued"}
        conn = open_db(paths.state_db)
        try:
            conn.execute(
                "INSERT INTO jobs (id, mode, status, metadata_json) "
                "VALUES (?, ?, 'queued', ?)",
                (jid, body.mode, json.dumps(meta)),
            )
        finally:
            conn.close()
        bus.publish("job.status", {"id": jid, "status": "queued"})
        return {"id": jid, "status": "queued"}

    def _set_job_status(job_id: str, status: str) -> dict[str, Any]:
        conn = open_db(paths.state_db)
        try:
            cur = conn.execute(
                "UPDATE jobs SET status=?, updated_at=datetime('now') WHERE id=?",
                (status, job_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(404, f"job {job_id} not found")
        finally:
            conn.close()
        bus.publish("job.status", {"id": job_id, "status": status})
        return {"id": job_id, "status": status}

    @app.post("/api/jobs/{job_id}/pause", tags=["jobs"])
    def pause_job(job_id: str) -> dict[str, Any]:
        return _set_job_status(job_id, "paused")

    @app.post("/api/jobs/{job_id}/resume", tags=["jobs"])
    def resume_job(job_id: str) -> dict[str, Any]:
        return _set_job_status(job_id, "running")

    @app.post("/api/jobs/{job_id}/cancel", tags=["jobs"])
    def cancel_job(job_id: str) -> dict[str, Any]:
        return _set_job_status(job_id, "cancelled")

    # ============================ DRAFTS ===========================

    @app.get("/api/drafts", tags=["drafts"])
    def list_drafts(status: str | None = None) -> dict[str, Any]:
        conn = open_db(paths.state_db)
        try:
            if status:
                rows = _rows(conn, "SELECT id, job_id, topic, title, wep_band, "
                             "wep_phrase, confidence, source_count, status, created_at "
                             "FROM drafts WHERE status=? ORDER BY created_at DESC",
                             (status,))
            else:
                rows = _rows(conn, "SELECT id, job_id, topic, title, wep_band, "
                             "wep_phrase, confidence, source_count, status, created_at "
                             "FROM drafts ORDER BY created_at DESC")
        finally:
            conn.close()
        return {"drafts": rows}

    @app.get("/api/drafts/{draft_id}", tags=["drafts"])
    def get_draft(draft_id: str) -> dict[str, Any]:
        conn = open_db(paths.state_db)
        try:
            rows = _rows(conn, "SELECT * FROM drafts WHERE id=?", (draft_id,))
        finally:
            conn.close()
        if not rows:
            raise HTTPException(404, f"draft {draft_id} not found")
        return rows[0]

    @app.post("/api/drafts/{draft_id}/approve", tags=["drafts"])
    def approve_draft(draft_id: str) -> dict[str, Any]:
        conn = open_db(paths.state_db)
        try:
            cur = conn.execute(
                "UPDATE drafts SET status='published', updated_at=datetime('now') "
                "WHERE id=? AND status='staged'", (draft_id,))
            if cur.rowcount == 0:
                raise HTTPException(404, f"no staged draft {draft_id}")
            # Move the originating job to a terminal state so the dashboard
            # doesn't keep showing it as 'review' after publish.
            conn.execute(
                "UPDATE jobs SET status='done', updated_at=datetime('now') "
                "WHERE id = (SELECT job_id FROM drafts WHERE id=?)", (draft_id,))
        finally:
            conn.close()
        # Auto-export to Logseq if configured
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        try:
            if paths.config_file.exists():
                with paths.config_file.open("rb") as fh:
                    _cfg = tomllib.load(fh)
                logseq_cfg = _cfg.get("logseq", {})
                if logseq_cfg.get("enabled") and logseq_cfg.get("graph_dir"):
                    from pathlib import Path as _Path
                    from ..targets.logseq import export_draft as _logseq_export
                    _conn = open_db(paths.state_db)
                    try:
                        row = _conn.execute(
                            "SELECT body_html, title, topic, wep_phrase, source_count "
                            "FROM drafts WHERE id=?", (draft_id,)
                        ).fetchone()
                    finally:
                        _conn.close()
                    if row:
                        _graph_dir = _Path(logseq_cfg["graph_dir"]).expanduser()
                        _logseq_export(
                            _graph_dir,
                            draft_id=draft_id,
                            title=row[1] or draft_id,
                            body_html=row[0] or "",
                            topic=row[2] or "",
                            wep_phrase=row[3],
                            source_count=row[4] or 0,
                        )
        except Exception as _exc:
            import structlog as _structlog
            _structlog.get_logger(__name__).warning(
                "logseq.export_failed", draft_id=draft_id, error=str(_exc)
            )  # Logseq export is best-effort; never fail the approval
        bus.publish("draft.approved", {"id": draft_id})
        # Fire Telegram/desktop notification for draft approval (best-effort)
        _fire_notify(paths, "draft_approved", "Draft approved",
                     f"Draft approved: {draft_id}",
                     draft_id=draft_id)
        return {"id": draft_id, "status": "published"}

    @app.post("/api/drafts/{draft_id}/reject", tags=["drafts"])
    def reject_draft(draft_id: str, body: RejectBody) -> dict[str, Any]:
        conn = open_db(paths.state_db)
        try:
            cur = conn.execute(
                "UPDATE drafts SET status='rejected', reject_reason=?, "
                "updated_at=datetime('now') WHERE id=? AND status='staged'",
                (body.reason, draft_id))
            if cur.rowcount == 0:
                raise HTTPException(404, f"no staged draft {draft_id}")
        finally:
            conn.close()
        bus.publish("draft.rejected", {"id": draft_id, "reason": body.reason})
        return {"id": draft_id, "status": "rejected"}

    # ============================ TOPICS ===========================

    @app.get("/api/topics", tags=["topics"])
    def list_topics() -> dict[str, Any]:
        conn = open_db(paths.state_db)
        try:
            topics = _rows(conn, "SELECT * FROM topics ORDER BY updated_at DESC")
            counts = {r["topic_id"]: r["n"] for r in _rows(
                conn, "SELECT topic_id, COUNT(*) AS n FROM sources GROUP BY topic_id")}
        finally:
            conn.close()
        for t in topics:
            t["source_count"] = counts.get(t["id"], 0)
        return {"topics": topics}

    @app.get("/api/topics/{topic_id}", tags=["topics"])
    def get_topic(topic_id: str) -> dict[str, Any]:
        conn = open_db(paths.state_db)
        try:
            rows = _rows(conn, "SELECT * FROM topics WHERE id=?", (topic_id,))
            if not rows:
                raise HTTPException(404, f"topic {topic_id} not found")
            sources = _rows(conn, "SELECT * FROM sources WHERE topic_id=? ORDER BY id",
                            (topic_id,))
        finally:
            conn.close()
        topic = rows[0]
        topic["sources"] = sources
        return topic

    @app.post("/api/topics", tags=["topics"])
    def create_topic(body: NewTopic) -> dict[str, Any]:
        import uuid
        tid = uuid.uuid4().hex[:8]
        conn = open_db(paths.state_db)
        try:
            conn.execute("INSERT INTO topics (id, name, mode, cadence) VALUES (?,?,?,?)",
                         (tid, body.name, body.mode, body.cadence))
            for url in body.sources:
                conn.execute("INSERT INTO sources (topic_id, url) VALUES (?, ?)",
                             (tid, url))
        finally:
            conn.close()
        return {"id": tid, "name": body.name}

    @app.delete("/api/topics/{topic_id}", tags=["topics"])
    def delete_topic(topic_id: str) -> dict[str, Any]:
        conn = open_db(paths.state_db)
        try:
            conn.execute("DELETE FROM sources WHERE topic_id=?", (topic_id,))
            cur = conn.execute("DELETE FROM topics WHERE id=?", (topic_id,))
            if cur.rowcount == 0:
                raise HTTPException(404, f"topic {topic_id} not found")
        finally:
            conn.close()
        return {"id": topic_id, "deleted": True}

    # ========================== POSITIONS ==========================

    @app.get("/api/positions", tags=["positions"])
    def list_positions(overdue: bool = False, resolved: bool | None = None
                       ) -> dict[str, Any]:
        from ..verification.positions import _ensure_extras
        _ensure_extras(paths.positions_db)
        conn = open_db(paths.positions_db)
        try:
            sql = "SELECT * FROM positions"
            clauses = []
            if resolved is True:
                clauses.append("outcome IS NOT NULL")
            elif resolved is False or overdue:
                clauses.append("outcome IS NULL")
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY created_at DESC"
            rows = _rows(conn, sql)
        finally:
            conn.close()
        return {"positions": rows}

    @app.post("/api/positions/{position_id}/resolve", tags=["positions"])
    def resolve(position_id: int, body: ResolveBody) -> dict[str, Any]:
        from ..verification.positions import resolve_position
        if body.outcome == "defer":
            return {"id": position_id, "deferred": True}
        outcome = body.outcome == "confirmed"
        try:
            pos = resolve_position(paths.positions_db, position_id, outcome=outcome)
        except KeyError:
            raise HTTPException(404, f"position {position_id} not found") from None
        bus.publish("position.resolved", {"id": position_id, "outcome": outcome,
                                          "brier": pos.brier})
        return {"id": position_id, "outcome": outcome, "brier": pos.brier}

    @app.get("/api/calibration", tags=["positions"])
    def calibration() -> dict[str, Any]:
        return score_all(paths.positions_db)

    # ========================= HYPOTHESES ==========================

    @app.get("/api/hypotheses", tags=["positions"])
    def list_hypotheses(status: str | None = None) -> dict[str, Any]:
        from ..verification.hypotheses import list_hypotheses as _lh
        items = _lh(paths.hypotheses_db, status=status)
        return {"hypotheses": [h.__dict__ for h in items]}

    @app.post("/api/hypotheses", tags=["positions"])
    def create_hypothesis(body: NewHypothesis) -> dict[str, Any]:
        from ..verification.hypotheses import add_hypothesis
        hid = add_hypothesis(paths.hypotheses_db, body.statement)
        return {"id": hid, "statement": body.statement}

    @app.patch("/api/hypotheses/{hid}", tags=["positions"])
    def patch_hypothesis(hid: int, body: StatusBody) -> dict[str, Any]:
        from ..verification.hypotheses import update_hypothesis
        try:
            update_hypothesis(paths.hypotheses_db, hid, body.status)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"id": hid, "status": body.status}

    # ============================ HEALTH ===========================

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, Any]:
        return _build_health(paths, gov_get())

    @app.get("/api/audit", tags=["health"])
    def audit(limit: int = 100, event_type: str | None = None) -> dict[str, Any]:
        conn = open_db(paths.audit_db)
        try:
            if event_type:
                rows = _rows(conn, "SELECT seq, ts, actor, event_type, payload_json "
                             "FROM audit_events WHERE event_type=? "
                             "ORDER BY seq DESC LIMIT ?", (event_type, limit))
            else:
                rows = _rows(conn, "SELECT seq, ts, actor, event_type, payload_json "
                             "FROM audit_events ORDER BY seq DESC LIMIT ?", (limit,))
        finally:
            conn.close()
        for r in rows:
            r["payload"] = _json_field(r, "payload_json")
        return {"events": rows}

    @app.post("/api/audit/verify", tags=["health"])
    def audit_verify() -> dict[str, Any]:
        from ..verification.audit_chain import resolve_secret, verify_audit_chain
        try:
            secret = resolve_secret(None, data_dir=paths.data_dir)
        except Exception as exc:
            raise HTTPException(500, f"cannot resolve secret: {exc}") from None
        bad = verify_audit_chain(paths.audit_db, secret=secret)
        return {"ok": not bad, "bad_seqs": bad}

    @app.post("/api/governor/reset", tags=["health"])
    def governor_reset() -> dict[str, Any]:
        n = gov_get().reset()
        return {"reset": n}

    @app.post("/api/governor/kill", tags=["health"])
    def governor_kill() -> dict[str, Any]:
        conn = open_db(paths.state_db)
        try:
            conn.execute("UPDATE supervisor_state SET status='kill_switched', "
                         "updated_at=datetime('now') WHERE id=1")
        finally:
            conn.close()
        bus.publish("governor.tripped", {"reason": "manual kill"})
        return {"killed": True}

    @app.post("/api/quarantine/{sha}/restore", tags=["health"])
    def quarantine_restore(sha: str, dest: str) -> dict[str, Any]:
        from ..sandbox import Quarantine
        q = Quarantine(paths.data_dir / "quarantine.db", paths.data_dir / "quarantine")
        try:
            out = q.restore(sha, Path(dest))
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from None
        return {"restored": str(out)}

    # ============================ SETTINGS =========================

    @app.get("/api/settings", tags=["settings"])
    def get_settings() -> dict[str, Any]:
        cfg = {}
        if paths.config_file.exists():
            try:
                import tomllib
            except ImportError:  # pragma: no cover
                import tomli as tomllib  # type: ignore
            with paths.config_file.open("rb") as fh:
                cfg = tomllib.load(fh)
        return {"config": cfg}

    @app.get("/api/skills", tags=["settings"])
    def list_skills() -> dict[str, Any]:
        from ..verification.skills import list_skills as _ls
        return {"skills": [s.__dict__ for s in _ls(paths.state_db)]}

    @app.get("/api/perspectives", tags=["settings"])
    def list_perspectives() -> dict[str, Any]:
        conn = open_db(paths.state_db)
        try:
            rows = _rows(conn, "SELECT * FROM perspectives ORDER BY name")
        finally:
            conn.close()
        return {"perspectives": rows}

    @app.get("/api/secrets", tags=["settings"])
    def list_secrets() -> dict[str, Any]:
        from ..secrets import SecretStore
        keys = SecretStore(paths.data_dir).list()
        return {"secrets": {k: "***" for k in keys}}

    @app.post("/api/secrets", tags=["settings"])
    def set_secret(body: SecretBody) -> dict[str, Any]:
        from ..secrets import SecretStore
        backend = SecretStore(paths.data_dir).put(body.key, body.value)
        return {"key": body.key, "backend": backend}

    @app.get("/api/settings/logseq", tags=["settings"])
    def logseq_status() -> dict[str, Any]:
        """Return Logseq integration status and pending sync count."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        cfg: dict[str, Any] = {}
        if paths.config_file.exists():
            with paths.config_file.open("rb") as fh:
                cfg = tomllib.load(fh).get("logseq", {})
        pending = 0
        if cfg.get("enabled") and paths.state_db.exists():
            try:
                from ..compounding.logseq_sync import pending_count
                pending = pending_count(paths)
            except Exception:
                pass
        return {
            "enabled": cfg.get("enabled", False),
            "graph_dir": cfg.get("graph_dir"),
            "sync_interval_hours": cfg.get("sync_interval_hours", 24),
            "pending_sync": pending,
        }

    # ========================= NOTIFICATIONS =======================

    _NOTIFY_ALL_EVENTS = [
        "draft_ready", "draft_approved", "job_started", "job_completed",
        "job_failed", "monitor_alert_high", "monitor_alert_medium",
        "budget_warn", "budget_trip", "logseq_synced",
        "escalation_raised", "position_resolved",
    ]

    @app.get("/api/settings/notifications", tags=["settings"])
    def notifications_status() -> dict[str, Any]:
        """Return notification channel configuration and event subscriptions."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        cfg: dict[str, Any] = {}
        if paths.config_file.exists():
            with paths.config_file.open("rb") as fh:
                cfg = tomllib.load(fh).get("notifications", {})
        tg_token = cfg.get("telegram_bot_token", "")
        tg_chat = cfg.get("telegram_chat_id", "")
        tg_events = cfg.get("telegram_events", cfg.get("events", _NOTIFY_ALL_EVENTS))
        return {
            "channels": {
                "desktop": {"enabled": cfg.get("desktop_enabled", True)},
                "discord": {"enabled": bool(cfg.get("discord_webhook_url"))},
                "telegram": {
                    "enabled": bool(tg_token and tg_chat),
                    "configured": bool(tg_token and tg_chat),
                    "events": tg_events,
                },
            },
            "events": cfg.get("events", _NOTIFY_ALL_EVENTS),
            "all_events": _NOTIFY_ALL_EVENTS,
        }

    @app.patch("/api/settings/notifications", tags=["settings"])
    def update_notify_events(body: NotifyEventsBody) -> dict[str, Any]:
        """Update which events are routed to notification channels.

        Writes directly to config.toml. Only events in the known list are accepted.
        """
        unknown = [e for e in body.events if e not in _NOTIFY_ALL_EVENTS]
        if unknown:
            raise HTTPException(400, f"unknown events: {unknown}")
        if body.telegram_events is not None:
            bad = [e for e in body.telegram_events if e not in _NOTIFY_ALL_EVENTS]
            if bad:
                raise HTTPException(400, f"unknown telegram_events: {bad}")

        if not paths.config_file.exists():
            raise HTTPException(404, "config.toml not found — run `lighthouse init` first")
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        try:
            import tomli_w
        except ImportError:
            raise HTTPException(500, "tomli-w not installed; edit config.toml manually") from None

        with paths.config_file.open("rb") as fh:
            cfg_all = tomllib.load(fh)
        notif = cfg_all.setdefault("notifications", {})
        notif["events"] = body.events
        if body.telegram_events is not None:
            notif["telegram_events"] = body.telegram_events
        with paths.config_file.open("wb") as fh:
            tomli_w.dump(cfg_all, fh)
        return {"events": body.events, "telegram_events": body.telegram_events}

    # ========================= INTELLIGENCE (§3) ===================

    def _reflection_store():
        from ..subconscious.store import ReflectionStore
        return ReflectionStore(paths.reflections_db)

    @app.get("/api/reflections", tags=["intelligence"])
    def list_reflections(limit: int = 100) -> dict[str, Any]:
        """Return recent passive reflections (provenance notes, never auto-post)."""
        store = _reflection_store()
        items = store.list_reflections(limit=limit)
        return {
            "reflections": [
                {
                    "id": r.id,
                    "kind": r.kind.value,
                    "body": r.body,
                    "proposed_action": r.proposed_action,
                    "source_refs": r.source_refs,
                    "created_at": r.created_at,
                }
                for r in items
            ]
        }

    @app.get("/api/escalations", tags=["intelligence"])
    def list_escalations(status: str | None = None) -> dict[str, Any]:
        """Return escalations, optionally filtered by status."""
        from ..subconscious.types import EscalationStatus
        store = _reflection_store()
        status_filter = EscalationStatus(status) if status else None
        items = store.list_escalations(status=status_filter)
        return {
            "escalations": [
                {
                    "id": e.id,
                    "kind": e.kind.value,
                    "body": e.body,
                    "priority": e.priority.value,
                    "status": e.status.value,
                    "source_refs": e.source_refs,
                    "created_at": e.created_at,
                    "updated_at": e.updated_at,
                }
                for e in items
            ]
        }

    @app.post("/api/reflections/{reflection_id}/act", tags=["intelligence"])
    def reflections_act(reflection_id: str) -> dict[str, Any]:
        """Spawn a fresh research job acting on the given reflection."""
        store = _reflection_store()
        reflections = store.list_reflections(limit=1000)
        target = next((r for r in reflections if r.id == reflection_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="reflection not found")

        # Reuse the existing job-creation path so the job lands in the same store.
        import uuid
        from ..persistence import open_db as _open_db

        def _spawn(seed: str) -> str:
            job_id = uuid.uuid4().hex[:8]
            meta = json.dumps({"topic": seed[:200], "progress": 0.0, "eta": "queued"})
            conn = _open_db(paths.state_db)
            try:
                conn.execute(
                    "INSERT INTO jobs (id, mode, status, metadata_json) VALUES (?, ?, ?, ?)",
                    (job_id, "deepdive", "queued", meta),
                )
            except Exception as exc:
                raise HTTPException(status_code=500,
                                    detail=f"failed to create job: {exc}") from exc
            finally:
                conn.close()
            bus.publish("jobs.created", {"id": job_id})
            return job_id

        from ..subconscious.engine import act_on_reflection
        job_id = act_on_reflection(target, spawn=_spawn)
        bus.publish("intelligence.acted", {"reflection_id": reflection_id, "job_id": job_id})
        return {"job_id": job_id, "reflection_id": reflection_id}

    @app.patch("/api/escalations/{escalation_id}/status", tags=["intelligence"])
    def update_escalation_status(escalation_id: str, body: StatusBody) -> dict[str, Any]:
        """Update the status of an escalation (open → acknowledged → resolved)."""
        from ..subconscious.types import EscalationStatus
        try:
            new_status = EscalationStatus(body.status)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"invalid status: {body.status!r}")
        store = _reflection_store()
        updated = store.update_escalation_status(escalation_id, new_status)
        if not updated:
            raise HTTPException(status_code=404, detail="escalation not found")
        bus.publish("intelligence.escalation_updated",
                    {"escalation_id": escalation_id, "status": body.status})
        return {"escalation_id": escalation_id, "status": body.status}

    # ========================= RESEARCH PLAN =======================

    @app.post("/api/research/plan", tags=["research"])
    def preview_plan(body: dict) -> dict[str, Any]:
        from ..framing.pipeline import run_framing
        question = str(body.get("question", "")).strip()
        if not question:
            raise HTTPException(status_code=422, detail="question is required")
        try:
            fq = run_framing(question)
            return {
                "question_type": fq.question_type.value,
                "critique": {
                    "well_formed": fq.critique.well_formed,
                    "is_compound": fq.critique.is_compound,
                    "has_presupposition": fq.critique.has_presupposition,
                    "is_underspecified": fq.critique.is_underspecified,
                    "implicit_utility": fq.critique.implicit_utility,
                    "notes": fq.critique.notes,
                },
                "framings": [
                    {"label": f.label, "statement": f.statement, "rationale": f.rationale}
                    for f in fq.framings
                ],
                "chosen_label": fq.chosen.label,
                "sub_questions": fq.sub_questions,
                "load_bearing": fq.load_bearing,
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---- health payload -------------------------------------------------------

def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def _build_health(paths: Paths, gov: Governor) -> dict[str, Any]:
    from ..hardware import probe
    from ..intents import outbox_depth
    from ..litestream import replica_lags

    profile = probe()
    # databases
    db_status: dict[str, str] = {}
    for kind, p in {
        "state": paths.state_db, "audit": paths.audit_db, "intents": paths.intents_db,
        "positions": paths.positions_db, "hypotheses": paths.hypotheses_db,
    }.items():
        if not p.exists():
            db_status[kind] = "absent"
            continue
        try:
            conn = open_db(p)
            try:
                db_status[kind] = integrity_check(conn)
            finally:
                conn.close()
        except Exception as exc:
            db_status[kind] = f"error: {exc!r}"

    # external services (probe is cheap, never blocks)
    try:
        from ..backends.ollama import OllamaBackend
        ollama_ok = OllamaBackend().available()
    except Exception:
        ollama_ok = False
    try:
        from ..rag.qdrant_store import QdrantStore
        qdrant_ok = QdrantStore(dim=8).available()
    except Exception:
        qdrant_ok = False

    # budget
    rem = gov.remaining()
    tier = gov.tier()

    # storage
    import psutil
    disk = psutil.disk_usage(str(paths.data_dir if paths.data_dir.exists() else Path.home()))
    subdirs = {name: _dir_size(getattr(paths, attr)) for name, attr in [
        ("corpus", "corpus_dir"), ("quarantine", "quarantine_dir"),
        ("worm", "worm_dir"), ("staging", "staging_dir"), ("logs", "logs_dir"),
    ]}

    # outbox
    depth = outbox_depth(paths.intents_db) if paths.intents_db.exists() else 0

    # audit chain (best-effort)
    chain_ok = None
    if paths.audit_db.exists():
        try:
            from ..verification.audit_chain import resolve_secret, verify_audit_chain
            secret = resolve_secret(None, data_dir=paths.data_dir)
            chain_ok = not verify_audit_chain(paths.audit_db, secret=secret)
        except Exception:
            chain_ok = None

    all_db_ok = all(v == "ok" for v in db_status.values())
    overall_green = all_db_ok and depth < 100 and (chain_ok is not False)

    return {
        "overall": "green" if overall_green else "attention",
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "hardware": {
            "platform": profile.platform, "arch": profile.arch,
            "total_ram_gb": profile.total_ram_gb, "tier": profile.suggested_tier,
        },
        "databases": db_status,
        "external": {"ollama": ollama_ok, "qdrant": qdrant_ok,
                     "litestream": shutil.which("litestream") is not None},
        "budget": {
            "tier": tier,
            "usd": {"used": round(BUDGET_DEFAULTS.monthly_usd - rem["usd"]["monthly"], 2),
                    "cap": BUDGET_DEFAULTS.monthly_usd},
            "tokens": {"used": BUDGET_DEFAULTS.daily_tokens - rem["tokens"]["daily"],
                       "cap": BUDGET_DEFAULTS.daily_tokens},
            "tool_calls": {"used": BUDGET_DEFAULTS.daily_tool_calls - rem["tool_calls"]["daily"],
                           "cap": BUDGET_DEFAULTS.daily_tool_calls},
        },
        "storage": {
            "disk_total_gb": round(disk.total / 1e9, 1),
            "disk_free_gb": round(disk.free / 1e9, 1),
            "subdirs_bytes": subdirs,
            "replicas": [lag.__dict__ for lag in replica_lags(paths)],
        },
        "outbox_depth": depth,
        "audit_chain_ok": chain_ok,
    }
