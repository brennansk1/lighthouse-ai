"""Offline tests for artifact chat (modes/artifact_chat.py).

No real LLM, no network. Proves: the evidence snapshot round-trips, a turn is
grounded in it, backend honesty is reported (a mock answer is labelled mock, not
masqueraded), research escalation fires on thin retrieval, and suggestions come
from the artifact.
"""

from __future__ import annotations

from dataclasses import dataclass

from lighthouse_ai.modes.artifact_chat import (
    ChatTurnResult,
    chat_turn,
    load_evidence_chunks,
    session_id_for,
    snapshot_evidence,
    suggestions_for,
)
from lighthouse_ai.modes.quc import QUCSession
from lighthouse_ai.rag.chunker import Chunk


@dataclass
class _FakeResp:
    text: str


class _RealishGateway:
    """A gateway whose answer echoes the evidence — stands in for a grounded
    local model."""

    def complete(self, role, prompt, *, job_id=None, **kw):
        return _FakeResp(text="Based on the evidence, the answer is X [1].")


class _MockMasqueradeGateway:
    """A gateway that silently returns a MockProvider-stamped answer."""

    def complete(self, role, prompt, *, job_id=None, **kw):
        return _FakeResp(text="[mock 12p+3c] 'some prompt echo'")


def _chunks(n=3):
    return [
        Chunk(
            id=f"c{i}",
            document_id=f"d{i}",
            text=f"Evidence sentence number {i} about metabolic health.",
            position=i,
            metadata={"source": f"src{i}"},
        )
        for i in range(n)
    ]


def test_snapshot_round_trips(migrated_paths):
    written = snapshot_evidence(migrated_paths.state_db, "d-1", _chunks(3))
    assert written == 3
    loaded = load_evidence_chunks(migrated_paths.state_db, "d-1")
    assert [c.id for c in loaded] == ["c0", "c1", "c2"]
    assert loaded[0].metadata["source"] == "src0"


def test_snapshot_accepts_hybrid_results(migrated_paths):
    """snapshot_evidence must accept HybridResult-like objects (.chunk) too."""

    class _HR:
        def __init__(self, chunk):
            self.chunk = chunk

    written = snapshot_evidence(migrated_paths.state_db, "d-2", [_HR(c) for c in _chunks(2)])
    assert written == 2


def test_turn_offline_is_grounded_and_honest():
    """gateway=None → an offline turn, labelled 'offline', grounded in snapshot."""
    session = QUCSession(id=session_id_for("d-1"), topic="metabolic health")
    res = chat_turn(
        session, "What does the evidence say about metabolic health?", _chunks(3), gateway=None
    )
    assert isinstance(res, ChatTurnResult)
    assert res.backend == "offline"
    assert res.citations  # grounded in the snapshot chunks


def test_turn_reports_real_backend():
    session = QUCSession(id="chat-d1", topic="t")
    res = chat_turn(
        session,
        "What is the established finding on metabolic health?",
        _chunks(3),
        gateway=_RealishGateway(),
    )
    assert res.backend == "ollama"


def test_turn_does_not_let_mock_masquerade():
    """The trust-critical case: a silent mock fallback must be labelled 'mock',
    never presented as a real answer."""
    session = QUCSession(id="chat-d1", topic="t")
    res = chat_turn(
        session,
        "What is the established finding on metabolic health?",
        _chunks(3),
        gateway=_MockMasqueradeGateway(),
    )
    assert res.backend == "mock"


def test_escalation_fires_on_thin_retrieval():
    """With little grounding and an acquire_fn available, the turn researches."""
    extra = [
        Chunk(
            id="new1",
            document_id="n1",
            text="Freshly acquired evidence.",
            position=0,
            metadata={"source": "web"},
        )
    ]

    def _acquire(_q):
        return extra

    session = QUCSession(id="chat-d1", topic="t")
    res = chat_turn(
        session,
        "An entirely unrelated question about quantum gravity?",
        [],
        gateway=None,
        acquire_fn=_acquire,
    )
    assert res.researched is True
    assert res.research_note and "1" in res.research_note


def test_no_escalation_when_grounding_sufficient():
    def _acquire(_q):
        raise AssertionError("should not acquire when snapshot is sufficient")

    session = QUCSession(id="chat-d1", topic="t")
    # Many on-topic chunks → retrieval is sufficient → no escalation.
    res = chat_turn(
        session,
        "What does the evidence say about metabolic health?",
        _chunks(6),
        gateway=None,
        acquire_fn=_acquire,
    )
    assert res.researched is False


def test_suggestions_from_artifact_open_questions():
    art = {
        "open_questions": ["Does timing matter?", "What about long-term?"],
        "contested_claims": ["Fasting always helps"],
    }
    sug = suggestions_for(art)
    assert any("timing" in s for s in sug)
    assert len(sug) <= 3


def test_suggestions_fallback_when_empty():
    assert len(suggestions_for(None)) == 3
    assert len(suggestions_for({})) == 3


def test_rich_turn_persistence_and_retrieval(migrated_paths):
    from lighthouse_ai.modes.ask_store import load_session, save_session
    from lighthouse_ai.modes.quc import QUCSession

    # 1. Snapshot some evidence
    snapshot_evidence(migrated_paths.state_db, "d-rich", _chunks(3))
    chunks = load_evidence_chunks(migrated_paths.state_db, "d-rich")

    # 2. Run a turn with realish gateway
    session = QUCSession(id=session_id_for("d-rich"), topic="metabolic health")
    chat_turn(session, "What is the established finding?", chunks, gateway=_RealishGateway())

    # 3. Save the session
    save_session(migrated_paths.state_db, session)

    # 4. Load it back and verify fields on loaded Turn
    loaded = load_session(migrated_paths.state_db, session_id_for("d-rich"))
    assert loaded is not None
    assert len(loaded.history) == 2  # user turn + assistant turn
    ast_turn = loaded.history[1]
    assert ast_turn.backend == "ollama"
    assert ast_turn.wep_band is not None
    assert len(ast_turn.citations_rich) == 3
    assert ast_turn.citations_rich[0]["source"] == "src0"
