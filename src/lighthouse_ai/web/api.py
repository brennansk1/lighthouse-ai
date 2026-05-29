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
    budget: str | None = None  # Deep-tier wall-clock/node budget (30m/1h/2h/overnight)
    options: list[str] = []
    criteria: list[dict[str, Any]] = []
    source_urls: list[str] = []


class ResolveBody(BaseModel):
    outcome: str  # "confirmed" | "refuted" | "defer"
    notes: str | None = None


class SettingsPatch(BaseModel):
    offline_mode: bool | None = None
    backup_enabled: bool | None = None
    notify_enabled: bool | None = None
    theme: str | None = None


class NewTopic(BaseModel):
    name: str
    mode: str = "Monitor"
    cadence: str = "continuous"
    sources: list[str] = []


class NewHypothesis(BaseModel):
    statement: str


class NewMonitorSession(BaseModel):
    label: str
    source_urls: list[str] = []
    starts_at: str | None = None
    ends_at: str | None = None
    auto_stop: bool = True
    poll_interval_s: int = 300
    quiet_cycles: int = 3
    salience_floor: float = 0.5
    max_duration_s: int = 86400


class StatusBody(BaseModel):
    status: str


class RejectBody(BaseModel):
    reason: str


class SecretBody(BaseModel):
    key: str
    value: str


class ActBody(BaseModel):
    pass  # no payload required; act_on_reflection uses the stored reflection


# ---- helpers --------------------------------------------------------------

def _rows(conn, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    cur = conn.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _json_field(d: dict[str, Any], key: str) -> dict[str, Any]:
    raw = d.pop(key, None)
    return json.loads(raw) if raw else {}


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

        from ..modes.registry import canonical, resolve
        try:
            mode_key = canonical(body.mode)
            spec = resolve(mode_key)
        except KeyError:
            raise HTTPException(400, f"unknown mode: {body.mode!r}") from None
        # Decide needs at least two options and weighted criteria up front.
        if "options" in spec.requires and len(body.options) < 2:
            raise HTTPException(400, "Decide requires at least two options")
        if "criteria" in spec.requires and not body.criteria:
            raise HTTPException(400, "Decide requires at least one weighted criterion")
        # Adjudicate needs a real adversarial set (steelman / devil's-advocate /
        # base-rate / fragility). A 2-3 perspective "debate" only legitimizes a
        # decision instead of stress-testing it, so Quick is promoted to Standard.
        depth = body.depth
        if mode_key == "adjudicate" and str(depth).strip().lower() == "quick":
            depth = "standard"
        jid = uuid.uuid4().hex[:6]
        meta = {"topic": body.topic, "progress": 0.0, "depth": depth,
                "eta": "queued"}
        if body.budget:
            meta["budget"] = body.budget
        if body.options:
            meta["options"] = body.options
        if body.criteria:
            meta["criteria"] = body.criteria
        if body.source_urls:
            meta["source_urls"] = body.source_urls
        conn = open_db(paths.state_db)
        try:
            conn.execute(
                "INSERT INTO jobs (id, mode, status, metadata_json) "
                "VALUES (?, ?, 'queued', ?)",
                (jid, mode_key, json.dumps(meta)),
            )
        finally:
            conn.close()
        bus.publish("job.status", {"id": jid, "status": "queued"})
        return {"id": jid, "status": "queued", "mode": mode_key}

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
        bus.publish("draft.approved", {"id": draft_id})
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

    # ====================== MONITOR SESSIONS =======================

    @app.get("/api/monitor/sessions", tags=["monitors"])
    def list_monitor_sessions(status: str | None = None) -> dict[str, Any]:
        from dataclasses import asdict

        from ..modes.monitor_session import list_sessions
        sessions = list_sessions(paths.state_db, status=status)
        return {"sessions": [asdict(s) for s in sessions]}

    @app.get("/api/monitor/sessions/{session_id}", tags=["monitors"])
    def get_monitor_session(session_id: str) -> dict[str, Any]:
        from dataclasses import asdict

        from ..modes.monitor_session import get_session
        s = get_session(paths.state_db, session_id)
        if s is None:
            raise HTTPException(404, f"session {session_id} not found")
        return asdict(s)

    @app.get("/api/monitor/sessions/{session_id}/results", tags=["monitors"])
    def get_monitor_session_results(session_id: str) -> dict[str, Any]:
        from ..modes.monitor_session import get_session, get_session_results
        if get_session(paths.state_db, session_id) is None:
            raise HTTPException(404, f"session {session_id} not found")
        return {"results": get_session_results(paths.state_db, session_id)}

    @app.post("/api/monitor/sessions", tags=["monitors"])
    def create_monitor_session(body: NewMonitorSession) -> dict[str, Any]:
        from dataclasses import asdict

        from ..modes.monitor_session import (
            AutoStopConfig,
            SessionSpec,
            create_session,
        )
        spec = SessionSpec(
            label=body.label,
            source_urls=body.source_urls,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            auto_stop=body.auto_stop,
            poll_interval_s=body.poll_interval_s,
            auto=AutoStopConfig(
                quiet_cycles=body.quiet_cycles,
                salience_floor=body.salience_floor,
                max_duration_s=body.max_duration_s,
            ),
        )
        session = create_session(paths.state_db, spec)
        return asdict(session)

    @app.post("/api/monitor/sessions/{session_id}/stop", tags=["monitors"])
    def stop_monitor_session(session_id: str) -> dict[str, Any]:
        from dataclasses import asdict

        from ..modes.monitor_session import stop_session
        s = stop_session(paths.state_db, session_id, reason="manual")
        if s is None:
            raise HTTPException(404, f"session {session_id} not found")
        return asdict(s)

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
        return _build_health(paths)

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

    def _load_config() -> dict[str, Any]:
        if not paths.config_file.exists():
            return {}
        try:
            import tomllib
        except ImportError:  # pragma: no cover
            import tomli as tomllib  # type: ignore
        with paths.config_file.open("rb") as fh:
            return tomllib.load(fh)

    def _settings_payload() -> dict[str, Any]:
        cfg = _load_config()
        ui = cfg.get("ui", {}) if isinstance(cfg.get("ui"), dict) else {}
        return {
            "config": cfg,
            "data_dir": str(paths.data_dir),
            "offline_mode": bool(ui.get("offline_mode", False)),
            "backup_enabled": bool(ui.get("backup_enabled", False)),
            "notify_enabled": bool(ui.get("notify_enabled", False)),
            "theme": ui.get("theme", "system"),
        }

    @app.get("/api/settings", tags=["settings"])
    def get_settings() -> dict[str, Any]:
        return _settings_payload()

    @app.patch("/api/settings", tags=["settings"])
    def patch_settings(body: SettingsPatch) -> dict[str, Any]:
        import tomli_w

        cfg = _load_config()
        ui = cfg.get("ui")
        if not isinstance(ui, dict):
            ui = {}
        for key in ("offline_mode", "backup_enabled", "notify_enabled", "theme"):
            val = getattr(body, key)
            if val is not None:
                ui[key] = val
        cfg["ui"] = ui
        paths.config_file.parent.mkdir(parents=True, exist_ok=True)
        with paths.config_file.open("wb") as fh:
            tomli_w.dump(cfg, fh)
        return _settings_payload()

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
                    (job_id, "investigate", "queued", meta),
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
            raise HTTPException(status_code=422, detail=f"invalid status: {body.status!r}") from None
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

    # ============================ MODES ============================

    @app.get("/api/modes", tags=["research"])
    def list_modes() -> dict[str, Any]:
        from ..modes.registry import all_modes
        return {"modes": [m.as_dict() for m in all_modes()]}

    # =========================== LIBRARY ===========================

    @app.get("/api/library", tags=["library"])
    def library(type: str | None = None, status: str | None = None
                ) -> dict[str, Any]:
        clauses, params = [], []
        if type:
            clauses.append("artifact_type=?")
            params.append(type)
        if status:
            clauses.append("status=?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = open_db(paths.state_db)
        try:
            rows = _rows(conn,
                         "SELECT id, job_id, topic, title, artifact_type, wep_band, "
                         "wep_phrase, confidence, source_count, status, created_at "
                         f"FROM drafts{where} ORDER BY created_at DESC", tuple(params))
        finally:
            conn.close()
        return {"artifacts": rows}

    @app.get("/api/library/{artifact_id}", tags=["library"])
    def get_artifact(artifact_id: str) -> dict[str, Any]:
        conn = open_db(paths.state_db)
        try:
            rows = _rows(conn, "SELECT * FROM drafts WHERE id=?", (artifact_id,))
        finally:
            conn.close()
        if not rows:
            raise HTTPException(404, f"artifact {artifact_id} not found")
        art = rows[0]
        if art.get("body_json"):
            try:
                art["body"] = json.loads(art["body_json"])
            except (TypeError, ValueError):
                art["body"] = None
        return art

    @app.get("/api/library/{artifact_id}/export", tags=["library"])
    def export_artifact(artifact_id: str, format: str = "json"):
        from fastapi.responses import PlainTextResponse
        conn = open_db(paths.state_db)
        try:
            rows = _rows(conn, "SELECT * FROM drafts WHERE id=?", (artifact_id,))
        finally:
            conn.close()
        if not rows:
            raise HTTPException(404, f"artifact {artifact_id} not found")
        art = rows[0]
        body = None
        if art.get("body_json"):
            try:
                body = json.loads(art["body_json"])
            except (TypeError, ValueError):
                body = None
        if format == "json":
            return {"id": art["id"], "title": art["title"],
                    "artifact_type": art.get("artifact_type"), "body": body}
        if format == "md":
            md = f"# {art['title']}\n\n{art.get('body_html', '')}"
            return PlainTextResponse(md, media_type="text/markdown")
        if format == "csv":
            return PlainTextResponse(_artifact_to_csv(art, body),
                                     media_type="text/csv")
        raise HTTPException(400, f"unknown export format: {format!r}")

    # ========================= ASK SESSIONS ========================

    @app.get("/api/ask/sessions", tags=["library"])
    def ask_sessions(status: str | None = None) -> dict[str, Any]:
        from ..modes.ask_store import list_sessions
        return {"sessions": list_sessions(paths.state_db, status=status)}

    @app.get("/api/ask/sessions/{session_id}", tags=["library"])
    def ask_session(session_id: str) -> dict[str, Any]:
        from ..modes.ask_store import get_session_dict
        d = get_session_dict(paths.state_db, session_id)
        if d is None:
            raise HTTPException(404, f"session {session_id} not found")
        return d

    @app.post("/api/ask/sessions/{session_id}/turns/{idx}/promote", tags=["library"])
    def promote_ask_turn(session_id: str, idx: int) -> dict[str, Any]:
        from ..modes.ask_store import promote_turn
        try:
            draft_id = promote_turn(paths.state_db, session_id, idx)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        bus.publish("draft.staged", {"id": draft_id})
        return {"id": draft_id, "status": "staged", "artifact_type": "transcript"}

    # ====================== CALIBRATION TIMELINE ===================

    @app.get("/api/calibration/timeline", tags=["positions"])
    def calibration_timeline(bucket: str = "week") -> dict[str, Any]:
        from ..verification.positions import timeline
        return {"bucket": bucket,
                "buckets": timeline(paths.positions_db, bucket=bucket)}


# ---- health payload -------------------------------------------------------


def _artifact_to_csv(art: dict[str, Any], body: Any) -> str:
    """Flatten a table/matrix artifact into CSV; fall back to a title row."""
    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out)
    if isinstance(body, dict) and body.get("rows") and isinstance(body["rows"], list):
        # Survey evidence table: one row per document, columns per attribute.
        attrs = [a["label"] if isinstance(a, dict) else str(a)
                 for a in body.get("attributes", [])]
        w.writerow(["doc_id", "title", *attrs])
        for row in body["rows"]:
            cells = {c["attribute"]: c["value"] for c in row.get("cells", [])}
            w.writerow([row.get("doc_id", ""), row.get("title", ""),
                        *[cells.get(a, "") for a in attrs]])
    elif isinstance(body, dict) and body.get("cells") and body.get("totals"):
        # Decide matrix: option x criterion scores.
        w.writerow(["option", "criterion", "score", "contribution"])
        for c in body["cells"]:
            w.writerow([c.get("option"), c.get("criterion"),
                        c.get("score"), c.get("contribution")])
    elif isinstance(body, dict) and body.get("events"):
        # Reconstruct timeline.
        w.writerow(["date", "action", "sources", "certainty"])
        for e in body["events"]:
            w.writerow([e.get("date"), e.get("action"),
                        ";".join(e.get("sources", [])), e.get("certainty")])
    else:
        w.writerow(["title"])
        w.writerow([art.get("title", "")])
    return out.getvalue()

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


def _build_health(paths: Paths) -> dict[str, Any]:
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

    # chosen models for this hardware (per-role bindings the tier resolved to)
    try:
        from ..gateway import recommend_models
        chosen_models = {
            role: b.model for role, b in recommend_models(profile).items()
        }
    except Exception:
        chosen_models = {}

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
            "total_ram_gb": profile.total_ram_gb,
            "free_ram_gb": round(profile.free_ram_gb, 1),
            "tier": profile.suggested_tier,
            "cpu_cores_physical": profile.cpu_cores_physical,
            "cpu_cores_logical": profile.cpu_cores_logical,
            "gpu": [{"name": g.name, "vram_gb": g.vram_gb, "vendor": g.vendor}
                    for g in profile.gpu],
        },
        "chosen_models": chosen_models,
        "databases": db_status,
        "external": {"ollama": ollama_ok, "qdrant": qdrant_ok,
                     "litestream": shutil.which("litestream") is not None},
        "storage": {
            "disk_total_gb": round(disk.total / 1e9, 1),
            "disk_free_gb": round(disk.free / 1e9, 1),
            "subdirs_bytes": subdirs,
            "replicas": [lag.__dict__ for lag in replica_lags(paths)],
        },
        "outbox_depth": depth,
        "audit_chain_ok": chain_ok,
    }
