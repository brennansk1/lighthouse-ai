"""Deep-tier exhaustive research — recursive question-tree decomposition.

The differentiator Claude/Gemini deep research can't match: they time-box to
~10-20 minutes. This engine instead decomposes a question into load-bearing
sub-questions, researches each, and *recursively decomposes* any sub-question
that itself surfaces load-bearing gaps — until every leaf is grounded or recorded
as an explicit known-unknown, bounded only by a user budget (max nodes / max
depth). Safe on local hardware because it is one bounded step at a time (the
caller drives it through the single RAM-gated gateway slot); long != heavy.

Two things make the depth actually *good* rather than merely long:

  * **Value-of-information prioritization (gap #14)** — a uniform BFS spends the
    node budget on whatever it dequeued first, which on a tight budget can be
    shallow filler. Instead we score every pending node for decision-impact (is
    it load-bearing? how deep? how grounded was its parent?) and always research
    the highest-VOI node next, pruning nodes that score below a floor. So the
    budget lands on the branches that can actually flip the answer.

  * **Cross-node synthesis weaving (gap #8)** — a tree of grounded leaves is not
    an answer. After expansion we run a synthesis pass that weaves the node
    bodies into one coherent narrative (the gateway ``synthesizer`` role when
    present; a deterministic structured concatenation by tree traversal when
    not), surfaced on :attr:`ExhaustiveReport.synthesis`.

Deterministic + offline: decomposition uses the framing planner (deterministic
when ``gateway=None``); per-node research is an injectable ``research_fn`` so the
orchestration — the novel, must-be-correct part — is fully testable without a
model. Termination is guaranteed by the node/depth budget plus question dedup.
VOI ordering is a total order with stable tie-breaks, so a gateway-less run is
bit-for-bit reproducible.

**Resumable state (crash recovery).** A Deep run can be many minutes; a crash
mid-run should not throw away grounded leaves. :meth:`ExhaustiveReport.to_state`
/ :func:`tree_state_to_dict` / :func:`tree_state_from_dict` give a JSON-friendly
snapshot of the whole search state (the ``TreeNode`` tree + the pending frontier
+ the dedup seen-set + counters). Dispatcher-level checkpoint wiring (when/where
to persist, how to re-enter ``run_exhaustive`` from a snapshot) is out of scope
here — this module just provides the serializable surface and round-trip helpers.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from ..framing.pipeline import run_framing

NodeStatus = Literal["grounded", "known_unknown"]

#: (body, citation_ids, grounded) for one node's research step.
ResearchFn = Callable[[str], tuple[str, list[int], bool]]

#: Default minimum value-of-information for a pending node to be researched.
#: Nodes scoring below this are pruned (counted on the report) rather than
#: spending node budget. 0.0 keeps the old "research everything" behaviour.
DEFAULT_VOI_FLOOR = 0.0


@dataclass
class TreeNode:
    question: str
    depth: int
    status: NodeStatus
    body: str = ""
    citations: list[int] = field(default_factory=list)
    children: list[TreeNode] = field(default_factory=list)
    #: Whether framing flagged this node's question as load-bearing (its answer
    #: can flip the parent). Drives VOI; the root is load-bearing by definition.
    load_bearing: bool = False
    #: Value-of-information score this node was admitted with (0.0 for the root /
    #: nodes scored before VOI was computed). Recorded for transparency/debug.
    voi: float = 0.0


@dataclass
class ExhaustiveReport:
    root_question: str
    root: TreeNode
    total_nodes: int
    grounded: int
    known_unknowns: int
    max_depth_reached: int
    budget: dict
    truncated: bool  # True if the budget stopped expansion before completion
    #: Count of pending nodes pruned for scoring below ``voi_floor`` (gap #14).
    pruned: int = 0
    #: Woven cross-node narrative over the whole tree (gap #8). Empty only for a
    #: degenerate (no-body) tree.
    synthesis: str = ""

    @property
    def coverage_ratio(self) -> float:
        return round(self.grounded / self.total_nodes, 3) if self.total_nodes else 0.0

    def to_state(self) -> dict:
        """JSON-friendly snapshot of the *finished* tree, for resume/inspection.

        This serializes the completed tree (no pending frontier). For a snapshot
        of an *in-progress* search use :class:`TreeState` / :func:`tree_state_to_dict`.
        """
        return {
            "root_question": self.root_question,
            "root": _node_to_dict(self.root),
            "total_nodes": self.total_nodes,
            "grounded": self.grounded,
            "known_unknowns": self.known_unknowns,
            "max_depth_reached": self.max_depth_reached,
            "budget": dict(self.budget),
            "truncated": self.truncated,
            "pruned": self.pruned,
            "synthesis": self.synthesis,
        }


# --- serializable tree state (resume surface) ------------------------------


@dataclass
class TreeState:
    """A serializable snapshot of an in-progress exhaustive search.

    Captures everything needed to resume a crashed Deep run: the partially-built
    ``TreeNode`` tree (rooted at ``root``), the pending frontier (``pending`` —
    nodes scored but not yet researched), the dedup ``seen`` set, and the
    counters (``done``, ``truncated``, ``pruned``). The frontier and tree share
    node identity by a stable integer id assigned in creation order, so a node
    referenced in ``pending`` is the same object as in the tree after a
    round-trip.

    The dispatcher owns *when* to checkpoint and *how* to re-enter the engine
    from a snapshot; this type is only the data surface.
    """

    root: TreeNode
    pending: list[TreeNode] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)
    done: int = 0
    truncated: bool = False
    pruned: int = 0

    def to_dict(self) -> dict:
        return tree_state_to_dict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TreeState:
        return tree_state_from_dict(data)


def _node_to_dict(node: TreeNode) -> dict:
    return {
        "question": node.question,
        "depth": node.depth,
        "status": node.status,
        "body": node.body,
        "citations": list(node.citations),
        "load_bearing": node.load_bearing,
        "voi": node.voi,
        "children": [_node_to_dict(c) for c in node.children],
    }


def _node_from_dict(data: dict) -> TreeNode:
    return TreeNode(
        question=data["question"],
        depth=int(data["depth"]),
        status=data.get("status", "known_unknown"),
        body=data.get("body", ""),
        citations=list(data.get("citations", [])),
        load_bearing=bool(data.get("load_bearing", False)),
        voi=float(data.get("voi", 0.0)),
        children=[_node_from_dict(c) for c in data.get("children", [])],
    )


def tree_state_to_dict(state: TreeState) -> dict:
    """Serialize a :class:`TreeState` to a JSON-friendly dict.

    The pending frontier is stored as a list of node *paths* (sequences of child
    indices from the root), so a round-trip re-binds each pending entry to the
    same object inside the rebuilt tree — no duplication, identity preserved.
    """
    index: dict[int, list[int]] = {}
    _index_paths(state.root, [], index)
    pending_paths = [index[id(n)] for n in state.pending if id(n) in index]
    return {
        "version": 1,
        "root": _node_to_dict(state.root),
        "pending_paths": pending_paths,
        "seen": sorted(state.seen),
        "done": state.done,
        "truncated": state.truncated,
        "pruned": state.pruned,
    }


def tree_state_from_dict(data: dict) -> TreeState:
    """Rebuild a :class:`TreeState` from :func:`tree_state_to_dict` output."""
    root = _node_from_dict(data["root"])
    pending = [_node_at_path(root, p) for p in data.get("pending_paths", [])]
    pending = [n for n in pending if n is not None]
    return TreeState(
        root=root,
        pending=pending,  # type: ignore[arg-type]
        seen=set(data.get("seen", [])),
        done=int(data.get("done", 0)),
        truncated=bool(data.get("truncated", False)),
        pruned=int(data.get("pruned", 0)),
    )


def _index_paths(node: TreeNode, path: list[int], out: dict[int, list[int]]) -> None:
    out[id(node)] = list(path)
    for i, child in enumerate(node.children):
        _index_paths(child, [*path, i], out)


def _node_at_path(root: TreeNode, path: list[int]) -> TreeNode | None:
    node = root
    for i in path:
        if i < 0 or i >= len(node.children):
            return None
        node = node.children[i]
    return node


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


def _default_research_fn(question: str) -> tuple[str, list[int], bool]:
    """Deterministic offline stub: no corpus, so every node is a known-unknown.

    Real callers inject a research_fn that retrieves from the corpus and returns
    grounded=True with citation ids when evidence is found.
    """
    return (f"[draft] {question}", [], False)


# --- value-of-information scoring (gap #14) --------------------------------


def _voi_score(node: TreeNode, *, parent_grounded: bool, gateway=None,
               job_id: str | None = None) -> float:
    """Decision-impact score in [0, 1+] for a pending node — higher = research first.

    Deterministic heuristic (the always-on, must-be-correct path):
      * load-bearing nodes are worth far more (their answer can flip the parent);
      * a node under an *ungrounded* parent is worth more (we have a real gap to
        close there), one under a grounded parent slightly less;
      * value decays gently with depth — shallow nodes inform more of the tree.

    When a ``gateway`` is supplied we *nudge* the score with a model estimate but
    never let it dominate: the deterministic component is the floor of the order,
    so an offline run and an online run agree on the relative ranking of clearly
    high- vs low-impact branches. The gateway is optional and any failure is
    swallowed (offline result unchanged).
    """
    score = 0.2  # base
    if node.load_bearing:
        score += 0.6
    if not parent_grounded:
        score += 0.2  # an open gap under us is more valuable to close
    score += max(0.0, 0.25 - 0.08 * node.depth)  # shallow nodes inform more

    if gateway is not None:
        try:
            nudge = _voi_gateway_nudge(node, gateway=gateway, job_id=job_id)
            score += 0.1 * nudge  # bounded influence: ranking stays deterministic-led
        except Exception:
            pass
    return round(score, 6)


def _voi_gateway_nudge(node: TreeNode, *, gateway, job_id: str | None) -> float:
    """Ask the model for a 0..1 impact estimate; bounded, best-effort, optional."""
    prompt = (
        "Rate, as a single number between 0 and 1, how decision-relevant this "
        "sub-question is to answering a larger research question (1 = its answer "
        "could flip the conclusion, 0 = trivia). Reply with ONLY the number.\n\n"
        f"Sub-question: {node.question}"
    )
    resp = gateway.complete_structured(prompt, job_id=job_id)
    m = re.search(r"[01](?:\.\d+)?", resp.text.strip())
    if not m:
        return 0.0
    return max(0.0, min(1.0, float(m.group(0))))


def run_exhaustive(
    question: str,
    *,
    research_fn: ResearchFn | None = None,
    gateway=None,
    job_id: str | None = None,
    max_nodes: int = 25,
    max_depth: int = 3,
    on_node: Callable[[TreeNode, int, int], None] | None = None,
    voi_floor: float = DEFAULT_VOI_FLOOR,
    synthesize: bool = True,
) -> ExhaustiveReport:
    """Run recursive question-tree research, bounded by ``max_nodes``/``max_depth``.

    ``research_fn(question) -> (body, citation_ids, grounded)`` researches a
    single node; defaults to an offline stub. ``on_node`` is a progress callback
    ``(node, done, total_seen)`` — used by the dispatcher to emit SSE progress.

    Value-of-information ordering (gap #14): instead of a uniform BFS, pending
    nodes are scored for decision-impact and the highest-VOI node is researched
    next; nodes scoring below ``voi_floor`` are pruned (counted on
    ``report.pruned``). With ``gateway=None`` the order is fully deterministic
    (stable tie-breaks on creation order).

    Cross-node synthesis (gap #8): when ``synthesize`` is True the finished tree
    is woven into one narrative on ``report.synthesis`` — via the gateway
    ``synthesizer`` role when present, else a deterministic structured digest.

    Returns an :class:`ExhaustiveReport` whose tree is always finite.
    """
    research = research_fn or _default_research_fn
    max_nodes = max(1, int(max_nodes))
    max_depth = max(0, int(max_depth))

    root = TreeNode(question=question, depth=0, status="known_unknown",
                    load_bearing=True)  # the root question is load-bearing by definition
    seen: set[str] = {_norm(question)}
    all_nodes: list[TreeNode] = [root]
    # Pending frontier: (node, parent_grounded). We pop the highest-VOI node.
    # ``order`` is a monotonic creation counter for a stable tie-break, so the
    # ordering is a total order and a gateway-less run is reproducible.
    order = 0
    pending: list[tuple[TreeNode, bool, int]] = [(root, False, order)]
    truncated = False
    pruned = 0
    done = 0

    while pending:
        # VOI selection: pick the highest-scoring pending node. Tie-break on the
        # creation counter (lower = enqueued earlier) so the order is total and
        # deterministic when the gateway is absent.
        best_i = 0
        best_key: tuple[float, int] | None = None
        for i, (node, parent_grounded, ordr) in enumerate(pending):
            voi = _voi_score(node, parent_grounded=parent_grounded,
                             gateway=gateway, job_id=job_id)
            key = (voi, -ordr)  # higher VOI first; earlier creation breaks ties
            if best_key is None or key > best_key:
                best_key = key
                best_i = i
        node, parent_grounded, _ = pending.pop(best_i)
        node.voi = best_key[0] if best_key else 0.0

        # Prune below the floor — but never prune the root (we always answer the
        # question we were asked). Pruned nodes stay in the tree as recorded
        # known-unknowns (un-researched), and are counted on the report.
        if node is not root and node.voi < voi_floor:
            pruned += 1
            node.status = "known_unknown"
            node.body = node.body or f"[pruned: low value-of-information] {node.question}"
            continue

        # Research this node.
        try:
            body, citations, grounded = research(node.question)
        except Exception:
            body, citations, grounded = (f"[error] {node.question}", [], False)
        node.body = body
        node.citations = list(citations)
        node.status = "grounded" if grounded else "known_unknown"
        done += 1
        if on_node is not None:
            try:
                on_node(node, done, len(all_nodes))
            except Exception:
                pass

        # Decompose further only if we have depth + node budget left.
        if node.depth >= max_depth:
            continue
        if len(all_nodes) >= max_nodes:
            truncated = True
            continue

        try:
            framed = run_framing(node.question, gateway=gateway, job_id=job_id)
            subs = framed.load_bearing or framed.sub_questions
            load_bearing_set = {_norm(s) for s in framed.load_bearing}
        except Exception:
            subs = []
            load_bearing_set = set()

        for sq in subs:
            if len(all_nodes) >= max_nodes:
                truncated = True
                break
            key = _norm(sq)
            if not key or key in seen:
                continue              # dedup → guarantees termination
            seen.add(key)
            order += 1
            child = TreeNode(question=sq, depth=node.depth + 1,
                             status="known_unknown",
                             load_bearing=key in load_bearing_set)
            node.children.append(child)
            all_nodes.append(child)
            pending.append((child, grounded, order))

    grounded = sum(1 for n in all_nodes if n.status == "grounded")
    report = ExhaustiveReport(
        root_question=question,
        root=root,
        total_nodes=len(all_nodes),
        grounded=grounded,
        known_unknowns=len(all_nodes) - grounded,
        max_depth_reached=max((n.depth for n in all_nodes), default=0),
        budget={"max_nodes": max_nodes, "max_depth": max_depth,
                "voi_floor": voi_floor},
        truncated=truncated,
        pruned=pruned,
    )
    if synthesize:
        report.synthesis = synthesize_tree(root, gateway=gateway, job_id=job_id)
    return report


# --- cross-node synthesis weaving (gap #8) ---------------------------------


def _iter_tree(node: TreeNode):
    """Depth-first pre-order traversal yielding ``(node, ancestors)``.

    Ordered DFS so the narrative reads top-down, parent before children, in the
    order the tree was built.
    """
    out: list[tuple[TreeNode, tuple[TreeNode, ...]]] = []

    def _walk(n: TreeNode, anc: tuple[TreeNode, ...]) -> None:
        out.append((n, anc))
        for c in n.children:
            _walk(c, (*anc, n))

    _walk(node, ())
    return out


def synthesize_tree(root: TreeNode, *, gateway=None, job_id: str | None = None) -> str:
    """Weave the tree's node bodies into one coherent narrative (gap #8).

    With a ``gateway`` we hand the synthesizer role a structured outline of every
    node (question, body, citations, grounded/known-unknown status) and ask it to
    weave a single narrative that resolves overlaps, flags gaps, and preserves
    citations. With no gateway (or on any failure) we fall back to a deterministic
    structured digest produced by tree traversal — always non-empty for a tree
    that has any node bodies, and bit-for-bit reproducible.
    """
    digest = _deterministic_synthesis(root)
    if gateway is None:
        return digest
    try:
        prompt = _synthesis_prompt(root)
        resp = gateway.complete("synthesizer", prompt, job_id=job_id)
        woven = (resp.text or "").strip()
        return woven or digest
    except Exception:
        return digest


def _synthesis_prompt(root: TreeNode) -> str:
    lines = [
        "You are synthesizing a recursive research tree into one coherent report.",
        "Below is every node of the tree (indented by depth). For each: the "
        "sub-question, whether it is grounded in evidence or an open known-unknown, "
        "its citations, and a draft body.",
        "",
        "Weave a SINGLE flowing narrative that answers the root question:",
        "1. Lead with the root question's answer, supported by the grounded leaves.",
        "2. Merge overlapping sub-answers; do not repeat.",
        "3. Where the evidence is missing, surface it explicitly as a [GAP].",
        "4. Preserve [N] citation markers from the draft bodies.",
        "5. Do not invent facts beyond the draft bodies.",
        "",
        "TREE:",
    ]
    for node, ancestors in _iter_tree(root):
        indent = "  " * len(ancestors)
        status = "GROUNDED" if node.status == "grounded" else "OPEN"
        cites = f" cites={node.citations}" if node.citations else ""
        lines.append(f"{indent}- ({status}{cites}) Q: {node.question}")
        if node.body.strip():
            lines.append(f"{indent}  draft: {node.body.strip()}")
    return "\n".join(lines)


def _deterministic_synthesis(root: TreeNode) -> str:
    """Structured concatenation by tree traversal — the offline narrative.

    Produces a stable, readable digest: a header with coverage, then each node in
    pre-order with its status, body, and citations, indented by depth. This is
    deliberately not "prose" — it is the faithful, reproducible weave the model
    would otherwise polish.
    """
    nodes = _iter_tree(root)
    total = len(nodes)
    grounded = sum(1 for n, _ in nodes if n.status == "grounded")
    lines = [
        f"# Synthesis: {root.question}",
        "",
        f"Coverage: {grounded}/{total} sub-questions grounded in evidence.",
        "",
    ]
    for node, ancestors in nodes:
        depth = len(ancestors)
        prefix = "  " * depth
        tag = "[grounded]" if node.status == "grounded" else "[known-unknown]"
        heading = "##" + "#" * min(depth, 3)
        lines.append(f"{prefix}{heading} {tag} {node.question}")
        body = node.body.strip()
        if body:
            lines.append(f"{prefix}{body}")
        if node.citations:
            cites = ", ".join(f"[{c}]" for c in node.citations)
            lines.append(f"{prefix}Sources: {cites}")
        lines.append("")
    # Closing roll-up of the open gaps so the reader sees what's unresolved.
    gaps = [n.question for n, _ in nodes if n.status != "grounded"]
    if gaps:
        lines.append("## Open known-unknowns")
        for g in gaps:
            lines.append(f"- {g}")
    return "\n".join(lines).strip()
