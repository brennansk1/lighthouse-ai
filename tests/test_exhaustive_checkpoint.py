"""Deep-tier checkpoint / resume (deployment gap #8), offline-deterministic.

A crashed or paused multi-hour Deep (exhaustive) run must resume from the last
completed node instead of restarting. These tests prove:

1. a :class:`TreeState` round-trips through the on-disk checkpoint file
   (write → read → ``from_dict`` rebuilds the same tree / frontier / seen-set);
2. a run that "crashes" after K nodes leaves a checkpoint, and resuming with
   ``resume_state`` completes WITHOUT re-researching the already-done nodes
   (no node is visited twice across the two runs);
3. a completed dispatcher run deletes its checkpoint;
4. the no-checkpoint path is a fresh run, bit-for-bit unchanged.

No network, no real LLM — ``research_fn`` is injected and ``gateway=None``.
"""

from __future__ import annotations

import json

import lighthouse_ai.dispatcher as dispatcher
from lighthouse_ai.dispatcher import (
    _PATHS_META_KEY,
    _adapt_investigate_deep,
    _checkpoint_path,
    _load_checkpoint,
    _write_checkpoint,
)
from lighthouse_ai.modes.exhaustive import (
    TreeState,
    run_exhaustive,
    tree_state_from_dict,
    tree_state_to_dict,
)
from lighthouse_ai.paths import make_paths

# --- (1) checkpoint file round-trip -----------------------------------------


def test_tree_state_round_trips_through_checkpoint_file(tmp_path):
    """write → read → from_dict rebuilds the same tree/frontier/seen-set."""
    rep = run_exhaustive(
        "Compare A versus B on the evidence that could change it",
        research_fn=lambda q: (f"body {q}", [1, 2], True),
        max_nodes=10, max_depth=2)
    frontier = [rep.root]
    if rep.root.children:
        frontier.append(rep.root.children[0])
    state = TreeState(root=rep.root, pending=frontier,
                      seen={"a", "b", "compare a versus b"},
                      done=3, truncated=rep.truncated, pruned=rep.pruned)

    paths = make_paths(tmp_path / "data")
    _write_checkpoint(paths, "job-1", state)

    # Persisted as JSON under data_dir/checkpoints/<job_id>.json.
    cp = _checkpoint_path(paths, "job-1")
    assert cp.exists()
    on_disk = json.loads(cp.read_text(encoding="utf-8"))
    assert on_disk == tree_state_to_dict(state)

    loaded = _load_checkpoint(paths, "job-1")
    assert loaded is not None
    restored = tree_state_from_dict(loaded)

    assert restored.root.question == rep.root.question
    assert len(restored.root.children) == len(rep.root.children)
    assert restored.root.citations == rep.root.citations
    assert restored.seen == state.seen
    assert restored.done == state.done
    assert restored.pruned == state.pruned
    # Frontier identity preserved against the rebuilt tree.
    assert restored.pending[0] is restored.root
    if len(frontier) > 1:
        assert restored.pending[1] is restored.root.children[0]


def test_load_checkpoint_absent_returns_none(tmp_path):
    paths = make_paths(tmp_path / "data")
    assert _load_checkpoint(paths, "no-such-job") is None


# --- (2) crash after K nodes, resume completes without double-research ------


def test_resume_does_not_revisit_already_done_nodes():
    """A run that 'crashes' (research_fn raises) after K nodes leaves a
    checkpoint; resuming completes the tree and NO node is researched twice."""
    visited_first: list[str] = []
    checkpoints: list[dict] = []

    K = 3  # hard-stop after K researched nodes

    # run_exhaustive swallows per-node research_fn exceptions (marks the node
    # errored), so to force a HARD stop mid-run we raise out of the checkpoint
    # hook after K successful nodes — simulating a process crash between nodes.
    crashed = False
    try:
        def on_checkpoint_crash(state: TreeState) -> None:
            checkpoints.append(tree_state_to_dict(state))
            if len(checkpoints) >= K:
                raise KeyboardInterrupt("simulated crash mid-run")

        run_exhaustive(
            "Compare option A versus option B for the migration decision",
            research_fn=lambda q: (visited_first.append(q) or (f"a {q}", [1], True)),
            max_nodes=12, max_depth=2, on_checkpoint=on_checkpoint_crash)
    except KeyboardInterrupt:
        crashed = True

    assert crashed, "expected the run to be interrupted mid-flight"
    assert checkpoints, "a checkpoint must have been written before the crash"
    assert len(visited_first) == K  # exactly K nodes researched before the crash

    # Resume from the last checkpoint. Record every question researched in run 2.
    visited_second: list[str] = []

    def research2(q: str):
        visited_second.append(q)
        return (f"a {q}", [1], True)

    rep = run_exhaustive(
        "Compare option A versus option B for the migration decision",
        research_fn=research2, max_nodes=12, max_depth=2,
        resume_state=checkpoints[-1])

    # No node is visited twice across the two runs.
    overlap = set(visited_first) & set(visited_second)
    assert not overlap, f"node(s) re-researched on resume: {overlap}"

    # The resumed run actually made progress (researched the remaining frontier).
    assert visited_second, "resume should have researched the pending frontier"

    # The completed tree's researched-node count equals run1 + run2 (each node
    # researched exactly once, total).
    all_questions = [n.question for n in _all(rep.root)]
    researched = visited_first + visited_second
    # every researched question is unique
    assert len(researched) == len(set(researched))
    # and the union covers the questions that got a real (non-empty) body
    assert set(researched).issubset(set(all_questions))


def test_resume_completion_equivalent_to_uninterrupted_run():
    """Crash+resume yields the same final tree as one uninterrupted run."""
    def research(q: str):
        return (f"answer {q}", [1], True)

    full = run_exhaustive("Compare A versus B for the team decision today",
                          research_fn=research, max_nodes=10, max_depth=2)

    # Interrupt after 2 checkpoints, then resume.
    snaps: list[dict] = []

    def hook(state: TreeState) -> None:
        snaps.append(tree_state_to_dict(state))
        if len(snaps) >= 2:
            raise KeyboardInterrupt

    try:
        run_exhaustive("Compare A versus B for the team decision today",
                       research_fn=research, max_nodes=10, max_depth=2,
                       on_checkpoint=hook)
    except KeyboardInterrupt:
        pass

    resumed = run_exhaustive("Compare A versus B for the team decision today",
                             research_fn=research, max_nodes=10, max_depth=2,
                             resume_state=snaps[-1])

    assert resumed.total_nodes == full.total_nodes
    assert resumed.grounded == full.grounded
    assert {n.question for n in _all(resumed.root)} == \
        {n.question for n in _all(full.root)}


# --- (3) a completed dispatcher run deletes its checkpoint ------------------


def test_completed_deep_run_deletes_checkpoint(tmp_path, monkeypatch):
    """Driving the Deep adapter to completion removes the checkpoint file."""
    # Avoid loading the real deepdive engine: stub run_deepdive to a deterministic
    # grounded section so the offline path is fast and self-contained.
    import lighthouse_ai.modes.deepdive as deepdive

    class _Sec:
        def __init__(self, q):
            self.body = f"finding for {q}"
            self.citations = [1]

    class _Rep:
        def __init__(self, q):
            self.sections = [_Sec(q)]

    monkeypatch.setattr(deepdive, "run_deepdive",
                        lambda q, **kw: _Rep(q), raising=True)

    paths = make_paths(tmp_path / "data")
    meta = {"topic": "Compare A versus B", "depth": "deep",
            "budget": "30m", _PATHS_META_KEY: paths}
    knobs = {"top_k": 4}

    out = _adapt_investigate_deep(meta, knobs, gateway=None, gate=None,
                                  job_id="deep-1")
    assert out["body_json"]["engine"] == "exhaustive"
    # Checkpoint was written during the run but removed on completion.
    assert not _checkpoint_path(paths, "deep-1").exists()


def test_failed_deep_run_leaves_checkpoint_for_resume(tmp_path, monkeypatch):
    """If the Deep run dies mid-flight the checkpoint survives so a retry resumes."""
    import lighthouse_ai.modes.deepdive as deepdive
    import lighthouse_ai.modes.exhaustive as exhaustive

    class _Sec:
        def __init__(self, q):
            self.body = f"finding for {q}"
            self.citations = [1]

    class _Rep:
        def __init__(self, q):
            self.sections = [_Sec(q)]

    monkeypatch.setattr(deepdive, "run_deepdive",
                        lambda q, **kw: _Rep(q), raising=True)

    # Force a hard crash after the first node is researched + checkpointed by
    # making framing raise *after* a checkpoint exists. Simpler: wrap the engine
    # so the first checkpoint write raises out of the adapter.
    real_run = exhaustive.run_exhaustive

    def boom_run(*a, on_checkpoint=None, **kw):
        def wrapped(state):
            if on_checkpoint:
                on_checkpoint(state)
            raise KeyboardInterrupt
        return real_run(*a, on_checkpoint=wrapped, **kw)

    monkeypatch.setattr(dispatcher, "run_exhaustive", boom_run, raising=False)
    # _adapt_investigate_deep imports run_exhaustive locally, so patch the source.
    monkeypatch.setattr(exhaustive, "run_exhaustive", boom_run, raising=True)

    paths = make_paths(tmp_path / "data")
    meta = {"topic": "Compare A versus B", "depth": "deep",
            "budget": "30m", _PATHS_META_KEY: paths}
    try:
        _adapt_investigate_deep(meta, {"top_k": 4}, gateway=None, gate=None,
                                job_id="deep-2")
    except KeyboardInterrupt:
        pass
    # The checkpoint persists (run never completed → not deleted).
    assert _checkpoint_path(paths, "deep-2").exists()


# --- (4) no-checkpoint path == fresh run unchanged --------------------------


def test_no_checkpoint_path_is_unchanged_fresh_run():
    """run_exhaustive with neither resume_state nor on_checkpoint is identical to
    a plain call (full back-compat)."""
    def research(q: str):
        return ("body", [1], True)

    a = run_exhaustive("Stable question on the evidence", research_fn=research,
                       max_nodes=10, max_depth=2)
    b = run_exhaustive("Stable question on the evidence", research_fn=research,
                       max_nodes=10, max_depth=2,
                       resume_state=None, on_checkpoint=None)
    assert a.to_state() == b.to_state()


def test_dispatcher_deep_run_without_paths_still_works():
    """Absent the private _paths meta key the Deep adapter degrades to a plain
    run (no checkpointing) and still produces a tree."""
    import lighthouse_ai.modes.deepdive as deepdive
    orig = deepdive.run_deepdive
    try:
        class _Rep:
            def __init__(self, q):
                self.sections = []

        deepdive.run_deepdive = lambda q, **kw: _Rep(q)  # type: ignore
        out = _adapt_investigate_deep(
            {"topic": "No paths here", "depth": "deep", "budget": "30m"},
            {"top_k": 4}, gateway=None, gate=None, job_id="nopaths")
        assert out["body_json"]["engine"] == "exhaustive"
    finally:
        deepdive.run_deepdive = orig


# --- helpers ----------------------------------------------------------------


def _all(root):
    out = [root]
    for c in root.children:
        out.extend(_all(c))
    return out
