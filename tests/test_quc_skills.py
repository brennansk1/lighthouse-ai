"""Zone S — tests for per-turn skill selection and contradiction statement in
Mode C (Ask / QUC).

All tests are offline-deterministic: no real LLM calls, no datetime.now().
Tests cover:
- /sources pin parsing and session stickiness
- @skill directive parsing and precedence
- /adjudicate flag
- gateway=None path unchanged
- contradiction note prepended when evidence disagrees
- QUCSession.pinned_skills updated correctly
"""

from __future__ import annotations

from datetime import datetime

from lighthouse_ai.modes.quc import (
    QUCSession,
    _has_adjudicate,
    _parse_at_skills,
    _parse_sources_pin,
    _select_skills,
    ask,
)

FIXED_TS = datetime(2026, 5, 29, 12, 0, 0)


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #


def test_parse_sources_pin_extracts_skills():
    result = _parse_sources_pin("/sources arxiv,pubmed")
    assert result == ["arxiv", "pubmed"]


def test_parse_sources_pin_handles_spaces():
    result = _parse_sources_pin("/sources arxiv pubmed semantic_scholar")
    assert result == ["arxiv", "pubmed", "semantic_scholar"]


def test_parse_sources_pin_mixed_delimiters():
    result = _parse_sources_pin("/sources arxiv, pubmed, openalex")
    assert result == ["arxiv", "pubmed", "openalex"]


def test_parse_sources_pin_returns_none_when_absent():
    assert _parse_sources_pin("What is quantum entanglement?") is None


def test_parse_at_skills_single():
    assert _parse_at_skills("Tell me about @arxiv results") == ["arxiv"]


def test_parse_at_skills_multiple():
    skills = _parse_at_skills("Search @arxiv and @pubmed for cancer papers")
    assert "arxiv" in skills
    assert "pubmed" in skills


def test_parse_at_skills_none():
    assert _parse_at_skills("Plain question with no directives") == []


def test_has_adjudicate_true():
    assert _has_adjudicate("Is this claim correct? /adjudicate")


def test_has_adjudicate_false():
    assert not _has_adjudicate("Is this claim correct?")


def test_has_adjudicate_case_insensitive():
    assert _has_adjudicate("/ADJUDICATE this claim")


# --------------------------------------------------------------------------- #
# _select_skills priority ordering
# --------------------------------------------------------------------------- #


def _session(id_: str = "s1") -> QUCSession:
    return QUCSession(id=id_)


def test_at_skill_overrides_everything():
    session = _session()
    session.pinned_skills = ["pinned_skill"]
    result = _select_skills(
        "@my_skill check this",
        session,
        recommended_skills=["rec1", "rec2", "rec3"],
        pinned_skills=["pinned_skill"],
    )
    assert result == ["my_skill"]


def test_sources_pin_updates_session_and_returns():
    session = _session()
    result = _select_skills(
        "/sources arxiv,pubmed",
        session,
        recommended_skills=["rec1"],
        pinned_skills=None,
    )
    assert result == ["arxiv", "pubmed"]
    # Session should be updated for subsequent turns.
    assert session.pinned_skills == ["arxiv", "pubmed"]


def test_session_pinned_skills_sticky_across_turns():
    session = _session()
    session.pinned_skills = ["openalex", "semantic_scholar"]
    result = _select_skills(
        "What is the citation count?",
        session,
        recommended_skills=["rec1", "rec2"],
        pinned_skills=None,
    )
    assert result == ["openalex", "semantic_scholar"]


def test_caller_pinned_skills_used_when_no_session_pin():
    session = _session()
    result = _select_skills(
        "Normal question",
        session,
        recommended_skills=["rec1", "rec2", "rec3"],
        pinned_skills=["explicit_pin"],
    )
    assert result == ["explicit_pin"]


def test_recommended_skills_top_3_when_no_pin():
    session = _session()
    result = _select_skills(
        "Normal question",
        session,
        recommended_skills=["a", "b", "c", "d", "e"],
        pinned_skills=None,
    )
    assert result == ["a", "b", "c"]


def test_empty_skills_when_nothing_provided():
    session = _session()
    result = _select_skills(
        "Normal question",
        session,
        recommended_skills=None,
        pinned_skills=None,
    )
    assert result == []


# --------------------------------------------------------------------------- #
# ask() — gateway=None path unchanged
# --------------------------------------------------------------------------- #


def test_ask_no_gateway_draft_answer():
    session = QUCSession(id="sess-1")
    turn = ask(session, "What is quantum computing?")
    assert turn.role == "assistant"
    assert "[draft]" in turn.text
    assert "no LLM bound" in turn.text


def test_ask_no_gateway_citation_count_in_answer():
    session = QUCSession(id="sess-1")
    turn = ask(session, "What is quantum computing?")
    assert "Evidence chunks:" in turn.text


def test_ask_no_gateway_short_query_skips_retrieval():
    """Short queries (< retrieve_threshold words) skip retrieval."""

    class _FakeHybrid:
        def search(self, q, **kw):
            raise AssertionError("search should not be called for short queries")

    session = QUCSession(id="sess-1")
    # 2 words < default threshold of 4
    turn = ask(session, "hello world", hybrid=_FakeHybrid())  # type: ignore[arg-type]
    assert "Evidence chunks: 0" in turn.text


def test_ask_history_appended():
    session = QUCSession(id="sess-1")
    ask(session, "First question?")
    ask(session, "Second question?")
    roles = [t.role for t in session.history]
    assert roles == ["user", "assistant", "user", "assistant"]


# --------------------------------------------------------------------------- #
# ask() — skill selection integration
# --------------------------------------------------------------------------- #


def test_ask_sources_pin_updates_session():
    session = QUCSession(id="sess-skill")
    ask(session, "/sources arxiv,pubmed find me papers on CRISPR")
    assert session.pinned_skills == ["arxiv", "pubmed"]


def test_ask_at_skill_recorded_in_turn():
    session = QUCSession(id="sess-skill")
    turn = ask(session, "@arxiv search for quantum papers")
    assert "arxiv" in turn.skill_ids_used


def test_ask_recommended_skills_passed_through():
    session = QUCSession(id="sess-rec")
    turn = ask(
        session,
        "What are the latest papers on climate change?",
        recommended_skills=["openalex", "semantic_scholar", "arxiv"],
    )
    # Without a gateway, skill_ids_used should reflect the top-3 recommended.
    assert turn.skill_ids_used == ["openalex", "semantic_scholar", "arxiv"]


def test_ask_no_skills_when_nothing_provided():
    session = QUCSession(id="sess-noskill")
    turn = ask(session, "What is the capital of France?")
    assert turn.skill_ids_used == []


# --------------------------------------------------------------------------- #
# ask() — /adjudicate directive
# --------------------------------------------------------------------------- #


def test_ask_adjudicate_flag_set():
    session = QUCSession(id="sess-adj")
    turn = ask(session, "Is the sky blue? /adjudicate")
    assert turn.adjudicate_flag is True


def test_ask_adjudicate_flag_false_by_default():
    session = QUCSession(id="sess-adj")
    turn = ask(session, "Is the sky blue?")
    assert turn.adjudicate_flag is False


# --------------------------------------------------------------------------- #
# ask() — contradiction statement in answer
# --------------------------------------------------------------------------- #


class _FakeChunk:
    def __init__(self, cid: str, text: str, skill_id: str, entailment: float) -> None:
        self.id = cid
        self.text = text
        meta: dict = {"skill_id": skill_id}
        if entailment is not None:
            meta["entailment_score"] = entailment
        self.metadata = meta


class _FakeResult:
    def __init__(self, cid: str, text: str, skill_id: str, entailment: float) -> None:
        self.chunk = _FakeChunk(cid, text, skill_id, entailment)
        self.score = 1.0


class _FakeHybrid:
    """Returns a fixed set of contradicting results."""

    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = results

    def search(self, query: str, *, top_k: int = 5, **kw):
        return self._results[:top_k]


def test_ask_contradiction_stated_in_answer():
    """When retrieved evidence contradicts itself, a note appears in the answer."""
    hits = [
        _FakeResult("c1", "Remote work increases team productivity", "skill_a", 0.9),
        _FakeResult("c2", "Remote work decreases team productivity", "skill_b", 0.1),
    ]
    hybrid = _FakeHybrid(hits)
    session = QUCSession(id="sess-contra")
    turn = ask(
        session,
        "Does remote work affect productivity?",
        hybrid=hybrid,
        contradiction_timestamp=FIXED_TS,
    )
    # The contradiction note should appear somewhere in the answer text.
    assert "sources disagree" in turn.text.lower() or "note:" in turn.text.lower(), (
        f"Expected contradiction note in answer, got: {turn.text!r}"
    )


def test_ask_no_contradiction_note_when_evidence_agrees():
    """Agreeing evidence produces no note."""
    hits = [
        _FakeResult("c1", "Quantum computers are fast", "skill_a", 0.9),
        _FakeResult("c2", "Quantum computers are powerful", "skill_b", 0.8),
    ]
    hybrid = _FakeHybrid(hits)
    session = QUCSession(id="sess-agree")
    turn = ask(
        session,
        "Tell me about quantum computers quantum computing speed processors",
        hybrid=hybrid,
        contradiction_timestamp=FIXED_TS,
    )
    assert "sources disagree" not in turn.text.lower()
    assert "note:" not in turn.text.lower()


def test_ask_no_contradiction_without_timestamp():
    """Without contradiction_timestamp, the note step is skipped entirely."""
    hits = [
        _FakeResult("c1", "Remote work increases productivity", "skill_a", 0.9),
        _FakeResult("c2", "Remote work decreases productivity", "skill_b", 0.1),
    ]
    hybrid = _FakeHybrid(hits)
    session = QUCSession(id="sess-nots")
    turn = ask(
        session,
        "Does remote work affect productivity?",
        hybrid=hybrid,
        # no contradiction_timestamp
    )
    assert "sources disagree" not in turn.text.lower()


# --------------------------------------------------------------------------- #
# Turn dataclass stability
# --------------------------------------------------------------------------- #


def test_turn_has_skill_ids_used_field():
    session = QUCSession(id="s")
    turn = ask(session, "test question with enough words here")
    assert hasattr(turn, "skill_ids_used")
    assert isinstance(turn.skill_ids_used, list)


def test_turn_has_adjudicate_flag_field():
    session = QUCSession(id="s")
    turn = ask(session, "test question")
    assert hasattr(turn, "adjudicate_flag")
    assert isinstance(turn.adjudicate_flag, bool)


def test_quc_session_pinned_skills_starts_empty():
    session = QUCSession(id="s")
    assert session.pinned_skills == []


def test_session_add_backward_compatible():
    """session.add() still works with the old two-arg signature."""
    session = QUCSession(id="s")
    t = session.add("user", "hello")
    assert t.role == "user"
    assert t.text == "hello"
    assert t.citations == []
    assert t.skill_ids_used == []
    assert t.adjudicate_flag is False
