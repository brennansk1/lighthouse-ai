"""Offline tests for Zone U — VOI prioritization, cross-node synthesis weaving,
and serializable resumable tree state. No network, no real LLM."""

from __future__ import annotations

from lighthouse_ai.modes.exhaustive import (
    TreeNode,
    TreeState,
    _voi_score,
    run_exhaustive,
    synthesize_tree,
    tree_state_from_dict,
    tree_state_to_dict,
)

# --- (1) VOI ordering: high-impact branch before low-impact -----------------


def test_voi_score_ranks_load_bearing_and_shallow_higher():
    """The deterministic VOI heuristic: load-bearing > non-load-bearing, shallow
    > deep, open-gap (ungrounded parent) > closed. This is the order the engine
    pops in."""
    lb_shallow = TreeNode("q", depth=1, status="known_unknown", load_bearing=True)
    nlb_shallow = TreeNode("q", depth=1, status="known_unknown", load_bearing=False)
    lb_deep = TreeNode("q", depth=3, status="known_unknown", load_bearing=True)

    s_lb = _voi_score(lb_shallow, parent_grounded=True)
    s_nlb = _voi_score(nlb_shallow, parent_grounded=True)
    s_lb_deep = _voi_score(lb_deep, parent_grounded=True)

    # load-bearing beats non-load-bearing at the same depth
    assert s_lb > s_nlb
    # shallow load-bearing beats deep load-bearing
    assert s_lb > s_lb_deep
    # an open gap (ungrounded parent) is worth more than a closed one
    assert _voi_score(nlb_shallow, parent_grounded=False) > s_nlb


def test_voi_researches_high_impact_branch_before_low_impact():
    """In a real run, the highest-VOI pending node is always researched next.
    Here the load-bearing depth-1 branch (VOI ~0.97) must be reached before its
    lower-VOI depth-2 descendants (VOI ~0.89) — VOI, not BFS depth/enqueue
    order, drives selection. We assert the global property: every node is
    visited only after every strictly-higher-VOI node already in the tree."""
    visited: list[TreeNode] = []

    def research(q: str):
        return (f"answer to {q}", [1], True)

    def on_node(node, done, total):
        visited.append(node)

    rep = run_exhaustive(
        "Compare option A versus option B for the migration",
        research_fn=research, max_nodes=12, max_depth=2, on_node=on_node,
    )

    # The tree must actually span multiple VOI levels for the test to bite.
    vois = sorted({round(n.voi, 3) for n in visited})
    assert len(vois) >= 2, "expected nodes at distinct VOI levels"

    # Property: visit order is non-increasing in VOI — a higher-VOI node is
    # never researched after a strictly-lower-VOI one. (Children only become
    # pending once their parent is researched, so this is the meaningful
    # 'spend budget on what matters first' guarantee.)
    visited_vois = [n.voi for n in visited]
    assert visited_vois == sorted(visited_vois, reverse=True)
    # And the root (load-bearing) is first.
    assert visited[0] is rep.root


def test_voi_ordering_is_deterministic_without_gateway():
    """Same inputs, gateway=None → identical visit order across runs."""
    def make_run():
        order: list[str] = []
        run_exhaustive("Compare X versus Y on the evidence",
                       research_fn=lambda q: (order.append(q) or ("b", [], True)),
                       max_nodes=10, max_depth=2)
        return order

    assert make_run() == make_run()


# --- (2) low-VOI nodes pruned below the floor -------------------------------


def test_low_voi_nodes_pruned_below_floor():
    """A high floor prunes the low-impact (non-load-bearing) pending nodes and
    records the count; load-bearing nodes survive."""
    researched: list[str] = []

    def research(q: str):
        researched.append(q)
        return (f"answer to {q}", [1], True)

    # A factual-survey root decomposes into non-load-bearing sub-questions
    # (VOI ~0.37 at depth 1). A floor of 0.5 prunes them; the root (VOI > 1) is
    # always researched. Pruned nodes are NOT passed to research_fn.
    rep = run_exhaustive(
        "What is the current state of the field today",
        research_fn=research, max_nodes=12, max_depth=1, voi_floor=0.5,
    )

    assert rep.pruned >= 1, "expected at least one low-VOI node pruned"
    # No pruned node body was produced by research(); pruned ones carry the
    # pruned marker and were never passed to research_fn.
    pruned_nodes = [c for c in rep.root.children
                    if c.body.startswith("[pruned")]
    assert len(pruned_nodes) == rep.pruned
    for n in pruned_nodes:
        assert n.question not in researched
        assert not n.load_bearing
    # The root is never pruned.
    assert rep.root.body.startswith("answer to")


def test_voi_floor_zero_prunes_nothing():
    rep = run_exhaustive("Compare A versus B on evidence",
                         research_fn=lambda q: ("x", [1], True),
                         max_nodes=10, max_depth=2, voi_floor=0.0)
    assert rep.pruned == 0


# --- (3) cross-node synthesis weaving ---------------------------------------


def test_synthesis_deterministic_non_empty_offline():
    rep = run_exhaustive("What is the state of local-first research tools?",
                         research_fn=lambda q: (f"finding for {q}", [7], True),
                         max_nodes=8, max_depth=1)
    assert rep.synthesis  # non-empty
    assert "Synthesis:" in rep.synthesis
    assert "Coverage:" in rep.synthesis
    # The root question and a citation marker survive into the narrative.
    assert "state of local-first research tools" in rep.synthesis
    assert "[7]" in rep.synthesis


def test_synthesis_is_reproducible_offline():
    def build():
        return run_exhaustive("Stable synthesis question on evidence",
                              research_fn=lambda q: ("body", [1], True),
                              max_nodes=8, max_depth=2).synthesis
    assert build() == build()


def test_synthesis_uses_gateway_when_provided():
    class FakeResp:
        text = "WOVEN-NARRATIVE: a single coherent report [1]."

    class FakeGateway:
        def __init__(self):
            self.calls = []

        def complete(self, role, prompt, *, job_id=None, allow_drift=True):
            self.calls.append((role, prompt))
            return FakeResp()

        def complete_structured(self, prompt, *, job_id=None, allow_drift=True):
            # Used by the VOI gateway nudge; return a neutral mid score.
            self.calls.append(("aux", prompt))
            return type("R", (), {"text": "0.5"})()

    gw = FakeGateway()
    root = TreeNode(question="Root", depth=0, status="grounded",
                    body="root body", citations=[1], load_bearing=True)
    out = synthesize_tree(root, gateway=gw)
    assert out == "WOVEN-NARRATIVE: a single coherent report [1]."
    # The synthesizer role was used.
    assert any(role == "synthesizer" for role, _ in gw.calls)


def test_synthesis_falls_back_to_digest_on_gateway_error():
    class BoomGateway:
        def complete(self, role, prompt, *, job_id=None, allow_drift=True):
            raise RuntimeError("model down")

    root = TreeNode(question="Root", depth=0, status="grounded",
                    body="root body", citations=[1])
    out = synthesize_tree(root, gateway=BoomGateway())
    assert "Synthesis: Root" in out  # deterministic digest, not a crash


# --- (4) serializable resumable tree state round-trips ----------------------


def test_tree_state_round_trips():
    rep = run_exhaustive("Compare A versus B on the evidence that could change it",
                         research_fn=lambda q: (f"body {q}", [1, 2], True),
                         max_nodes=10, max_depth=2)
    # Build an in-progress-style state: the finished tree, a frontier of two of
    # its real nodes, a seen-set, and counters.
    frontier_nodes = [rep.root]
    if rep.root.children:
        frontier_nodes.append(rep.root.children[0])
    state = TreeState(
        root=rep.root,
        pending=frontier_nodes,
        seen={"a", "b", "compare a versus b"},
        done=3,
        truncated=rep.truncated,
        pruned=rep.pruned,
    )

    data = tree_state_to_dict(state)
    # JSON-serializable.
    import json
    json.loads(json.dumps(data))

    restored = tree_state_from_dict(data)

    # Tree shape + payload preserved.
    assert restored.root.question == rep.root.question
    assert len(restored.root.children) == len(rep.root.children)
    assert restored.root.citations == rep.root.citations
    assert restored.seen == state.seen
    assert restored.done == state.done
    assert restored.pruned == state.pruned

    # Frontier identity preserved: each pending entry is the *same object* as the
    # corresponding node inside the restored tree (not a detached copy).
    assert restored.pending[0] is restored.root
    if len(frontier_nodes) > 1:
        assert restored.pending[1] is restored.root.children[0]


def test_tree_state_dataclass_helpers_match_module_fns():
    root = TreeNode(question="Q", depth=0, status="grounded", body="b",
                    citations=[9], load_bearing=True, voi=0.9)
    state = TreeState(root=root, pending=[root], seen={"q"}, done=1)
    assert state.to_dict() == tree_state_to_dict(state)
    restored = TreeState.from_dict(state.to_dict())
    assert restored.root.question == "Q"
    assert restored.root.voi == 0.9
    assert restored.pending[0] is restored.root


def test_voi_gateway_nudge_called_at_most_once_per_node(monkeypatch):
    """The frontier-selection loop must not re-nudge the same pending node on
    every pop: each node's VOI inputs are frozen at enqueue, so one LLM nudge
    per node suffices. Regression for the O(n^2) re-scoring of the frontier."""
    from lighthouse_ai.modes import exhaustive as ex

    nudged: list[str] = []

    def _fake_nudge(node, *, gateway, job_id, gate=None) -> float:
        nudged.append(node.question)
        return 0.5

    monkeypatch.setattr(ex, "_voi_gateway_nudge", _fake_nudge)
    report = ex.run_exhaustive(
        "root question?", gateway=object(),  # non-None → nudge path active
        max_nodes=10, max_depth=2, synthesize=False)
    assert report.total_nodes >= 3  # the stub fans out sub-questions
    # Every nudge target is distinct — no node was ever re-scored.
    assert len(nudged) == len(set(nudged))
