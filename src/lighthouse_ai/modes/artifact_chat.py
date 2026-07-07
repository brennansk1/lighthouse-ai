"""Artifact Chat — interactive, grounded conversation with a staged artifact.

See ``docs/ARTIFACT_CHAT_DESIGN.md``. The turn engine is the existing
:func:`quc.ask`; this module adds the pieces that make a chat *about an
artifact* trustworthy on a local model:

* a persisted **evidence snapshot** so the chat is grounded in the artifact's own
  sources even when the live corpus is gone (in-memory store, post-run);
* conservative, retrieval-signal-driven **research escalation** (never the weak
  model deciding what it knows);
* an answer-side **discipline gate** (citation coverage → WEP band);
* honest per-turn **backend reporting** — a turn that silently fell back to the
  mock provider must never masquerade as a real answer.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..persistence import open_db
from ..rag.bm25 import BM25Index
from ..rag.chunker import Chunk
from ..rag.embedder import Embedder, HashEmbedder
from ..rag.hybrid import HybridSearch
from ..rag.store import InMemoryStore
from .quc import QUCSession, Turn, ask

#: The MockProvider stamps its output with this prefix — a reliable tell that a
#: turn's answer was NOT produced by the real local model.
MOCK_SIGNATURE = "[mock"

#: Below this many on-topic hits from the artifact + corpus, a turn escalates to
#: fresh research (when an acquire function is available).
_SUFFICIENCY_MIN_HITS = 2


def session_id_for(draft_id: str) -> str:
    """Deterministic chat session id for an artifact (one conversation each)."""
    return f"chat-{draft_id}"


# --- evidence snapshot -------------------------------------------------------

def snapshot_evidence(state_db, draft_id: str, evidence: list) -> int:
    """Persist the artifact's evidence chunks for later grounded chat.

    ``evidence`` may be ``HybridResult`` objects (``.chunk``) or bare chunks.
    Best-effort and idempotent (``INSERT OR REPLACE``); returns the count
    written. Never raises — a snapshot failure must not fail the run.
    """
    rows = []
    for e in evidence or []:
        chunk = getattr(e, "chunk", e)
        cid = getattr(chunk, "id", None)
        text = getattr(chunk, "text", None)
        if not cid or not text:
            continue
        meta = getattr(chunk, "metadata", {}) or {}
        rows.append((draft_id, str(cid), str(text),
                     str(meta.get("source", "")), json.dumps(meta, default=str)))
    if not rows:
        return 0
    try:
        conn = open_db(state_db)
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO artifact_evidence "
                "(draft_id, chunk_id, text, source, metadata_json) "
                "VALUES (?, ?, ?, ?, ?)", rows)
        finally:
            conn.close()
    except Exception:
        return 0
    return len(rows)


def load_evidence_chunks(state_db, draft_id: str) -> list[Chunk]:
    """Rebuild the artifact's evidence chunks from the snapshot table."""
    try:
        conn = open_db(state_db)
        try:
            cur = conn.execute(
                "SELECT chunk_id, text, source, metadata_json FROM "
                "artifact_evidence WHERE draft_id=?", (draft_id,))
            out: list[Chunk] = []
            for i, (cid, text, source, meta_json) in enumerate(cur.fetchall()):
                try:
                    meta = json.loads(meta_json) if meta_json else {}
                except (TypeError, ValueError):
                    meta = {}
                if source and "source" not in meta:
                    meta["source"] = source
                out.append(Chunk(id=cid, document_id=meta.get("document_id", cid),
                                 text=text, position=i, metadata=meta))
            return out
        finally:
            conn.close()
    except Exception:
        return []


def build_grounded_hybrid(chunks: list[Chunk],
                          embedder: Embedder | None = None) -> HybridSearch | None:
    """Build a small in-memory retriever over the artifact's evidence.

    Uses the deterministic :class:`HashEmbedder` by default so grounding works
    offline and in tests; a real embedder can be injected when a gateway is live.
    Returns ``None`` when there is nothing to ground on.
    """
    if not chunks:
        return None
    hy = HybridSearch(InMemoryStore(), embedder or HashEmbedder(), BM25Index())
    hy.add(chunks)
    return hy


# --- suggestions -------------------------------------------------------------

def suggestions_for(artifact: dict[str, Any] | None) -> list[str]:
    """Starter prompts derived from the artifact — its open questions and
    contested claims make the best follow-ups. Falls back to generic probes."""
    if not artifact:
        return ["What are the main findings?", "What sources support this?",
                "What did this miss?"]
    out: list[str] = []
    for q in (artifact.get("open_questions") or [])[:2]:
        out.append(f"Dig into: {q}")
    for c in (artifact.get("contested_claims") or [])[:1]:
        out.append(f"Is this actually true? — {str(c)[:80]}")
    if not out:
        out = ["What are the main findings?",
               "Which claims are best supported by the sources?",
               "What would change the conclusion?"]
    return out[:3]


# --- the turn ----------------------------------------------------------------

@dataclass
class ChatTurnResult:
    turn: Turn
    backend: str                       # "ollama" | "mock" | "offline"
    researched: bool = False
    research_note: str | None = None
    citations: list[dict] = field(default_factory=list)
    wep_band: str | None = None

    def as_dict(self) -> dict:
        return {
            "role": self.turn.role, "text": self.turn.text,
            "citations": self.citations, "backend": self.backend,
            "researched": self.researched, "research_note": self.research_note,
            "wep_band": self.wep_band,
        }


def _backend_of(answer: str, gateway) -> str:
    if gateway is None:
        return "offline"
    if answer.lstrip().startswith(MOCK_SIGNATURE):
        return "mock"
    return "ollama"


def _citation_view(ids: list[str], chunks: list[Chunk]) -> list[dict]:
    by_id = {c.id: c for c in chunks}
    view = []
    for cid in ids:
        c = by_id.get(cid)
        if c is None:
            continue
        view.append({"id": cid,
                     "source": (c.metadata or {}).get("source", ""),
                     "snippet": c.text[:200]})
    return view


def chat_turn(
    session: QUCSession,
    message: str,
    chunks: list[Chunk],
    *,
    gateway=None,
    embedder: Embedder | None = None,
    acquire_fn: Callable[[str], list[Chunk]] | None = None,
    gate=None,
) -> ChatTurnResult:
    """Run one grounded chat turn over an artifact's evidence.

    ``chunks`` is the artifact's evidence snapshot. When retrieval over it is
    thin and ``acquire_fn`` is supplied, the turn escalates: it fetches fresh
    evidence for ``message``, adds it to the grounding, and answers over the
    enlarged set. The answer is drafted by :func:`quc.ask` and its backend is
    reported honestly.
    """
    all_chunks = list(chunks)
    researched = False
    research_note = None

    hybrid = build_grounded_hybrid(all_chunks, embedder)
    # Sufficiency check on the artifact's own evidence — retrieval-driven, not
    # model-introspection. Escalate only when grounding is genuinely thin.
    if acquire_fn is not None and len(message.split()) >= 4:
        hits = hybrid.search(message, top_k=4) if hybrid is not None else []
        if len(hits) < _SUFFICIENCY_MIN_HITS:
            try:
                fresh = acquire_fn(message) or []
            except Exception:
                fresh = []
            if fresh:
                all_chunks.extend(fresh)
                hybrid = build_grounded_hybrid(all_chunks, embedder)
                researched = True
                research_note = f"searched and added {len(fresh)} new source(s)"

    turn = ask(session, message, hybrid=hybrid, gateway=gateway, gate=gate)
    backend = _backend_of(turn.text, gateway)

    # Answer-side discipline gate → an honest WEP band. Best-effort.
    wep_band = None
    try:
        from ..verification.discipline import check as _dcheck
        from ..verification.discipline import downgrade_wep
        rep = _dcheck(turn.text, evidence_chunks=all_chunks or None)
        wep_band = downgrade_wep(0.75, rep).name
    except Exception:
        pass

    return ChatTurnResult(
        turn=turn, backend=backend, researched=researched,
        research_note=research_note,
        citations=_citation_view(turn.citations, all_chunks),
        wep_band=wep_band,
    )
