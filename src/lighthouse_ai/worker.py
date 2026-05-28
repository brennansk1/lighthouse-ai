"""Job worker — executes queued research jobs created from the dashboard/API.

Creating an agent in the web UI inserts a ``jobs`` row with status ``queued``;
this worker is what actually runs it: it claims the oldest queued job, marks it
``running``, runs the :class:`~lighthouse_ai.pipeline.ResearchPipeline` for the
job's assigned mode, and lands it in ``review`` with a staged draft (or
``error`` on failure). Without this, a created job would sit queued forever.

Design:
- Single sequential worker (one job at a time) — safe and predictable for a
  local single-user instance; the Governor + SchedulerGate still meter/throttle
  the LLM calls inside the pipeline.
- Honors supervisor pause (``paused_soft``/``paused_hard``): no new job is
  claimed while paused.
- The job's status lifecycle is owned here: queued → running → review | error.
  (Approve/reject from the dashboard move review → done/rejected.)
- Best-effort and crash-safe: any pipeline exception is captured onto the job
  as ``error`` with the message, never takes down the supervisor loop.
"""

from __future__ import annotations

import json
import threading
import time

import structlog

from .paths import Paths
from .persistence import open_db

log = structlog.get_logger(__name__)

_PAUSED = {"paused_soft", "paused_hard"}


def _is_paused(state_db) -> bool:
    try:
        conn = open_db(state_db)
        try:
            row = conn.execute(
                "SELECT status FROM supervisor_state WHERE id = 1"
            ).fetchone()
        finally:
            conn.close()
        return bool(row) and row[0] in _PAUSED
    except Exception:
        return False


def _pipeline_mode(mode_label: str) -> str:
    """Map a UI/CLI research-mode label to a PipelineConfig mode.

    Deep-Dive and Monitor both run the full TTD-DR deep-dive pipeline for a
    one-shot job; QUC / Quick map to the quick-answer path.
    """
    m = (mode_label or "").lower()
    if "quc" in m or "quick" in m:
        return "quc"
    return "deep-dive"


def claim_next_job(state_db) -> dict | None:
    """Atomically move the oldest queued job to 'running' and return its info.

    Returns ``None`` when there is nothing to run. The UPDATE ... WHERE status=
    'queued' guard makes the claim safe even if two workers ever race.
    """
    conn = open_db(state_db)
    try:
        row = conn.execute(
            "SELECT id, mode, metadata_json FROM jobs WHERE status = 'queued' "
            "ORDER BY created_at, id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        job_id, mode, meta_json = row
        cur = conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = datetime('now') "
            "WHERE id = ? AND status = 'queued'", (job_id,))
        if cur.rowcount == 0:
            return None  # someone else claimed it
        meta = {}
        try:
            meta = json.loads(meta_json) if meta_json else {}
        except (ValueError, TypeError):
            meta = {}
        # mark progress started
        meta["eta"] = "running"
        meta["progress"] = meta.get("progress", 0.0)
        conn.execute("UPDATE jobs SET metadata_json = ? WHERE id = ?",
                     (json.dumps(meta), job_id))
    finally:
        conn.close()
    return {"id": job_id, "mode": mode, "topic": meta.get("topic", ""),
            "depth": meta.get("depth", "Standard"), "metadata": meta}


def _set_job(state_db, job_id: str, status: str, *, meta_updates: dict | None = None) -> None:
    conn = open_db(state_db)
    try:
        if meta_updates:
            row = conn.execute("SELECT metadata_json FROM jobs WHERE id = ?",
                               (job_id,)).fetchone()
            meta = {}
            try:
                meta = json.loads(row[0]) if row and row[0] else {}
            except (ValueError, TypeError):
                meta = {}
            meta.update(meta_updates)
            conn.execute(
                "UPDATE jobs SET status = ?, metadata_json = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (status, json.dumps(meta), job_id))
        else:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (status, job_id))
    finally:
        conn.close()


def run_job(paths: Paths, job: dict, *, bus=None, offline: bool = False) -> str:
    """Run one claimed job through the research pipeline. Returns final status.

    Never raises — failures are recorded on the job as ``error``.
    """
    from .cli import _load_config_section  # reuse the [learning] loader
    from .pipeline import PipelineConfig, ResearchPipeline

    job_id = job["id"]
    topic = (job.get("topic") or "").strip()
    if not topic:
        _set_job(paths.state_db, job_id, "error",
                 meta_updates={"error": "job has no topic/question", "eta": "—"})
        if bus:
            bus.publish("job.status", {"id": job_id, "status": "error"})
        return "error"

    mode = _pipeline_mode(job.get("mode", ""))
    lrn = _load_config_section("learning")
    try:
        cfg = PipelineConfig(
            offline=offline, mode=mode,
            learning_enabled=bool(lrn.get("enabled", True)),
            learning_distill_min_coverage=float(lrn.get("distill_min_coverage", 0.75)),
            learning_max_skills=int(lrn.get("max_skills_injected", 3)))
        pipe = ResearchPipeline(paths, config=cfg)
        result = pipe.research(topic, job_id=job_id)
        # Pipeline staged a draft; the job is now awaiting review.
        _set_job(paths.state_db, job_id, "review",
                 meta_updates={"progress": 1.0, "eta": "done",
                               "draft_id": result.draft_id})
        if bus:
            bus.publish("job.status", {"id": job_id, "status": "review"})
            bus.publish("draft.staged", {"id": result.draft_id, "title": topic[:80]})
        log.info("worker.job_done", job_id=job_id, draft_id=result.draft_id, mode=mode)
        return "review"
    except Exception as exc:
        log.warning("worker.job_failed", job_id=job_id, error=str(exc))
        _set_job(paths.state_db, job_id, "error",
                 meta_updates={"error": str(exc)[:500], "eta": "—"})
        if bus:
            bus.publish("job.status", {"id": job_id, "status": "error"})
        return "error"


def process_once(paths: Paths, *, bus=None, offline: bool = False) -> bool:
    """Claim and run one queued job if any (and not paused). Returns True if it ran."""
    if _is_paused(paths.state_db):
        return False
    job = claim_next_job(paths.state_db)
    if job is None:
        return False
    if bus:
        bus.publish("job.status", {"id": job["id"], "status": "running"})
    run_job(paths, job, bus=bus, offline=offline)
    return True


def start_worker(paths: Paths, *, bus=None, interval_s: float = 3.0,
                 offline: bool = False) -> threading.Thread:
    """Start the daemon worker thread that drains the job queue."""
    def _loop() -> None:
        while True:
            try:
                ran = process_once(paths, bus=bus, offline=offline)
            except Exception as exc:
                log.warning("worker.loop_error", error=str(exc))
                ran = False
            # Poll faster when busy (more jobs likely queued), slower when idle.
            time.sleep(0.2 if ran else interval_s)

    thread = threading.Thread(target=_loop, daemon=True, name="job-worker")
    thread.start()
    log.info("worker.started", interval_s=interval_s)
    return thread
