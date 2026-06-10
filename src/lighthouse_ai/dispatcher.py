"""Job dispatcher — claims queued jobs and runs the matching mode engine.

A *job* is a row in the ``jobs`` table created by ``POST /api/jobs``. The
dispatcher claims the oldest queued job atomically (``BEGIN IMMEDIATE``, mirror
of ``intents.claim_one``), resolves the mode registry to the engine callable,
builds the engine's inputs from the job's metadata, runs it, persists the
resulting typed artifact into ``drafts`` (status ``staged`` — awaiting review),
and audits the run. Status flows ``queued → running → review`` on success or
``→ failed`` on error.

RAM admission is inherited through ``Gateway.complete`` (the single
``ollama_slot`` seam) — the dispatcher adds no second queue. It is driven one
job per tick by the supervisor's dispatch loop, which is SchedulerGate-gated and
started only by ``serve(run=True)``.

Deterministic + offline by default: when ``gateway=None`` every wired engine
(watch / ask / investigate / survey / reconstruct / decide / adjudicate) runs
from heuristics, so the dispatcher is fully testable without an LLM.
"""

from __future__ import annotations

import dataclasses
import hashlib
import html as _html
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from .gateway import Gateway
from .governor.scheduler_gate import SchedulerGate
from .modes.registry import canonical, load_engine, resolve
from .paths import Paths
from .persistence import open_db

_log = structlog.get_logger(__name__)

#: Bumped when artifact body_json schemas change; recorded in every provenance
#: manifest so an artifact says which engine produced it (reproducibility).
ENGINE_VERSION = "1.0.0"

#: General Web fallback skill id (CRAG gap-filler — MODE_SKILL_INTEGRATION §5.2).
_GENERAL_WEB_ID = "general_web"

#: Private meta key the dispatcher uses to hand the per-job broker to the
#: adapters without changing their (stable) signatures. Stripped before persist.
_BROKER_META_KEY = "_broker"

#: Private meta key holding the raw skill Documents (for contradiction
#: detection). Stripped before persist alongside ``_BROKER_META_KEY``.
_SKILL_DOCS_META_KEY = "_skill_documents"

#: Private meta key handing the resolved :class:`Paths` to adapters that need
#: the data dir (Deep-tier checkpoint/resume). Stripped before persist.
_PATHS_META_KEY = "_paths"

#: Private meta key handing the per-job :class:`ProgressEmitter` to the
#: investigate adapters so they can wire the engine progress callbacks
#: (on_round / on_node / on_checkpoint). Stripped before persist.
_PROGRESS_META_KEY = "_progress"

#: Fixed epoch handed to ``contradiction.detect`` so detection is deterministic
#: and free of ``datetime.now()`` at import/runtime (the module forbids it).
_DETECTED_AT = datetime(2026, 1, 1, tzinfo=UTC)

#: Modes whose engines consume a multi-source corpus (``meta["documents"]``) and
#: therefore benefit from skill execution feeding documents into the hybrid.
_MULTISOURCE_MODES = frozenset(
    {"investigate", "survey", "reconstruct", "decide", "adjudicate"})


@dataclass(frozen=True)
class ClaimedJob:
    id: str
    mode: str
    meta: dict[str, Any]


def claim_one_job(state_db) -> ClaimedJob | None:
    """Atomically claim the oldest queued job, flipping it to ``running``.

    ``BEGIN IMMEDIATE`` takes the write lock before the read so two dispatch
    ticks cannot claim the same row. Returns None if the queue is empty.
    """
    conn = open_db(state_db)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT id, mode, metadata_json FROM jobs "
                "WHERE status = 'queued' ORDER BY created_at, id LIMIT 1"
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return None
            jid, mode, meta_json = row[0], row[1], row[2]
            conn.execute(
                "UPDATE jobs SET status = 'running', updated_at = datetime('now') "
                "WHERE id = ?", (jid,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    try:
        meta = json.loads(meta_json) if meta_json else {}
    except (TypeError, ValueError):
        meta = {}
    return ClaimedJob(id=jid, mode=mode, meta=meta)


def reap_stuck_jobs(state_db) -> list[str]:
    """Re-queue jobs left ``running`` by a previous (crashed) process.

    Called at startup before the dispatch loop begins, so an interrupted job is
    retried rather than stranded. Returns the ids that were re-queued.
    """
    conn = open_db(state_db)
    try:
        rows = conn.execute(
            "SELECT id FROM jobs WHERE status = 'running'").fetchall()
        ids = [r[0] for r in rows]
        if ids:
            conn.execute(
                "UPDATE jobs SET status = 'queued', updated_at = datetime('now') "
                "WHERE status = 'running'")
        return ids
    finally:
        conn.close()


def _set_status(state_db, job_id: str, status: str,
                meta: dict[str, Any] | None = None) -> None:
    conn = open_db(state_db)
    try:
        if meta is not None:
            conn.execute(
                "UPDATE jobs SET status = ?, metadata_json = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (status, json.dumps(meta), job_id))
        else:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = datetime('now') "
                "WHERE id = ?", (status, job_id))
    finally:
        conn.close()


# ── per-mode adapters ──────────────────────────────────────────────────────
#
# Each adapter turns a job's metadata into the keyword arguments its engine
# expects, then summarizes the returned report into (title, body_html,
# body_json, source_count) for the drafts row. Every one of the seven modes is
# wired here and runs offline-deterministically when ``gateway is None`` — the
# engines fall back to heuristic/stub behaviour, so the dispatcher is fully
# testable without an LLM. With a real gateway the same adapters build a hybrid
# corpus (pipeline factories) so the engines retrieve real evidence.


def _meta_documents(meta: dict) -> list[dict]:
    """Pull a list of ``{doc_id/id, title, text}`` dicts out of job metadata.

    The wizard does not (yet) attach documents, so this is normally empty;
    tests and real-backend callers may supply ``meta["documents"]`` directly.
    """
    docs = meta.get("documents")
    return list(docs) if isinstance(docs, list) else []


def _build_hybrid(meta: dict, *, gateway):
    """Build a populated ``HybridSearch`` from ``meta["documents"]``.

    Returns ``None`` when there are no documents to index (the engines accept
    ``hybrid=None`` and degrade to stubs). When a real gateway is wired we use
    the real backend factories; offline we force the in-memory + hash stubs so
    no model loads. Any failure degrades to ``None`` rather than raising — the
    dispatcher must never crash a job over corpus assembly.
    """
    docs = _meta_documents(meta)
    if not docs:
        return None
    try:
        from .pipeline import make_embedder, make_vector_store
        from .rag import BM25Index, Document, HybridSearch, chunk_document

        offline = gateway is None
        embedder, _en, _ew = make_embedder(offline=offline)
        store, _sn, _sw = make_vector_store(embedder.dim, offline=offline)
        hybrid = HybridSearch(store, embedder, BM25Index())
        chunks = []
        for i, d in enumerate(docs):
            doc_id = str(d.get("doc_id") or d.get("id") or f"doc{i}")
            text = str(d.get("text", ""))
            if not text.strip():
                continue
            chunks.extend(chunk_document(
                Document(id=doc_id, text=text,
                         metadata={"source": str(d.get("title", doc_id))})))
        if not chunks:
            return None
        hybrid.add(chunks)
        return hybrid
    except Exception:
        return None


def _build_broker(paths: Paths):
    """Best-effort default :class:`SandboxBroker` for skill fetches.

    Returns ``None`` on any failure so the dispatcher degrades to "no skills"
    rather than crashing a job over broker assembly."""
    try:
        from .sandbox.broker import build_default_broker
        return build_default_broker(paths.data_dir)
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("dispatcher.broker.build_failed", error=repr(exc))
        return None


# ── skill execution (Zone J — dispatcher pipeline skill run) ────────────────
#
# When a job carries ``meta["selected_skills"]`` (chosen in the source picker),
# the dispatcher executes each through the platform broker, aggregates the
# attributed Documents, and feeds them into the mode engine's hybrid corpus
# (MODE_SKILL_INTEGRATION §2.1). The mode engine never reads ``selected_skills``
# — it only consumes the corpus, which keeps the seven modes orthogonal. When no
# skills are selected this whole path is inert and behaviour is UNCHANGED.


def _selected_skill_ids(meta: dict) -> list[str]:
    """The skill ids chosen in the source picker, de-duped, order-preserved."""
    raw = meta.get("selected_skills") or []
    out: list[str] = []
    seen: set[str] = set()
    for sid in raw:
        sid = str(sid)
        if sid and sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _maybe_decide_skills(meta: dict, *, gateway) -> list[str]:
    """Decide per-option merge (§2.2): merge ``recommend`` picks per option into
    the selected set. Optional, guarded, offline-safe — any failure (or no
    options) leaves the explicitly selected ids unchanged.
    """
    selected = _selected_skill_ids(meta)
    options = meta.get("options") or []
    if not options:
        return selected
    try:
        from .skills.recommender import recommend

        topic = meta.get("topic", "") or ""
        merged: dict[str, float] = {sid: 1.0 for sid in selected}
        for opt in options:
            q = f"{topic} {opt}".strip()
            for rec in recommend(q, "decide", meta.get("depth"), gateway=gateway):
                merged[rec.skill_id] = max(merged.get(rec.skill_id, 0.0), rec.score)
        # Keep originally-selected ids first, then the merged picks by score.
        extra = sorted(
            (sid for sid in merged if sid not in selected),
            key=lambda s: merged[s], reverse=True)
        return selected + extra
    except Exception:
        return selected


def _run_selected_skills(meta: dict, *, gateway, broker,
                         max_results: int = 5) -> list:
    """Load + run each selected skill through the broker, aggregate ``.documents``.

    Returns a flat ``list[Document]`` (rag chunker Documents, already stamped
    with ``skill_id`` provenance by the runner). When the specialty skills all
    return thin/empty results, falls back to the ``general_web`` skill as a
    CRAG-style gap-filler (§5.2). Never raises — a missing/faulting skill is
    logged and skipped (``run_skill`` already swallows skill-side faults), so
    skill execution can never crash a job.
    """
    skill_ids = (_maybe_decide_skills(meta, gateway=gateway)
                 if str(meta.get("mode") or "") == "decide"
                 else _selected_skill_ids(meta))
    if not skill_ids:
        return []
    if broker is None:
        _log.warning("dispatcher.skills.no_broker", skills=skill_ids)
        return []

    from .skills import load_skill, run_skill

    question = meta.get("topic", "") or ""
    documents: list = []
    all_thin = True
    ran_general_web = False
    for sid in skill_ids:
        if sid == _GENERAL_WEB_ID:
            ran_general_web = True
        try:
            skill = load_skill(sid)
        except Exception as exc:  # SkillNotFound / SkillLoadError
            _log.warning("dispatcher.skills.load_failed", skill=sid, error=repr(exc))
            continue
        run = run_skill(skill, question, broker=broker, gateway=gateway,
                        max_results=max_results)
        if not run.ok:
            _log.warning("dispatcher.skills.run_error", skill=sid, error=run.error)
        if not run.thin:
            all_thin = False
        documents.extend(run.documents)

    # CRAG gap-filler: specialty skills came back empty → fall back to the
    # universal General Web skill (when available and not already run).
    if all_thin and not ran_general_web:
        try:
            gw = load_skill(_GENERAL_WEB_ID)
        except Exception:
            gw = None
        if gw is not None:
            _log.info("dispatcher.skills.gap_filler", reason="thin_specialty_results",
                      fallback=_GENERAL_WEB_ID)
            run = run_skill(gw, question, broker=broker, gateway=gateway,
                            max_results=max_results)
            documents.extend(run.documents)
    return documents


def _skill_docs_to_meta(documents: list) -> list[dict]:
    """Adapt skill ``Document`` objects to the ``meta["documents"]`` dict shape
    that :func:`_build_hybrid` and the corpus adapters expect."""
    out: list[dict] = []
    for d in documents:
        meta = getattr(d, "metadata", {}) or {}
        out.append({
            "doc_id": getattr(d, "id", None),
            "id": getattr(d, "id", None),
            "title": meta.get("title") or meta.get("source") or getattr(d, "id", ""),
            "text": getattr(d, "text", "") or "",
            "url": meta.get("url") or meta.get("source"),
            "source": meta.get("source"),
            "skill_id": meta.get("skill_id"),
        })
    return out


def _inject_skill_documents(meta: dict, *, gateway) -> list:
    """Run the job's selected skills and merge their documents into
    ``meta["documents"]`` (extending, not replacing, any caller-supplied docs).

    Returns the raw ``list[Document]`` from the skills (for downstream
    contradiction detection). Inert when no skills are selected — ``meta`` is
    left untouched and behaviour is UNCHANGED (back-compat).
    """
    if not _selected_skill_ids(meta) and not (
            str(meta.get("mode") or "") == "decide" and meta.get("options")):
        return []
    broker = meta.get(_BROKER_META_KEY)
    emitter = meta.get(_PROGRESS_META_KEY)
    if emitter is not None:
        emitter.emit("sources", "sources_start", "Gathering sources", 12.0,
                     {"skills": _selected_skill_ids(meta)})
    documents = _run_selected_skills(meta, gateway=gateway, broker=broker)
    if emitter is not None:
        # One skill_done step per selected skill (best-effort; we don't have a
        # per-skill document split here, so report the aggregate corpus size).
        for sid in _selected_skill_ids(meta):
            emitter.emit("sources", "skill_done", str(sid), 18.0,
                         {"skill_id": sid, "documents": len(documents)})
    if not documents:
        return []
    existing = _meta_documents(meta)
    meta["documents"] = existing + _skill_docs_to_meta(documents)
    # Retain the raw skill Documents (carrying metadata.skill_id + any
    # entailment_score) for contradiction detection in run_job.
    prior = meta.get(_SKILL_DOCS_META_KEY) or []
    meta[_SKILL_DOCS_META_KEY] = list(prior) + list(documents)
    return documents


def _collect_skill_documents(meta: dict) -> list:
    """The raw skill Documents stashed by :func:`_inject_skill_documents`."""
    return list(meta.get(_SKILL_DOCS_META_KEY) or [])


def _maybe_flag_auto_adjudicate(meta: dict, summary: dict, documents: list) -> None:
    """Auto-Adjudicate trigger (§6.4): detect contradictions over the run's
    corpus and, when the five conditions hold for any contradiction, record the
    decision on the artifact + job meta. This zone DETECTS and FLAGS only — the
    actual sub-job spawn is mode-side (P/R) and left as a logged hook.
    """
    if not documents:
        return
    try:
        from .verification.contradiction import detect, should_auto_adjudicate
        from .verification.discipline import extract_claims

        # Claims come from the produced artifact body where available; evidence
        # is the skill corpus (carrying metadata.skill_id for the cross-skill
        # layer). Each chunk's entailment_score may be pre-stamped by a skill.
        body = summary.get("body_json")
        body = body if isinstance(body, dict) else {}
        text = json.dumps(body, default=str)
        claims = extract_claims(text)
        if not claims:
            return
        depth_tier = str(meta.get("depth") or "standard")
        contradictions = detect(
            claims, documents, job_id=str(meta.get("job_id") or "job"),
            detected_at=_DETECTED_AT, load_bearing=True)
        for c in contradictions:
            if should_auto_adjudicate(c, depth_tier=depth_tier):
                meta["auto_adjudicate"] = c.contradiction_id
                if isinstance(summary.get("body_json"), dict):
                    summary["body_json"]["auto_adjudicate"] = c.contradiction_id
                # Sub-job spawn is deliberately NOT done here: it needs
                # loop-guard + budget-inheritance treatment first (tracked in
                # FUTURE_FEATURES.md §6, "Auto-Adjudicate sub-job spawn").
                _log.info("dispatcher.auto_adjudicate.flagged",
                          contradiction=c.contradiction_id,
                          depth=depth_tier)
                return
    except Exception as exc:  # never let detection crash a job
        _log.warning("dispatcher.auto_adjudicate.error", error=repr(exc))


def _adapt_decide(meta, *, gateway, gate, job_id, positions_db) -> dict:
    _inject_skill_documents(meta, gateway=gateway)
    fn = load_engine("decide")
    report = fn(
        meta.get("topic", ""),
        options=meta.get("options", []),
        criteria=meta.get("criteria", []),
        gateway=gateway, gate=gate, job_id=job_id, positions_db=positions_db,
    )
    body_html = (
        f"<p><strong>Winner:</strong> {report.winner}</p>"
        f"<p>{report.crux}</p>")
    return {
        "title": meta.get("topic", "Decision"),
        "body_html": body_html,
        "body_json": dataclasses.asdict(report),
        "source_count": len(report.options),
    }


def _adapt_survey(meta, *, gateway, gate, job_id, positions_db) -> dict:
    _inject_skill_documents(meta, gateway=gateway)
    fn = load_engine("survey")
    topic = meta.get("topic", "") or "Survey"
    documents = _meta_documents(meta)
    # Survey requires ≥1 document and ≥1 attribute. When the wizard supplies
    # neither (the common case today) fall back to a deterministic single-doc
    # placeholder so the run yields a (small) table rather than crashing.
    if not documents:
        documents = [{"doc_id": "topic", "title": topic,
                      "text": f"Survey scope: {topic}."}]
    attributes = meta.get("attributes") or [{"label": "summary"}]
    report = fn(
        topic,
        documents=documents,
        criteria=meta.get("criteria", []),
        attributes=attributes,
        gateway=gateway, gate=gate, job_id=job_id, positions_db=positions_db,
    )
    body_html = (
        f"<p>Included {report.prisma.included} of "
        f"{report.prisma.identified} documents.</p>")
    return {
        "title": topic,
        "body_html": body_html,
        "body_json": dataclasses.asdict(report),
        "source_count": report.prisma.included,
    }


def _adapt_reconstruct(meta, *, gateway, gate, job_id, positions_db) -> dict:
    _inject_skill_documents(meta, gateway=gateway)
    fn = load_engine("reconstruct")
    topic = meta.get("topic", "") or "Timeline"
    documents = _meta_documents(meta)
    # Reconstruct requires ≥1 document. Supply a deterministic placeholder when
    # the wizard attaches none so the run completes (an empty corpus simply
    # yields an empty timeline rather than raising).
    if not documents:
        documents = [{"doc_id": "topic", "title": topic,
                      "text": f"Reconstruction scope: {topic}."}]
    report = fn(
        topic,
        documents=documents,
        gateway=gateway, gate=gate, job_id=job_id, positions_db=positions_db,
    )
    body_html = f"<p>Reconstructed {len(report.events)} dated events.</p>"
    return {
        "title": topic,
        "body_html": body_html,
        "body_json": dataclasses.asdict(report),
        "source_count": len({s for e in report.events for s in e.sources}),
    }


def _adapt_watch(meta, *, gateway, gate, job_id, positions_db) -> dict:
    """Watch → digest. One monitor cycle over the supplied items/sources.

    Items come from ``meta["documents"]`` (url/title/text), falling back to
    ``meta["source_urls"]`` (title-only). With no inputs the cycle is empty and
    a deterministic empty digest is produced. Offline-deterministic via the
    length+keyword ``default_salience`` heuristic; when the job carries
    ``topic_interests`` (or ``interests``) AND a gateway is present, run_monitor
    upgrades to interest-relative LLM salience (gap #15, Zone S)."""
    from .modes.monitor import MonitorItem, run_monitor

    topic = meta.get("topic", "") or "Watch"
    items: list[MonitorItem] = []
    for i, d in enumerate(_meta_documents(meta)):
        url = str(d.get("url") or d.get("source") or d.get("id") or f"item-{i}")
        items.append(MonitorItem(
            source=str(d.get("source", url)), url=url,
            title=str(d.get("title", "")), body=str(d.get("text", "")),
            published_at=d.get("published_at")))
    if not items:
        for url in meta.get("source_urls", []) or []:
            items.append(MonitorItem(source=str(url), url=str(url),
                                     title=str(url), body=""))

    interests = meta.get("topic_interests") or meta.get("interests") or None
    report = run_monitor(
        topic, items, gateway=gateway, gate=gate,
        topic_interests=str(interests) if interests else None,
    )
    rows = "".join(
        f"<li>{_html.escape(c.item.title or c.item.url)} "
        f"<span class='meta'>(salience {c.salience:.2f}, {c.category})</span></li>"
        for c in (report.alerts + report.digest))
    body_html = (
        f"<p>{len(report.alerts)} alert(s), {len(report.digest)} digest item(s) "
        f"from {report.total_seen} seen "
        f"({report.suppressed_duplicates} duplicate(s) suppressed).</p>"
        + (f"<ul>{rows}</ul>" if rows else "<p><em>No items in this cycle.</em></p>"))
    return {
        "title": topic,
        "body_html": body_html,
        "body_json": dataclasses.asdict(report),
        "source_count": report.total_seen,
    }


def _adapt_ask(meta, *, gateway, gate, job_id, positions_db) -> dict:
    """Ask → transcript. A single grounded Q&A turn over the corpus.

    Offline-deterministic: with ``gateway=None`` ``quc.ask`` returns a stub
    answer; ``hybrid`` is built only when documents are attached."""
    from .modes.quc import QUCSession
    from .modes.quc import ask as quc_ask

    topic = meta.get("topic", "") or "Ask"
    session = QUCSession(id=job_id or "ask", topic=topic)
    hybrid = _build_hybrid(meta, gateway=gateway)
    quc_ask(session, topic, hybrid=hybrid, gateway=gateway, gate=gate)
    turns = [
        {"role": t.role, "text": t.text, "citations": list(t.citations)}
        for t in session.history
    ]
    last = session.history[-1]
    body_html = "".join(
        f"<p><strong>{_html.escape(t.role.title())}:</strong> "
        f"{_html.escape(t.text)}</p>" for t in session.history)
    return {
        "title": topic,
        "body_html": body_html,
        "body_json": {"topic": topic, "turns": turns},
        "source_count": len(last.citations),
    }


#: Deep-tier wall-clock budget → recursive node cap (max tree size).
_DEEP_BUDGET_NODES = {"30m": 8, "1h": 15, "2h": 25, "overnight": 50}


# ── Deep-tier checkpoint / resume (deployment gap #8) ───────────────────────
#
# A Deep (exhaustive) run can be many minutes; a crash mid-run must resume from
# the last completed node rather than restart. The exhaustive engine fires an
# ``on_checkpoint(TreeState)`` callback after every researched node; here we
# persist that snapshot as JSON under ``data_dir/checkpoints/<job_id>.json``
# (atomic temp+rename, no schema change). On (re)running a Deep job whose
# checkpoint exists, we load it and pass ``resume_state`` so expansion continues;
# a completed run deletes the file. No checkpoint == an unchanged fresh run.


def _checkpoint_dir(paths: Paths) -> Path:
    return paths.data_dir / "checkpoints"


def _checkpoint_path(paths: Paths, job_id: str) -> Path:
    return _checkpoint_dir(paths) / f"{job_id}.json"


def _write_checkpoint(paths: Paths, job_id: str, state) -> None:
    """Atomically persist a :class:`TreeState` snapshot (temp file + rename).

    Best-effort: a checkpoint failure must never abort the Deep run, so all
    errors are swallowed (the run simply loses crash-recovery for that tick)."""
    try:
        cdir = _checkpoint_dir(paths)
        cdir.mkdir(parents=True, exist_ok=True)
        final = _checkpoint_path(paths, job_id)
        tmp = final.with_suffix(final.suffix + f".{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(json.dumps(state.to_dict()), encoding="utf-8")
        tmp.replace(final)  # atomic on POSIX
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("dispatcher.checkpoint.write_failed",
                     job_id=job_id, error=repr(exc))


def _load_checkpoint(paths: Paths, job_id: str) -> dict | None:
    """Load a prior checkpoint dict for ``job_id``, or ``None`` if absent/bad."""
    path = _checkpoint_path(paths, job_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("dispatcher.checkpoint.load_failed",
                     job_id=job_id, error=repr(exc))
        return None


def _delete_checkpoint(paths: Paths, job_id: str) -> None:
    """Remove a completed run's checkpoint file (no-op if absent)."""
    try:
        _checkpoint_path(paths, job_id).unlink(missing_ok=True)
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("dispatcher.checkpoint.delete_failed",
                     job_id=job_id, error=repr(exc))


def _serialize_tree(node) -> dict:
    return {
        "question": node.question, "depth": node.depth, "status": node.status,
        "body": node.body, "citations": list(node.citations),
        "children": [_serialize_tree(c) for c in node.children],
    }


def _adapt_investigate_deep(meta, knobs, *, gateway, gate, job_id) -> dict:
    """Deep tier → recursive question-tree research via the exhaustive engine.

    Each node is researched with a one-round deep-dive (grounded iff it gathers
    citations); the tree is bounded by the Deep budget. Offline-deterministic
    (stub bodies, every node a known-unknown without a corpus)."""
    from .modes.deepdive import run_deepdive
    from .modes.exhaustive import TreeState, run_exhaustive

    topic = meta.get("topic", "") or "Investigation"
    hybrid = _build_hybrid(meta, gateway=gateway)
    max_nodes = _DEEP_BUDGET_NODES.get(str(meta.get("budget", "1h")), 15)

    def _research(q: str):
        try:
            r = run_deepdive(q, hybrid=hybrid, gateway=gateway, job_id=job_id,
                             gate=gate, max_rounds=1, top_k=knobs["top_k"])
            cites = sorted({c for s in r.sections for c in s.citations})
            body = " ".join(s.body for s in r.sections if s.body.strip())
            return (body or f"[draft] {q}", list(cites), bool(cites))
        except Exception:
            return (f"[draft] {q}", [], False)

    # Checkpoint/resume wiring (deployment gap #8). With a resolved data dir we
    # persist a crash-recovery snapshot after every node and resume from any
    # prior checkpoint; absent ``paths`` (or job_id) this degrades to a plain run.
    paths = meta.get(_PATHS_META_KEY)
    emitter = meta.get(_PROGRESS_META_KEY)
    resume_state = None
    if paths is not None and job_id:
        resume_state = _load_checkpoint(paths, job_id)
        if resume_state is not None:
            _log.info("dispatcher.checkpoint.resume", job_id=job_id,
                      done=resume_state.get("done"))

    # Wire the progress trace: a node step per researched node and a checkpoint
    # heartbeat. Both are best-effort (the emitter swallows its own errors).
    def on_checkpoint(state: TreeState) -> None:
        if paths is not None and job_id:
            _write_checkpoint(paths, job_id, state)
        if emitter is not None:
            emitter.checkpoint_cb(state)

    on_node = emitter.node_cb if emitter is not None else None
    tree = run_exhaustive(topic, research_fn=_research, gateway=gateway,
                          job_id=job_id, gate=gate, max_nodes=max_nodes,
                          max_depth=3, on_node=on_node,
                          on_checkpoint=on_checkpoint, resume_state=resume_state)

    # Completed run → drop the checkpoint so a future job with this id starts
    # fresh (and disk doesn't accumulate stale snapshots).
    if paths is not None and job_id:
        _delete_checkpoint(paths, job_id)
    body_json = {
        "question": topic, "depth": "deep", "engine": "exhaustive",
        "budget": meta.get("budget"),
        "tree": _serialize_tree(tree.root),
        "total_nodes": tree.total_nodes, "grounded": tree.grounded,
        "known_unknowns": tree.known_unknowns,
        "coverage": tree.coverage_ratio, "truncated": tree.truncated,
        "max_depth_reached": tree.max_depth_reached,
    }

    def _count(node, acc):
        acc.update(node.citations)
        for c in node.children:
            _count(c, acc)
        return acc
    source_count = len(_count(tree.root, set()))
    body_html = (
        f"<p>Recursive deep research: {tree.grounded}/{tree.total_nodes} nodes "
        f"grounded (depth {tree.max_depth_reached}"
        f"{', budget-truncated' if tree.truncated else ''}).</p>")
    return {"title": topic, "body_html": body_html, "body_json": body_json,
            "source_count": source_count}


def _adapt_investigate(meta, *, gateway, gate, job_id, positions_db) -> dict:
    """Investigate → report. Bounded TTD-DR deep-dive over the corpus.

    Offline-deterministic: ``run_deepdive`` writes stub section bodies when
    ``gateway=None``. We serialise a JSON-safe view of the report (the full
    ``DraftReport`` carries non-serialisable evidence chunks)."""
    from .modes.deepdive import run_deepdive
    from .modes.depth import resolve_depth

    _inject_skill_documents(meta, gateway=gateway)
    topic = meta.get("topic", "") or "Investigation"
    knobs = resolve_depth(meta.get("depth"))
    if knobs.get("recursive"):
        return _adapt_investigate_deep(meta, knobs, gateway=gateway, gate=gate,
                                       job_id=job_id)
    hybrid = _build_hybrid(meta, gateway=gateway)
    emitter = meta.get(_PROGRESS_META_KEY)
    on_round = emitter.round_cb if emitter is not None else None
    report = run_deepdive(topic, hybrid=hybrid, gateway=gateway,
                          job_id=job_id, gate=gate, on_round=on_round,
                          max_rounds=knobs["max_rounds"], top_k=knobs["top_k"])
    parts = []
    for s in report.sections:
        parts.append(f"<h3>{_html.escape(s.title)}</h3>")
        parts.append(f"<p>{_html.escape(s.body)}</p>")
        if s.citations:
            parts.append(f"<p class='meta'>sources: {len(s.citations)}</p>")
    if report.open_questions:
        parts.append("<h3>Open questions</h3><ul>" + "".join(
            f"<li>{_html.escape(q)}</li>" for q in report.open_questions) + "</ul>")
    body_json = {
        "question": report.question,
        "question_type": report.framing.question_type.value,
        "depth": knobs["tier"],
        "max_rounds": knobs["max_rounds"],
        "rounds_used": report.rounds_used,
        "sections": [
            {"title": s.title, "sub_question": s.sub_question,
             "body": s.body, "citations": list(s.citations),
             "is_load_bearing": s.is_load_bearing}
            for s in report.sections
        ],
        "open_questions": list(report.open_questions),
        "ruled_out": list(report.ruled_out),
    }
    # Coverage critic: which planned (load-bearing) sub-questions are answered?
    # Runs from Standard up; a gap is recorded as a known-unknown.
    if knobs.get("coverage_critic"):
        try:
            from .verification.coverage import assess_coverage
            subs = [s.sub_question for s in report.sections if s.is_load_bearing] \
                or list(report.framing.sub_questions)
            cov = assess_coverage(subs, report.sections)
            body_json["coverage"] = cov.coverage_ratio
            body_json["coverage_gaps"] = cov.gaps
        except Exception:
            pass

    # Adversarial refutation: stress-test key claims (Thorough+). Refuted/
    # contested claims are flagged so they don't stand unchallenged.
    if knobs.get("adversarial"):
        try:
            from .verification.adversarial import refute_claims, summarize
            evidence = "\n".join(s.body for s in report.sections)
            key_claims = [s.body.split(".")[0].strip() + "."
                          for s in report.sections
                          if s.is_load_bearing and s.body.strip()]
            verdicts = refute_claims(key_claims, evidence, gateway=gateway,
                                     job_id=job_id)
            body_json["adversarial"] = summarize(verdicts)
            body_json["contested_claims"] = [
                v.claim for v in verdicts if not v.survives]
        except Exception:
            pass

    source_count = len({c for s in report.sections for c in s.citations})
    return {
        "title": topic,
        "body_html": "".join(parts) or "<p><em>No findings.</em></p>",
        "body_json": body_json,
        "source_count": source_count,
    }


def _adapt_adjudicate(meta, *, gateway, gate, job_id, positions_db) -> dict:
    """Adjudicate → verdict. Multi-perspective debate on a claim.

    Offline-deterministic via the heuristic perspective responses in
    ``run_debate`` when ``gateway=None``."""
    from .modes.debate import run_debate

    _inject_skill_documents(meta, gateway=gateway)
    topic = meta.get("topic", "") or "Claim under debate"
    draft = str(meta.get("draft", "")) or topic
    result = run_debate(claim=topic, draft=draft, gateway=gateway, job_id=job_id,
                        gate=gate)
    persp = "".join(
        f"<li><strong>{_html.escape(r.perspective.name)}:</strong> "
        f"{_html.escape(r.critique)}</li>" for r in result.responses)
    body_html = (
        f"<p><strong>Verdict:</strong> {_html.escape(result.judge_summary)}</p>"
        f"<ul>{persp}</ul>")
    return {
        "title": topic,
        "body_html": body_html,
        "body_json": dataclasses.asdict(result),
        "source_count": len(result.responses),
    }


_ADAPTERS: dict[str, Callable[..., dict]] = {
    "watch": _adapt_watch,
    "ask": _adapt_ask,
    "investigate": _adapt_investigate,
    "survey": _adapt_survey,
    "reconstruct": _adapt_reconstruct,
    "decide": _adapt_decide,
    "adjudicate": _adapt_adjudicate,
}


def _persist_artifact(state_db, *, job_id: str, mode_key: str,
                      artifact_type: str, summary: dict) -> str:
    draft_id = "d-" + uuid.uuid4().hex[:6]
    body_json = json.dumps(summary.get("body_json")) if summary.get("body_json") else None
    conn = open_db(state_db)
    try:
        conn.execute(
            "INSERT INTO drafts (id, job_id, topic, title, body_html, body_json, "
            "artifact_type, source_count, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'staged')",
            (draft_id, job_id, summary["title"][:60], summary["title"],
             summary.get("body_html", ""), body_json, artifact_type,
             summary.get("source_count", 0)))
    finally:
        conn.close()
    return draft_id


def _emit_prov_sidecar(paths: Paths, *, draft_id: str, job_id: str,
                       question: str, mode_key: str, summary: dict,
                       backends: dict, gateway: Gateway | None) -> None:
    """Write a PROV-O JSON sidecar next to the staged artifact (best-effort).

    The dispatcher already embeds a provenance manifest in the artifact body;
    this also writes a self-contained ``<draft_id>.prov.json`` that travels with
    the artifact (W3C PROV-O), so every research run — not just the legacy
    ``ResearchPipeline`` path — leaves a sidecar. Never raises into the dispatch
    loop. Time-free for determinism (the draft row carries created_at).
    """
    try:
        from .provenance import build_run_sidecar, write_run_sidecar
        body_html = summary.get("body_html", "") or ""
        content_hash = hashlib.sha256(body_html.encode()).hexdigest()
        sampling = None
        if gateway is not None and hasattr(gateway, "sampling_provenance"):
            try:
                sampling = gateway.sampling_provenance()
            except Exception:
                sampling = None
        sidecar = build_run_sidecar(
            draft_id=draft_id, job_id=job_id, question=question, mode=mode_key,
            backends=backends or {}, source_count=summary.get("source_count", 0),
            content_hash=content_hash, sampling=sampling)
        write_run_sidecar(paths.staging_dir / f"{draft_id}.prov.json", sidecar)
        _log.info("prov_sidecar.written", draft_id=draft_id)
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("prov_sidecar.failed", draft_id=draft_id, error=repr(exc))


def _is_guard_trip(exc: Exception) -> bool:
    """True when a job failed because a budget/loop guard stopped it.

    Covers the loop detector (``LoopTripped``) and a Governor budget-bucket
    underflow (whose error text names the underflow/budget). Used to fire a
    user-facing notification + a ``governor.tripped`` event, vs an ordinary
    crash.
    """
    from .gateway import LoopTripped
    if isinstance(exc, LoopTripped):
        return True
    msg = str(exc).lower()
    return "underflow" in msg or "budget" in msg or "tripped" in msg


def _notify_budget_trip(paths: Paths, reason: str) -> None:
    """Best-effort Telegram ping that a run was stopped by a guard.

    Reads the ``[ui]`` config (``notify_enabled`` + telegram token/chat id) at the
    application edge where secrets live (the Governor itself has no config access).
    No-op when disabled/unconfigured; never raises into the dispatch loop.
    """
    try:
        if not paths.config_file.exists():
            return
        try:
            import tomllib
        except ImportError:  # pragma: no cover
            import tomli as tomllib  # type: ignore
        with paths.config_file.open("rb") as fh:
            ui = tomllib.load(fh).get("ui", {})
        if not ui.get("notify_enabled", False):
            return
        from .notify import notify_budget_trip
        notify_budget_trip(
            reason,
            bot_token=str(ui.get("telegram_bot_token", "")),
            chat_id=str(ui.get("telegram_chat_id", "")),
            enabled=True,
        )
    except Exception:
        pass


def _audit(paths: Paths, event_type: str, payload: dict) -> None:
    if not paths.audit_db.exists():
        return
    try:
        from .verification.audit_chain import append_event
        append_event(paths.audit_db, actor="dispatcher",
                     event_type=event_type, payload=payload,
                     data_dir=paths.data_dir)
    except Exception:
        pass


def _notify_staged(paths: Paths, *, artifact_type: str, summary: dict) -> None:
    """Best-effort Telegram ping that an artifact is staged for review.

    Reads the ``[ui]`` config (``notify_enabled`` + the telegram token/chat id),
    renders a concise per-type mobile summary, and sends it. A no-op when
    notifications are disabled or unconfigured. Never raises — the dispatch loop
    and ``run_job`` must stay alive regardless of notification outcome.
    """
    try:
        if not paths.config_file.exists():
            return
        try:
            import tomllib
        except ImportError:  # pragma: no cover
            import tomli as tomllib  # type: ignore
        with paths.config_file.open("rb") as fh:
            ui = tomllib.load(fh).get("ui", {})
        if not ui.get("notify_enabled", False):
            return
        from .notify import notify_artifact_staged
        notify_artifact_staged(
            artifact_type, summary.get("title", ""), summary.get("body_json"),
            bot_token=str(ui.get("telegram_bot_token", "")),
            chat_id=str(ui.get("telegram_chat_id", "")),
            enabled=True,
        )
    except Exception:
        pass


def _provenance_manifest(*, mode_key: str, meta: dict, summary: dict,
                         gateway: Gateway | None, backends: dict) -> dict:
    """Build a deterministic provenance manifest for an artifact.

    Records how the artifact was produced — mode, depth/budget, the backend that
    actually served it (real ``ollama`` vs ``mock`` fallback vs offline stub),
    the per-role models, source count, any quality metrics the engine surfaced,
    and a content hash of the body. Deterministic given fixed inputs (no
    wall-clock inside), so the same corpus + question reproduces the same
    manifest — the property frontier tools can't offer. The draft row carries
    its own ``created_at`` separately.
    """
    body = summary.get("body_json")
    body = body if isinstance(body, dict) else {}

    if gateway is None:
        backend = "offline-stub"
    elif backends.get("ollama"):
        backend = "ollama"
    elif backends:
        backend = "mock"
    else:
        backend = "none"

    models: dict[str, str] = {}
    if gateway is not None:
        for role in ("planner", "researcher", "synthesizer", "aux_context"):
            try:
                b = gateway.binding(role)
                if b is not None:
                    models[role] = b.model
            except Exception:
                pass

    metrics: dict[str, Any] = {}
    for key in ("citation_coverage", "entailment_coverage", "rounds_used",
                "nodes_resolved", "coverage"):
        if key in body:
            metrics[key] = body[key]

    payload = {
        "engine_version": ENGINE_VERSION,
        "mode": mode_key,
        "depth": meta.get("depth"),
        "budget": meta.get("budget"),
        "backend": backend,
        "backends": backends or None,
        "models": models or None,
        "source_count": summary.get("source_count", 0),
        "metrics": metrics or None,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    payload["content_sha256"] = digest[:16]
    return payload


def _emit_verification(progress, summary: dict) -> None:
    """Emit ``verification`` steps off a produced artifact body (best-effort).

    Surfaces a coverage step (with gap count), a ``contradiction`` step when the
    body flags an auto-adjudicate, and one ``known_unknown`` per open question.
    Pulls only from the JSON body so it works across modes; never raises."""
    try:
        body = summary.get("body_json")
        if not isinstance(body, dict):
            return
        if "coverage" in body or "coverage_gaps" in body:
            gaps = body.get("coverage_gaps") or []
            progress.emit("verification", "coverage", "Coverage check", 82.0, {
                "coverage": body.get("coverage"),
                "gaps": len(gaps) if isinstance(gaps, list) else 0,
            })
        contested = body.get("contested_claims") or []
        if contested or body.get("auto_adjudicate"):
            progress.emit("verification", "contradiction",
                          "Contested claims", 84.0, {
                              "contested": len(contested)
                              if isinstance(contested, list) else 0,
                              "auto_adjudicate": body.get("auto_adjudicate"),
                          })
        open_qs = body.get("open_questions") or body.get("known_unknowns") or []
        if isinstance(open_qs, list):
            for q in open_qs:
                progress.emit("verification", "known_unknown", str(q)[:120],
                              86.0, {"question": str(q)})
    except Exception:  # pragma: no cover - defensive
        pass


def _wire_token_stream(gateway, bus) -> None:
    """Publish synthesizer tokens as SSE ``synthesis.token`` events.

    Only the synthesizer role streams — that is the user-visible narrative the
    dashboard renders live; planner/researcher chatter would be noise. The sink
    is best-effort by contract (the gateway swallows its exceptions) and
    idempotent to wire: an existing sink is never replaced.
    """
    try:
        if getattr(gateway, "token_sink", None) is not None:
            return

        def _sink(role: str, job_id: str | None, token: str) -> None:
            if role != "synthesizer" or not job_id:
                return
            bus.publish("synthesis.token", {"job_id": job_id, "token": token})

        gateway.token_sink = _sink
    except Exception:  # never let live-feed wiring break a job
        pass


def run_job(paths: Paths, job: ClaimedJob, *,
            gateway: Gateway | None = None,
            gate: SchedulerGate | None = None,
            bus=None) -> str | None:
    """Run a claimed job's engine and persist its artifact.

    On success the job moves to ``review`` and a draft (status ``staged``) is
    written; the draft id is returned. On any engine error the job moves to
    ``failed`` and None is returned. Never raises — the dispatch loop must stay
    alive across one bad job.
    """
    try:
        mode_key = canonical(job.mode)
        spec = resolve(mode_key)
    except KeyError:
        _set_status(paths.state_db, job.id, "failed")
        _audit(paths, "job.failed", {"job_id": job.id, "error": "unknown mode"})
        return None

    adapter = _ADAPTERS.get(mode_key)
    if adapter is None:
        _set_status(paths.state_db, job.id, "failed")
        _audit(paths, "job.failed",
               {"job_id": job.id, "error": f"no dispatcher adapter for {mode_key}"})
        if bus is not None:
            bus.publish("job.status", {"id": job.id, "status": "failed"})
        return None

    # Hand the per-job broker + routing context to the adapters via private meta
    # keys (keeps the stable adapter signatures untouched). The broker is the
    # platform chokepoint every skill fetch passes through; built best-effort so
    # a broker failure degrades to "no skills" rather than crashing the job.
    job.meta.setdefault("mode", mode_key)
    job.meta.setdefault("job_id", job.id)
    job.meta[_BROKER_META_KEY] = _build_broker(paths)
    # Hand the resolved data dir to adapters that checkpoint (Deep tier).
    job.meta[_PATHS_META_KEY] = paths
    # Per-job progress trace. Best-effort: a ProgressEmitter never raises, so a
    # trace failure can never fail the job. The emitter is handed to the
    # investigate adapters (via meta) to wire the engine progress callbacks.
    from .progress import ProgressEmitter
    progress = ProgressEmitter(job.id, paths, bus)
    job.meta[_PROGRESS_META_KEY] = progress
    progress.emit("framing", "start", f"Framing: {mode_key}", 5.0,
                  {"mode": mode_key, "depth": job.meta.get("depth")})

    # Live synthesis feed: stream the synthesizer's tokens to the dashboard so
    # a long run shows text being written instead of a frozen progress bar.
    # Wired once per gateway (the sink is stateless — job_id arrives per call).
    if bus is not None and gateway is not None:
        _wire_token_stream(gateway, bus)

    backends: dict = {}
    try:
        summary = adapter(job.meta, gateway=gateway, gate=gate, job_id=job.id,
                          positions_db=paths.positions_db)
        # Modes without rich engine callbacks (ask/survey/reconstruct/decide/
        # adjudicate/watch) still get a minimal trace: framing→drafting→done.
        progress.emit("drafting", "drafted", summary.get("title", mode_key),
                      75.0, {"source_count": summary.get("source_count", 0)})
        # Verification: surface contradictions/coverage gaps and a known_unknown
        # per open question off the produced artifact body (best-effort).
        _emit_verification(progress, summary)
        # Auto-Adjudicate trigger (§6.4): detect contradictions over the run's
        # skill corpus and flag a follow-up when the five conditions hold.
        if mode_key in _MULTISOURCE_MODES:
            skill_docs = _collect_skill_documents(job.meta)
            _maybe_flag_auto_adjudicate(job.meta, summary, skill_docs)
        # Drain the backend tally BEFORE persisting so the provenance manifest
        # can record which backend actually served the job.
        if gateway is not None:
            try:
                backends = gateway.drain_backends()
            except Exception:
                backends = {}
        # Attach a deterministic provenance manifest to the artifact body.
        try:
            body = summary.get("body_json")
            if isinstance(body, dict):
                body["provenance"] = _provenance_manifest(
                    mode_key=mode_key, meta=job.meta, summary=summary,
                    gateway=gateway, backends=backends)
        except Exception:
            pass
        draft_id = _persist_artifact(
            paths.state_db, job_id=job.id, mode_key=mode_key,
            artifact_type=spec.artifact_type.value, summary=summary)
        # PROV-O sidecar travels with the artifact (every run, not just pipeline).
        _emit_prov_sidecar(
            paths, draft_id=draft_id, job_id=job.id,
            question=str(job.meta.get("topic", "")), mode_key=mode_key,
            summary=summary, backends=backends, gateway=gateway)
    except Exception as exc:
        _set_status(paths.state_db, job.id, "failed")
        _audit(paths, "job.failed", {"job_id": job.id, "error": str(exc)})
        # A budget/loop guard stopping a run is a user-facing event: notify + emit.
        if _is_guard_trip(exc):
            _notify_budget_trip(paths, str(exc))
            _audit(paths, "governor.tripped", {"job_id": job.id, "reason": str(exc)})
            if bus is not None:
                bus.publish("governor.tripped",
                            {"job_id": job.id, "reason": str(exc)})
        if bus is not None:
            bus.publish("job.status", {"id": job.id, "status": "failed"})
        return None

    # Final progress step: done at 100. This also nudges metadata_json.progress
    # to 1.0, but we set it explicitly below for the persisted snapshot too.
    progress.emit("done", "done", "Complete", 100.0, {"draft_id": draft_id})

    meta = dict(job.meta)
    # Drop the private, non-serializable handoff keys before persisting.
    meta.pop(_BROKER_META_KEY, None)
    meta.pop(_SKILL_DOCS_META_KEY, None)
    meta.pop(_PATHS_META_KEY, None)
    meta.pop(_PROGRESS_META_KEY, None)
    meta["progress"] = 1.0
    meta["draft_id"] = draft_id
    # Record which backend actually served this job so a "mock masquerade" (a
    # real-gateway run that silently degraded to the mock) is visible downstream.
    if backends:
        real = backends.get("ollama", 0)
        meta["backends"] = backends
        meta["backend"] = "ollama" if real else "mock"
    _set_status(paths.state_db, job.id, "review", meta=meta)
    _audit(paths, "job.review",
           {"job_id": job.id, "draft_id": draft_id, "mode": mode_key,
            "backend": meta.get("backend")})
    # Best-effort mobile review ping (no-op unless [ui].notify_enabled + token).
    _notify_staged(paths, artifact_type=spec.artifact_type.value, summary=summary)
    if bus is not None:
        bus.publish("job.status", {"id": job.id, "status": "review"})
        bus.publish("job.progress", {"id": job.id, "progress": 1.0})
    return draft_id


def dispatch_once(paths: Paths, *, gateway: Gateway | None = None,
                  gate: SchedulerGate | None = None, bus=None) -> str | None:
    """Claim and run a single job. Returns the draft id, or None if idle."""
    job = claim_one_job(paths.state_db)
    if job is None:
        return None
    return run_job(paths, job, gateway=gateway, gate=gate, bus=bus)


#: Smallest reasoning model we will bother to load, plus headroom. Below this
#: much free RAM the dispatch loop defers real work rather than thrash/mock.
MIN_REASONING_RESIDENT_GB = 4.0


def build_runtime_gateway(paths: Paths) -> Gateway | None:
    """Best-effort real Ollama gateway for the live dispatch loop.

    Returns a real-backend :class:`Gateway` (capability classes resolved to the
    installed Ollama tags, RAM admission inherited through ``Gateway.complete``'s
    ``ollama_slot`` seam) when Ollama is reachable with at least one model.
    Returns ``None`` when Ollama is unavailable so the dispatcher degrades to its
    offline-deterministic stub path instead of failing jobs. Never raises.

    Model selection is constrained to **live-free RAM** (free minus a safety
    margin), not total capacity — so on a busy box we pick a model that actually
    fits and produces real output, instead of a too-big pick that would only
    ever degrade to the low-memory mock.

    Built ONCE at dispatch-loop start, not per tick (probing shells out to
    Ollama). The default offline test suite never calls this — tests drive
    ``dispatch_once`` with ``gateway=None`` directly.
    """
    try:
        from .gateway import RUNTIME_RAM_MARGIN_GB
        from .hardware import probe
        from .pipeline import _ollama_installed_tags, make_gateway

        tags = _ollama_installed_tags()
        if not tags:
            return None
        profile = probe()
        budget = max(0.0, profile.free_ram_gb - RUNTIME_RAM_MARGIN_GB)
        return make_gateway(paths, profile, offline=False, installed=tags,
                            budget_gb=budget)
    except Exception:
        return None


def runtime_ram_ok(*, min_resident_gb: float | None = None) -> bool:
    """True if there is enough live-free RAM to run a real reasoning model.

    The dispatch loop checks this before claiming a job for a *real* gateway: if
    free RAM cannot fit even the smallest reasoning model plus margin, it skips
    the tick (transient defer) so the job waits for headroom instead of running
    straight into the low-memory mock.

    The floor **adapts to the box**: it is the resident size of the smallest
    reasoning model actually installed (a 1B box clears on far less RAM than an
    8B-only box), so small machines are not deferred forever while big-model-only
    machines still wait for genuine headroom. ``min_resident_gb`` overrides the
    probe. Returns True when RAM/models cannot be measured (never block on a
    measurement failure)."""
    try:
        from .gateway import RUNTIME_RAM_MARGIN_GB, smallest_reasoning_resident_gb
        from .hardware import probe
        if min_resident_gb is None:
            try:
                from .pipeline import _ollama_installed_tags
                min_resident_gb = smallest_reasoning_resident_gb(
                    _ollama_installed_tags(), default_gb=MIN_REASONING_RESIDENT_GB)
            except Exception:
                min_resident_gb = MIN_REASONING_RESIDENT_GB
        return probe().free_ram_gb >= (min_resident_gb + RUNTIME_RAM_MARGIN_GB)
    except Exception:
        return True
