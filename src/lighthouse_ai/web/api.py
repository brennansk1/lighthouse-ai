"""JSON API for the seven dashboard pages (design webapp_tui_design.md §2, §4).

All endpoints are thin shims over existing Lighthouse modules. Read paths
are pure SQLite reads; write paths go through the outbox where a supervisor
is the single writer, but for the in-process dashboard (single user, single
machine) we apply the write directly and emit an audit + SSE event.

Registered onto the FastAPI app by ``register_api(app, paths)``.
"""

from __future__ import annotations

import base64
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
    selected_skills: list[str] = []  # skill ids chosen in the source picker (Zone K)


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


class SandboxUpload(BaseModel):
    filename: str
    content_base64: str
    content_type: str | None = None


class PinBody(BaseModel):
    pinned: bool = True


class SandboxConfig(BaseModel):
    max_bytes: int | None = None


class PauseBody(BaseModel):
    hard: bool = False


class WatchVerifyBody(BaseModel):
    url: str


class WatchWebBody(BaseModel):
    url: str
    name: str | None = None
    criteria: dict[str, Any] | None = None
    cadence_minutes: int | None = None


class SteerabilityPut(BaseModel):
    locked: bool = False
    seed: int | None = None
    temperature: float | None = None
    top_p: float | None = None


# ---- Watch v2 live fetch (injectable so tests never hit the network) -------


def _watch_fetch(url: str) -> Any:
    """Single guarded fetch of a user-typed URL for Watch v2.

    Mirrors ingest's user-explicit fetch: the URL's own host is added to the
    egress allowlist (the user explicitly asked to watch this page) and the
    request is gated + logged by the egress proxy before any socket opens. Tests
    monkeypatch this module-level function so they never touch the network.

    Returns a small object exposing ``status_code`` / ``headers`` / ``content``
    so it can be adapted to scrapability's ``FetchResult``.
    """
    from ..governor.egress_proxy import DEFAULT_ALLOWED_DOMAINS, extract_host
    from ..net import guarded_get

    host = extract_host(url)
    allowed = frozenset(DEFAULT_ALLOWED_DOMAINS | {host}) if host else None
    return guarded_get(url, allowed_domains=allowed)


def _plain_language_verdict(url: str, verdict: Any) -> dict[str, Any]:
    """Translate a :class:`ScrapeVerdict` into a user-facing payload.

    No internal jargon leaks: the user sees ``can_watch`` + a headline + a
    one-line detail, never ``extract_tier`` / ``robots_ok`` and friends. The
    three roll-up verdicts map to:

      * ``good``    → "We can watch this page" (can_watch=True);
      * ``limited`` → either heavier ("needs a browser to read it fully") or a
        trust prompt when the host isn't reachable yet (can_watch=False until
        trusted);
      * ``blocked`` → robots disallow ("doesn't allow automated reading") or no
        readable content.
    """
    v = verdict.verdict
    if v == "good":
        return {
            "can_watch": True,
            "status": "good",
            "headline": "We can watch this page",
            "detail": "Lighthouse can read this page and tell you when it changes.",
            "change_method": verdict.change_method,
            "needs_trust": False,
            "trust_hint": "",
            "url": url,
        }

    if v == "limited":
        if not verdict.reachable:
            # Monitorable, but the host must be trusted first.
            return {
                "can_watch": False,
                "status": "blocked",
                "headline": "Not reachable yet — add it to trusted sites first",
                "detail": (
                    "Add this site to your trusted list and Lighthouse can "
                    "start watching it."
                ),
                "change_method": verdict.change_method,
                "needs_trust": True,
                "trust_hint": verdict.trust_add_hint,
                "url": url,
            }
        return {
            "can_watch": True,
            "status": "limited",
            "headline": "We can watch it, but it's heavier (needs a browser to read it fully)",
            "detail": (
                "This page loads its content with scripts, so reading it takes "
                "more work — but Lighthouse can still track changes."
            ),
            "change_method": verdict.change_method,
            "needs_trust": False,
            "trust_hint": "",
            "url": url,
        }

    # blocked
    if not verdict.robots_ok:
        headline = "This site doesn't allow automated reading"
        detail = (
            "The site's rules (robots.txt) ask tools not to read it "
            "automatically, so Lighthouse won't watch it."
        )
    else:
        headline = "There's nothing readable to watch on this page"
        detail = (
            "Lighthouse couldn't find readable text or a feed here — the page "
            "may be empty, paywalled, or fully script-rendered."
        )
    return {
        "can_watch": False,
        "status": "blocked",
        "headline": headline,
        "detail": detail,
        "change_method": verdict.change_method,
        "needs_trust": False,
        "trust_hint": "",
        "url": url,
    }


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
        if body.selected_skills:
            meta["selected_skills"] = body.selected_skills
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

    # ============================ WATCH v2 ============================

    @app.post("/api/watch/verify", tags=["watch"])
    def watch_verify(body: WatchVerifyBody) -> dict[str, Any]:
        """Pre-flight a page the user wants to watch — plain-language answer.

        Runs ONE guarded fetch (the URL's own host is permitted, like an
        explicit user-typed ingest) and the scrapability check, then translates
        the internal verdict into words a non-technical user can act on. The
        fetch goes through ``_watch_fetch`` so tests monkeypatch it offline.
        """
        from ..governor.egress_proxy import DEFAULT_ALLOWED_DOMAINS, extract_host
        from ..net import EgressBlocked
        from ..sources.scrapability import FetchResult, verify_scrapable

        url = (body.url or "").strip()
        if not url:
            raise HTTPException(422, "url is required")

        def _adapt(resp: Any) -> FetchResult:
            headers = dict(getattr(resp, "headers", {}) or {})
            return FetchResult(
                status=getattr(resp, "status_code", 200),
                headers=headers,
                body=getattr(resp, "content", b"") or b"",
                content_type=headers.get("content-type"),
            )

        host = extract_host(url)

        def fetch(target: str) -> FetchResult:
            return _adapt(_watch_fetch(target))

        # Run the guarded fetch up front so a true egress block (host not
        # trusted) is caught *here* and surfaced as a plain-language trust
        # prompt — scrapability swallows fetch errors into its verdict, so we
        # must distinguish "not trusted" before handing off.
        try:
            fetch(url)
        except EgressBlocked:
            return {
                "can_watch": False,
                "status": "blocked",
                "headline": "Not reachable yet — add it to trusted sites first",
                "detail": (
                    "This site isn't on your trusted list yet, so Lighthouse "
                    "won't reach out to it automatically. Add it to trusted "
                    "sites and try again."
                ),
                "change_method": "diff",
                "needs_trust": True,
                "trust_hint": host,
                "url": url,
            }

        # Pass the DEFAULT allowlist (NOT host-augmented) so the verdict's
        # ``reachable`` reflects whether the user has actually trusted this host
        # — that drives the "add it to trusted sites first" prompt for a
        # not-yet-trusted host. The fetch above already permitted the host.
        verdict = verify_scrapable(
            url, fetch=fetch, allowlist=DEFAULT_ALLOWED_DOMAINS
        )
        return _plain_language_verdict(url, verdict)

    @app.post("/api/watch/web", tags=["watch"])
    def watch_web_create(body: WatchWebBody) -> dict[str, Any]:
        """Register a page to watch. Defaults: any change, every 60 minutes."""
        from ..modes.web_monitor_store import create_web_monitor

        url = (body.url or "").strip()
        if not url:
            raise HTTPException(422, "url is required")
        cadence_minutes = body.cadence_minutes if body.cadence_minutes else 60
        if cadence_minutes <= 0:
            cadence_minutes = 60
        monitor = create_web_monitor(
            paths.state_db,
            url=url,
            name=body.name,
            criteria=body.criteria or {"kind": "any_change"},
            cadence_seconds=cadence_minutes * 60,
            now=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        return monitor

    @app.get("/api/watch/web", tags=["watch"])
    def watch_web_list() -> dict[str, Any]:
        from ..modes.web_monitor_store import list_web_monitors
        return {"monitors": list_web_monitors(paths.state_db)}

    @app.delete("/api/watch/web/{monitor_id}", tags=["watch"])
    def watch_web_delete(monitor_id: str) -> dict[str, Any]:
        from ..modes.web_monitor_store import delete_web_monitor
        if not delete_web_monitor(paths.state_db, monitor_id):
            raise HTTPException(404, f"monitor {monitor_id} not found")
        return {"deleted": monitor_id}

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

    @app.delete("/api/secrets/{key_name}", tags=["settings"])
    def delete_secret(key_name: str) -> dict[str, Any]:
        from ..secrets import SecretStore
        found = SecretStore(paths.data_dir).delete(key_name)
        if not found:
            raise HTTPException(404, f"secret {key_name!r} not found")
        return {"key": key_name, "deleted": True}

    # ====================== SOURCE KEY CATALOGUE ===================
    # Hard-coded list of auth-requiring sources with their env-var key name and
    # a help URL where the user can obtain a free key.  The "configured" flag is
    # derived from SecretStore.list() — the value is NEVER returned.

    _SOURCE_KEY_CATALOGUE: list[dict[str, str]] = [
        {
            "source_id": "fred",
            "label": "FRED (Federal Reserve Economic Data)",
            "key_name": "FRED_API_KEY",
            "help_url": "https://fred.stlouisfed.org/docs/api/api_key.html",
        },
        {
            "source_id": "bea",
            "label": "BEA (Bureau of Economic Analysis)",
            "key_name": "BEA_API_KEY",
            "help_url": "https://apps.bea.gov/API/signup/",
        },
        {
            "source_id": "bls",
            "label": "BLS (Bureau of Labor Statistics)",
            "key_name": "BLS_API_KEY",
            "help_url": "https://data.bls.gov/registrationEngine/",
        },
        {
            "source_id": "census",
            "label": "Census Bureau",
            "key_name": "CENSUS_API_KEY",
            "help_url": "https://api.census.gov/data/key_signup.html",
        },
        {
            "source_id": "congress_gov",
            "label": "Congress.gov",
            "key_name": "CONGRESS_GOV_API_KEY",
            "help_url": "https://api.congress.gov/sign-up/",
        },
        {
            "source_id": "govinfo",
            "label": "GovInfo (GPO)",
            "key_name": "GOVINFO_API_KEY",
            "help_url": "https://api.govinfo.gov/docs/",
        },
        {
            "source_id": "courtlistener",
            "label": "CourtListener (Free Law Project)",
            "key_name": "COURTLISTENER_API_KEY",
            "help_url": "https://www.courtlistener.com/sign-in/",
        },
        {
            "source_id": "semantic_scholar",
            "label": "Semantic Scholar",
            "key_name": "SEMANTIC_SCHOLAR_API_KEY",
            "help_url": "https://www.semanticscholar.org/product/api",
        },
        {
            "source_id": "regulations_gov",
            "label": "Regulations.gov",
            "key_name": "REGULATIONS_GOV_API_KEY",
            "help_url": "https://open.gsa.gov/api/regulationsgov/",
        },
        {
            "source_id": "guardian",
            "label": "The Guardian",
            "key_name": "GUARDIAN_API_KEY",
            "help_url": "https://open-platform.theguardian.com/access/",
        },
    ]

    @app.get("/api/sources/keys", tags=["settings"])
    def list_source_keys() -> dict[str, Any]:
        """List auth-requiring sources with configured status (value never returned).

        ``configured`` is True when the key is present in either the OS keychain
        or the TOML fallback file.  The value is never returned.
        """
        from ..secrets import SecretStore
        store = SecretStore(paths.data_dir)
        sources = []
        for entry in _SOURCE_KEY_CATALOGUE:
            configured = store.get(entry["key_name"]) is not None
            sources.append({
                "source_id": entry["source_id"],
                "label": entry["label"],
                "key_name": entry["key_name"],
                "configured": configured,
                "help_url": entry["help_url"],
            })
        return {"sources": sources}

    # ======================= STEERABILITY ==========================
    # Persisted in a small JSON file beside sandbox_config.json so the gateway
    # can be reconstructed with the same locked/seed/temperature/top_p settings
    # on restart.  No gateway module is imported or mutated here.

    _steerability_path = paths.data_dir / "steerability.json"

    def _load_steerability() -> dict[str, Any]:
        try:
            return json.loads(_steerability_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"locked": False, "seed": None, "temperature": None, "top_p": None}

    def _save_steerability(data: dict[str, Any]) -> None:
        _steerability_path.parent.mkdir(parents=True, exist_ok=True)
        _steerability_path.write_text(json.dumps(data), encoding="utf-8")

    @app.get("/api/steerability", tags=["settings"])
    def get_steerability() -> dict[str, Any]:
        return _load_steerability()

    @app.put("/api/steerability", tags=["settings"])
    def put_steerability(body: SteerabilityPut) -> dict[str, Any]:
        if body.temperature is not None and not (0.0 <= body.temperature <= 2.0):
            raise HTTPException(422, "temperature must be between 0.0 and 2.0")
        if body.top_p is not None and not (0.0 <= body.top_p <= 1.0):
            raise HTTPException(422, "top_p must be between 0.0 and 1.0")
        data: dict[str, Any] = {
            "locked": body.locked,
            "seed": body.seed,
            "temperature": body.temperature,
            "top_p": body.top_p,
        }
        _save_steerability(data)
        return data

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

    @app.get("/api/classify", tags=["research"])
    def classify(q: str) -> dict[str, Any]:
        """Classify a question (deterministic, offline) and suggest a depth tier.

        Powers the wizard's 'Auto' depth default so routine work needs no
        decision. Never calls an LLM here (framing runs with gateway=None)."""
        from ..framing.pipeline import run_framing
        from ..modes.depth import auto_tier
        try:
            framed = run_framing(q)
            qtype = framed.question_type.value
            subs = list(framed.load_bearing or framed.sub_questions)
        except Exception:
            qtype, subs = "exploratory_survey", []
        return {"question_type": qtype, "suggested_tier": auto_tier(qtype),
                "sub_questions": subs}

    # ============================ SOURCES ==========================

    @app.get("/api/sources", tags=["research"])
    def list_sources() -> dict[str, Any]:
        """The skill catalog for the source picker (Zone K).

        Each entry is ``SkillManifest.as_dict()`` so the UI can render a
        categorized checkbox list (category, name, description, tier, grade,
        community flag, enabled_by_default). Tolerates an empty library."""
        from ..skills.registry import all_skills
        try:
            sources = [m.as_dict() for m in all_skills()]
        except Exception:
            sources = []
        return {"sources": sources}

    @app.get("/api/sources/health", tags=["research"])
    def sources_health() -> dict[str, Any]:
        """Per-source readiness in plain language.

        For each skill in the catalog, reports one of three statuses:

        * ``"ready"``      — reachable (all declared domains on the platform
                             allowlist) and no API key required, or the key
                             is already configured.
        * ``"needs_key"``  — this source needs a free API key and none has
                             been saved yet.
        * ``"needs_trust"``— at least one of the source's declared domains is
                             not on the platform allowlist, so Lighthouse
                             won't reach it until the user adds it via
                             Settings → Sources & trust.

        The ``summary`` field rolls up the per-source counts.  Secrets are
        never returned — only a boolean ``configured`` flag is used internally.
        """
        from ..governor.egress_proxy import DEFAULT_ALLOWED_DOMAINS
        from ..secrets import SecretStore
        from ..skills.registry import all_skills

        # Build a quick lookup: source_id → key_name from the key catalogue.
        key_required: dict[str, str] = {
            entry["source_id"]: entry["key_name"]
            for entry in _SOURCE_KEY_CATALOGUE
        }

        store = SecretStore(paths.data_dir)
        configured_keys: frozenset[str] = frozenset(store.list())

        def _domain_trusted(domain: str) -> bool:
            """True when domain (or a parent) is on the platform allowlist."""
            d = domain.lower().rstrip(".")
            if d in DEFAULT_ALLOWED_DOMAINS:
                return True
            return any(d.endswith("." + allowed) for allowed in DEFAULT_ALLOWED_DOMAINS)

        result: list[dict[str, Any]] = []
        try:
            manifests = all_skills()
        except Exception:
            manifests = []

        for m in manifests:
            # 1. Check domain reachability.
            domains = list(m.allowed_domains)
            untrusted = [d for d in domains if not _domain_trusted(d)]
            if untrusted:
                result.append({
                    "id": m.id,
                    "name": m.name,
                    "category": m.category,
                    "tier": m.tier,
                    "status": "needs_trust",
                    "reason": (
                        f"The domain{'s' if len(untrusted) > 1 else ''} "
                        f"{', '.join(untrusted)} "
                        f"{'are' if len(untrusted) > 1 else 'is'} not on "
                        "the trusted list yet. Add it in Settings → "
                        "Sources & trust, then Lighthouse can reach it."
                    ),
                })
                continue

            # 2. Check key requirement.
            key_name = key_required.get(m.id)
            if key_name and key_name not in configured_keys:
                result.append({
                    "id": m.id,
                    "name": m.name,
                    "category": m.category,
                    "tier": m.tier,
                    "status": "needs_key",
                    "reason": (
                        f"{m.name} works without a key at a lower rate limit. "
                        "Add your free API key in Settings → Connect your data "
                        "sources to unlock higher limits."
                    ),
                })
                continue

            # 3. Ready.
            result.append({
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "tier": m.tier,
                "status": "ready",
                "reason": "",
            })

        ready = sum(1 for s in result if s["status"] == "ready")
        needs_key = sum(1 for s in result if s["status"] == "needs_key")
        needs_trust = sum(1 for s in result if s["status"] == "needs_trust")
        return {
            "sources": result,
            "summary": {
                "ready": ready,
                "needs_key": needs_key,
                "needs_trust": needs_trust,
                "total": len(result),
            },
        }

    @app.get("/api/recommend-sources", tags=["research"])
    def recommend_sources(q: str, mode: str = "investigate",
                          depth: str | None = None) -> dict[str, Any]:
        """Mode-aware ranked source suggestions for the picker (Zone K).

        Offline-safe and deterministic — the recommender frames the question
        with gateway=None. If the recommender raises or the library is empty we
        return an empty list (200, never 500)."""
        from ..skills.recommender import recommend
        try:
            recs = recommend(q, mode, depth)
        except Exception:
            recs = []
        return {"recommended": [
            {"skill_id": r.skill_id, "score": r.score,
             "reason": r.reason, "role": r.role}
            for r in recs
        ]}

    # =========================== SANDBOX ===========================
    # The secured two-zone data store (SB3): user uploads + LLM workspace, every
    # byte broker-scanned on entry, user-configurable size, LRU eviction + pin.

    _MAX_UPLOAD_BYTES = 64 * 1024 * 1024  # hard request cap (memory safety)
    _sandbox_config_path = paths.data_dir / "sandbox_config.json"

    def _sandbox_max_bytes() -> int | None:
        from ..sandbox.store import DEFAULT_MAX_BYTES
        try:
            cfg = json.loads(_sandbox_config_path.read_text(encoding="utf-8"))
            val = cfg.get("max_bytes", DEFAULT_MAX_BYTES)
            return None if val is None else int(val)
        except (OSError, ValueError):
            return DEFAULT_MAX_BYTES

    def _sandbox_store():
        from ..sandbox.store import SandboxStore
        return SandboxStore(paths.data_dir, max_bytes=_sandbox_max_bytes())

    def _sandbox_broker():
        from ..sandbox.broker import build_default_broker
        return build_default_broker(paths.data_dir)

    @app.get("/api/sandbox", tags=["sandbox"])
    def sandbox_contents() -> dict[str, Any]:
        store = _sandbox_store()
        return {
            "items": [i.as_dict() for i in store.list()],
            "usage": store.usage(),
            "breakdown": store.breakdown(),
        }

    @app.post("/api/sandbox/upload", tags=["sandbox"])
    def sandbox_upload(body: SandboxUpload) -> dict[str, Any]:
        try:
            payload = base64.b64decode(body.content_base64, validate=True)
        except Exception as exc:
            raise HTTPException(400, f"invalid base64 content: {exc}") from exc
        if len(payload) > _MAX_UPLOAD_BYTES:
            raise HTTPException(413, "upload exceeds the per-file size cap")
        item = _sandbox_store().add(
            payload, zone="uploads", filename=body.filename,
            content_type=body.content_type, source="user",
            broker=_sandbox_broker(), now=datetime.now(UTC).isoformat(),
        )
        if item is None:
            # Broker REJECTed the bytes — never stored. Surface why.
            raise HTTPException(422, "file rejected by the sandbox security scan")
        return item.as_dict()

    @app.delete("/api/sandbox/{item_id}", tags=["sandbox"])
    def sandbox_delete(item_id: str) -> dict[str, Any]:
        ok = _sandbox_store().remove(item_id)
        if not ok:
            raise HTTPException(404, "no such sandbox item")
        return {"id": item_id, "removed": True}

    @app.post("/api/sandbox/{item_id}/pin", tags=["sandbox"])
    def sandbox_pin(item_id: str, body: PinBody) -> dict[str, Any]:
        store = _sandbox_store()
        if store.stat(item_id) is None:
            raise HTTPException(404, "no such sandbox item")
        store.pin(item_id, body.pinned)
        return {"id": item_id, "pinned": body.pinned}

    @app.get("/api/sandbox/config", tags=["sandbox"])
    def sandbox_config_get() -> dict[str, Any]:
        return {"max_bytes": _sandbox_max_bytes()}

    @app.api_route("/api/sandbox/config", methods=["PUT", "PATCH"], tags=["sandbox"])
    def sandbox_config_set(body: SandboxConfig) -> dict[str, Any]:
        if body.max_bytes is not None and body.max_bytes < 0:
            raise HTTPException(400, "max_bytes must be >= 0 or null")
        _sandbox_config_path.parent.mkdir(parents=True, exist_ok=True)
        _sandbox_config_path.write_text(
            json.dumps({"max_bytes": body.max_bytes}), encoding="utf-8")
        store = _sandbox_store()
        store.enforce_quota()  # apply the new cap immediately
        return {"max_bytes": body.max_bytes, "usage": store.usage()}

    # =========================== CONTROL ===========================
    # Global pause/resume so the user can reclaim their machine. Writes the same
    # supervisor_state.status the CLI `pause`/`resume` use; every 24/7 loop reads
    # is_paused() each tick and skips its work while paused.

    @app.get("/api/control", tags=["control"])
    def control_status() -> dict[str, Any]:
        from ..supervisor import is_paused, runtime_status
        return {"status": runtime_status(paths), "paused": is_paused(paths)}

    @app.post("/api/pause", tags=["control"])
    def control_pause(body: PauseBody | None = None) -> dict[str, Any]:
        from ..supervisor import set_runtime_status
        hard = bool(body.hard) if body is not None else False
        status = set_runtime_status(paths, "paused_hard" if hard else "paused_soft")
        bus.publish("control.status", {"status": status, "paused": True})
        return {"status": status, "paused": True}

    @app.post("/api/resume", tags=["control"])
    def control_resume() -> dict[str, Any]:
        from ..supervisor import set_runtime_status
        status = set_runtime_status(paths, "running")
        bus.publish("control.status", {"status": status, "paused": False})
        return {"status": status, "paused": False}

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

    # ============================ GRAPH ============================

    @app.get("/api/graph/draft/{draft_id}", tags=["library"])
    def get_draft_graph(draft_id: str) -> dict[str, Any]:
        """Return the entity-connection graph for a research artifact.

        Harvests readable text from the draft's ``body_json`` (walking all
        known mode shapes: investigate sections, survey rows, reconstruct
        events, decide matrix cells, adjudicate verdict, ask transcript turns),
        plus a stripped ``body_html`` fallback.  Each logical section/turn/row
        becomes one chunk so co-occurrence is meaningful.

        Response shape::

            {
              "entities": [{"label": str, "weight": int}, ...],  # top 25
              "graph": {
                "nodes": [{"id": str, "label": str, "weight": int}, ...],
                "edges": [{"source": str, "target": str, "weight": int}, ...],
              }
            }

        Empty/short artifacts return ``{"entities": [], "graph": {"nodes": [],
        "edges": []}}`` (200).  Draft not found → 404.
        """
        import re as _re

        from ..rag.graph import build_corpus_graph

        conn = open_db(paths.state_db)
        try:
            rows = _rows(conn, "SELECT * FROM drafts WHERE id=?", (draft_id,))
        finally:
            conn.close()
        if not rows:
            raise HTTPException(404, f"draft {draft_id} not found")
        row = rows[0]

        # ---- harvest text chunks from body_json -------------------------
        body_json: dict[str, Any] = {}
        if row.get("body_json"):
            try:
                body_json = json.loads(row["body_json"])
            except (TypeError, ValueError):
                body_json = {}

        _MAX_CHUNKS = 200      # cap total chunks harvested
        _MIN_CHUNK_LEN = 30   # skip trivially short chunks

        chunks: list[dict[str, str]] = []

        def _add(chunk_id: str, text: str) -> None:
            if len(chunks) >= _MAX_CHUNKS:
                return
            t = (text or "").strip()
            if len(t) >= _MIN_CHUNK_LEN:
                chunks.append({"id": chunk_id, "text": t})

        # investigate/report: sections[{title, sub_question, body, citations}]
        sections = body_json.get("sections") if isinstance(body_json, dict) else None
        if isinstance(sections, list):
            for i, s in enumerate(sections):
                if not isinstance(s, dict):
                    continue
                combined = " ".join(
                    filter(None, [s.get("title", ""), s.get("sub_question", ""),
                                  s.get("body", "")])
                )
                _add(f"section:{i}", combined)

        # survey/table: rows[{doc_id, title, cells[{attribute, value}]}]
        table_rows = body_json.get("rows") if isinstance(body_json, dict) else None
        if isinstance(table_rows, list):
            for i, r in enumerate(table_rows):
                if not isinstance(r, dict):
                    continue
                cells_text = " ".join(
                    str(c.get("value", ""))
                    for c in (r.get("cells") or [])
                    if isinstance(c, dict)
                )
                combined = " ".join(
                    filter(None, [r.get("title", ""), r.get("doc_id", ""), cells_text])
                )
                _add(f"row:{i}", combined)

        # reconstruct/timeline: events[{date, action, sources, certainty}]
        events = body_json.get("events") if isinstance(body_json, dict) else None
        if isinstance(events, list):
            for i, e in enumerate(events):
                if not isinstance(e, dict):
                    continue
                combined = " ".join(
                    filter(None, [e.get("date", ""), e.get("action", ""),
                                  e.get("description", ""),
                                  e.get("significance", "")])
                )
                _add(f"event:{i}", combined)

        # decide/matrix: cells[{option, criterion, rationale}] + summary/finding
        matrix_cells = body_json.get("cells") if isinstance(body_json, dict) else None
        if isinstance(matrix_cells, list):
            # Group by option for better co-occurrence.
            by_option: dict[str, list[str]] = {}
            for c in matrix_cells:
                if not isinstance(c, dict):
                    continue
                opt = c.get("option", "option")
                by_option.setdefault(opt, [])
                for f in ("rationale", "notes", "criterion"):
                    v = c.get(f, "")
                    if v:
                        by_option[opt].append(str(v))
            for opt, parts in by_option.items():
                _add(f"option:{opt}", " ".join(parts))

        # adjudicate/verdict: finding, steelman, critique, verdict, perspectives
        verdict_fields = ("finding", "steelman", "critique", "summary",
                          "verdict", "recommendation")
        if isinstance(body_json, dict):
            for vf in verdict_fields:
                v = body_json.get(vf)
                if isinstance(v, str) and v.strip():
                    _add(f"verdict:{vf}", v)
                elif isinstance(v, list):
                    for j, item in enumerate(v):
                        t2 = item.get("body", "") if isinstance(item, dict) else str(item)
                        _add(f"verdict:{vf}:{j}", t2)

        # ask/transcript: turns[{role, text, citations}]
        turns = body_json.get("turns") if isinstance(body_json, dict) else None
        if isinstance(turns, list):
            for i, t in enumerate(turns):
                if not isinstance(t, dict):
                    continue
                _add(f"turn:{i}", t.get("text", ""))

        # perspectives (adjudicate deep mode): perspectives[{label, argument}]
        perspectives = body_json.get("perspectives") if isinstance(body_json, dict) else None
        if isinstance(perspectives, list):
            for i, p in enumerate(perspectives):
                if not isinstance(p, dict):
                    continue
                combined = " ".join(
                    filter(None, [p.get("label", ""), p.get("argument", ""),
                                  p.get("body", "")])
                )
                _add(f"perspective:{i}", combined)

        # ---- body_html fallback -----------------------------------------
        if not chunks:
            html = row.get("body_html") or ""
            plain = _re.sub(r"<[^>]+>", " ", html)
            plain = _re.sub(r"\s+", " ", plain).strip()
            # Split into ~300-char chunks so co-occurrence is local.
            words = plain.split()
            chunk_size = 60  # words per pseudo-section
            for i in range(0, min(len(words), _MAX_CHUNKS * chunk_size), chunk_size):
                _add(f"html:{i}", " ".join(words[i:i + chunk_size]))

        # ---- build graph ------------------------------------------------
        _EMPTY: dict[str, Any] = {"entities": [], "graph": {"nodes": [], "edges": []}}
        if not chunks:
            return _EMPTY

        g = build_corpus_graph(chunks)
        if g.node_count == 0:
            return _EMPTY

        top_entities = g.entities()[:25]
        top_labels = [lbl for lbl, _ in top_entities]
        # Use the top entities (or all if fewer than 25) as seeds for subgraph.
        graph_data = g.subgraph(top_labels, hops=1, max_nodes=40)

        return {
            "entities": [{"label": lbl, "weight": w} for lbl, w in top_entities],
            "graph": graph_data,
        }


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
