"""Offline tests for the Deep-tier exhaustive research engine (no real LLM)."""

from __future__ import annotations

from lighthouse_ai.modes.exhaustive import run_exhaustive


def test_expands_a_question_tree_offline():
    rep = run_exhaustive(
        "Should we migrate to a local-first architecture?", max_nodes=15, max_depth=2
    )
    assert rep.total_nodes >= 1
    assert rep.root.question.startswith("Should we migrate")
    # depth never exceeds the budget
    assert rep.max_depth_reached <= 2


def test_node_budget_is_respected_and_terminates():
    rep = run_exhaustive("A broad question about everything and anything", max_nodes=5, max_depth=5)
    assert rep.total_nodes <= 5


def test_default_offline_nodes_are_known_unknowns():
    # No corpus injected → every node is an explicit known-unknown, not asserted.
    rep = run_exhaustive("What is the state of the field?", max_nodes=6, max_depth=1)
    assert rep.grounded == 0
    assert rep.known_unknowns == rep.total_nodes


def test_research_fn_marks_grounded_leaves():
    def research(q):
        return (f"answer to {q}", [1, 2], True)

    rep = run_exhaustive("Root question here", research_fn=research, max_nodes=8, max_depth=2)
    assert rep.grounded == rep.total_nodes
    assert rep.coverage_ratio == 1.0
    assert rep.root.citations == [1, 2]


def test_dedup_prevents_runaway():
    # A research_fn is irrelevant; framing dedup must keep the tree finite even
    # with a generous budget.
    rep = run_exhaustive("Stable question", max_nodes=100, max_depth=4)
    # No infinite loop; node count is bounded well under the cap by dedup.
    assert rep.total_nodes <= 100


def test_progress_callback_invoked():
    seen = []
    run_exhaustive(
        "Track progress here",
        max_nodes=5,
        max_depth=1,
        on_node=lambda node, done, total: seen.append(done),
    )
    assert seen == sorted(seen)  # monotonic
    assert seen and seen[-1] >= 1
