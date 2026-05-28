"""Tests for Modes C (QUC), D (Digest), E (Debate)."""

from __future__ import annotations

from lighthouse_ai.modes.debate import (
    PERSPECTIVES,
    Perspective,
    run_debate,
)
from lighthouse_ai.modes.digest import aggregate_digest
from lighthouse_ai.modes.monitor import MonitorItem, MonitorReport, run_monitor
from lighthouse_ai.modes.quc import QUCSession, ask
from lighthouse_ai.rag import (
    BM25Index,
    Document,
    HashEmbedder,
    HybridSearch,
    InMemoryStore,
    chunk_document,
)

# --- QUC ---

def test_quc_session_records_turns():
    s = QUCSession(id="s1")
    turn = ask(s, "Hello")
    assert turn.role == "assistant"
    assert len(s.history) == 2  # user + assistant


def test_quc_retrieves_when_query_substantive():
    e = HashEmbedder(dim=64)
    hs = HybridSearch(InMemoryStore(), e, BM25Index())
    hs.add(chunk_document(Document(id="d", text="Quantum chips use qubits.")))
    s = QUCSession(id="s")
    turn = ask(s, "tell me about quantum computing chips", hybrid=hs)
    assert turn.citations  # at least one chunk retrieved


def test_quc_render_history_respects_budget():
    s = QUCSession(id="s")
    for i in range(100):
        s.add("user", f"msg {i}")
    rendered = s.render_history(max_chars=200)
    assert len(rendered) <= 250  # some slack for separators


# --- Digest ---

def test_digest_aggregates_topics():
    items = [MonitorItem(source="s1", url=f"https://x/{i}",
                         title=f"Title {i}", body="word " * 50)
             for i in range(5)]
    r1 = run_monitor("AI", items)
    r2 = run_monitor("Bio", items)
    d = aggregate_digest([r1, r2], period_label="2026-W21")
    assert d.period_label == "2026-W21"
    assert len(d.sections) == 2
    assert d.total_items >= 10


def test_digest_sections_sorted_by_alert_count():
    a = MonitorReport(topic="A", generated_at="t", alerts=[None] * 0,
                      digest=[], suppressed_duplicates=0, total_seen=0)
    b = MonitorReport(topic="B", generated_at="t",
                      alerts=[None, None, None],
                      digest=[], suppressed_duplicates=0, total_seen=0)
    d = aggregate_digest([a, b])
    assert d.sections[0].topic == "B"


# --- Debate ---

def test_debate_runs_every_perspective():
    result = run_debate("X causes Y.", "Draft text here.")
    assert len(result.responses) == len(PERSPECTIVES)
    for r in result.responses:
        assert r.critique


def test_debate_summary_reports_counts():
    result = run_debate("X.", "Draft.")
    assert "agree" in result.judge_summary
    assert str(len(result.responses)) in result.judge_summary


def test_debate_with_custom_perspectives():
    custom = (
        Perspective("foo", "always agrees",
                    "Argue '{claim}' is true (agree, proceed)."),
        Perspective("bar", "always refutes",
                    "Refute '{claim}' completely (fails, wrong)."),
    )
    res = run_debate("Hot is cold.", "Draft.", perspectives=custom)
    # The deterministic _heuristic_response uses perspective.stance which
    # contains "agrees" — so the agree predicate may return false because
    # of the absence of agreement keywords in the canned reply. We don't
    # assert on which way; just that both perspectives ran.
    assert {r.perspective.name for r in res.responses} == {"foo", "bar"}


def test_debate_agree_predicate_swappable():
    res = run_debate("X.", "Draft.",
                     agree_predicate=lambda c: True)
    assert all(r.agrees for r in res.responses)
    assert not res.disputes
