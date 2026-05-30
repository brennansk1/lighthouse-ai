"""Per-job research progress trace (live + persisted).

A research job's coarse ``metadata_json.progress`` used to jump 0.0 → 1.0 with
nothing in between, and there was no per-step record of *what* the engine was
doing. :class:`ProgressEmitter` fixes both: every meaningful step in a run calls
``emit(phase, kind, label, pct, data)``, which

1. appends a row to the ``job_events`` table (monotonic per-job ``seq``),
2. publishes an SSE ``job.step`` event on the :class:`EventBus` (if wired), and
3. nudges the job's ``metadata_json.progress`` to ``pct / 100``.

The contract other zones build to (KEEP EXACT):

* SSE event ``job.step`` payload:
  ``{job_id, seq, phase, kind, label, pct, data}``
* ``phase`` ∈ ``framing|sources|retrieval|drafting|verification|synthesis|done``
* ``GET /api/jobs/{id}/trace`` →
  ``{job_id, status, pct, events:[{seq,ts,phase,kind,label,pct,data}, ...]}``

Everything here is **best-effort**: a progress failure must never crash a job.
The dispatcher runs the engine synchronously in a worker thread, so emitting
inline (and publishing via the bus's thread-safe ``call_soon_threadsafe`` hop)
is fine.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from .paths import Paths
from .persistence import open_db

_log = structlog.get_logger(__name__)

#: The ordered phase vocabulary. Other zones key off these exact strings.
PHASES = (
    "framing", "sources", "retrieval", "drafting",
    "verification", "synthesis", "done",
)


class ProgressEmitter:
    """Emit + persist a per-job progress trace. Best-effort, never raises.

    Construct one per job (``ProgressEmitter(job.id, paths, bus)``) and call
    :meth:`emit` at each step. ``bus`` is optional — without it, rows are still
    persisted and ``progress`` is still updated, just no live SSE fan-out.
    """

    def __init__(self, job_id: str, paths: Paths, bus: Any = None) -> None:
        self.job_id = job_id
        self.paths = paths
        self.bus = bus

    # ── core ────────────────────────────────────────────────────────────────

    def emit(self, phase: str, kind: str, label: str, pct: float,
             data: dict[str, Any] | None = None) -> None:
        """Record one progress step. Swallows every error (logs + continues)."""
        try:
            payload = data if isinstance(data, dict) else {}
            seq = self._insert_event(phase, kind, label, pct, payload)
            if seq is None:
                return
            self._update_progress(pct)
            if self.bus is not None:
                try:
                    self.bus.publish("job.step", {
                        "job_id": self.job_id,
                        "seq": seq,
                        "phase": phase,
                        "kind": kind,
                        "label": label,
                        "pct": pct,
                        "data": payload,
                    })
                except Exception as exc:  # pragma: no cover - defensive
                    _log.warning("progress.publish_failed",
                                 job_id=self.job_id, error=repr(exc))
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("progress.emit_failed", job_id=self.job_id,
                         error=repr(exc))

    def _insert_event(self, phase: str, kind: str, label: str, pct: float,
                      payload: dict[str, Any]) -> int | None:
        conn = open_db(self.paths.state_db)
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM job_events WHERE job_id = ?",
                (self.job_id,)).fetchone()
            seq = int(row[0]) + 1 if row else 1
            conn.execute(
                "INSERT INTO job_events "
                "(job_id, seq, ts, phase, kind, label, pct, payload_json) "
                "VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?)",
                (self.job_id, seq, phase, kind, label, float(pct),
                 json.dumps(payload)))
            return seq
        finally:
            conn.close()

    def _update_progress(self, pct: float) -> None:
        """Set the job's ``metadata_json.progress`` to ``pct / 100`` in place."""
        try:
            frac = max(0.0, min(1.0, float(pct) / 100.0))
        except (TypeError, ValueError):
            return
        conn = open_db(self.paths.state_db)
        try:
            row = conn.execute(
                "SELECT metadata_json FROM jobs WHERE id = ?",
                (self.job_id,)).fetchone()
            if row is None:
                return
            try:
                meta = json.loads(row[0]) if row[0] else {}
            except (TypeError, ValueError):
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            meta["progress"] = frac
            conn.execute(
                "UPDATE jobs SET metadata_json = ?, updated_at = datetime('now') "
                "WHERE id = ?", (json.dumps(meta), self.job_id))
        finally:
            conn.close()

    # ── engine-callback adapters ────────────────────────────────────────────
    #
    # These translate the (stable) engine callback argument shapes into emit()
    # calls. They are passed directly to ``run_deepdive(on_round=...)`` and
    # ``run_exhaustive(on_node=..., on_checkpoint=...)`` — the engines are NOT
    # modified. Every adapter is best-effort: a bad arg shape is swallowed.

    def round_cb(self, round_idx: int, sections: Any) -> None:
        """Deep-dive ``on_round(round_idx, sections)``.

        Emits a ``drafting/round`` step plus one ``drafting/section_drafted``
        per grounded (cited) load-bearing section. ``pct`` ramps across the
        drafting band (35→70) by round so the bar advances visibly.
        """
        try:
            secs = list(sections or [])
            grounded = [s for s in secs
                        if getattr(s, "citations", None)]
            pct = min(70.0, 35.0 + round_idx * 10.0)
            self.emit("drafting", "round",
                      f"Drafting round {round_idx}", pct,
                      {"round": round_idx, "sections": len(secs),
                       "grounded": len(grounded)})
            for s in grounded:
                title = getattr(s, "title", "") or getattr(s, "sub_question", "")
                self.emit("drafting", "section_drafted", str(title), pct, {
                    "title": getattr(s, "title", ""),
                    "sub_question": getattr(s, "sub_question", ""),
                    "is_load_bearing": bool(getattr(s, "is_load_bearing", False)),
                    "citations": len(getattr(s, "citations", []) or []),
                })
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("progress.round_cb_failed", job_id=self.job_id,
                         error=repr(exc))

    def node_cb(self, node: Any, done: int, total: int) -> None:
        """Exhaustive ``on_node(node, done, total)``.

        Emits a ``retrieval/node`` step; ``pct`` tracks ``done/total`` mapped
        into the retrieval band (20→65)."""
        try:
            total = int(total) if total else 0
            frac = (int(done) / total) if total else 0.0
            pct = 20.0 + max(0.0, min(1.0, frac)) * 45.0
            question = str(getattr(node, "question", "") or "")
            self.emit("retrieval", "node", question[:120], pct, {
                "question": question,
                "depth": getattr(node, "depth", None),
                "status": getattr(node, "status", None),
                "voi": getattr(node, "voi", None),
                "children": len(getattr(node, "children", []) or []),
                "done": int(done), "total": total,
            })
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("progress.node_cb_failed", job_id=self.job_id,
                         error=repr(exc))

    def checkpoint_cb(self, tree_state: Any) -> None:
        """Exhaustive ``on_checkpoint(TreeState)``.

        A lightweight ``retrieval/checkpoint`` heartbeat carrying the running
        counters. Does not move ``pct`` past the node band."""
        try:
            done = int(getattr(tree_state, "done", 0) or 0)
            pending = len(getattr(tree_state, "pending", []) or [])
            total = done + pending
            frac = (done / total) if total else 0.0
            pct = 20.0 + max(0.0, min(1.0, frac)) * 45.0
            self.emit("retrieval", "checkpoint",
                      f"Checkpoint: {done} researched", pct,
                      {"done": done, "pending": pending,
                       "truncated": bool(getattr(tree_state, "truncated", False))})
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("progress.checkpoint_cb_failed", job_id=self.job_id,
                         error=repr(exc))
