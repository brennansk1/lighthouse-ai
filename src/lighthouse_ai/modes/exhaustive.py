"""Deep-tier exhaustive research — recursive question-tree decomposition.

The differentiator Claude/Gemini deep research can't match: they time-box to
~10-20 minutes. This engine instead decomposes a question into load-bearing
sub-questions, researches each, and *recursively decomposes* any sub-question
that itself surfaces load-bearing gaps — until every leaf is grounded or recorded
as an explicit known-unknown, bounded only by a user budget (max nodes / max
depth). Safe on local hardware because it is one bounded step at a time (the
caller drives it through the single RAM-gated gateway slot); long != heavy.

Deterministic + offline: decomposition uses the framing planner (deterministic
when ``gateway=None``); per-node research is an injectable ``research_fn`` so the
orchestration — the novel, must-be-correct part — is fully testable without a
model. Termination is guaranteed by the node/depth budget plus question dedup.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from ..framing.pipeline import run_framing

NodeStatus = Literal["grounded", "known_unknown"]

#: (body, citation_ids, grounded) for one node's research step.
ResearchFn = Callable[[str], tuple[str, list[int], bool]]


@dataclass
class TreeNode:
    question: str
    depth: int
    status: NodeStatus
    body: str = ""
    citations: list[int] = field(default_factory=list)
    children: list[TreeNode] = field(default_factory=list)


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

    @property
    def coverage_ratio(self) -> float:
        return round(self.grounded / self.total_nodes, 3) if self.total_nodes else 0.0


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


def _default_research_fn(question: str) -> tuple[str, list[int], bool]:
    """Deterministic offline stub: no corpus, so every node is a known-unknown.

    Real callers inject a research_fn that retrieves from the corpus and returns
    grounded=True with citation ids when evidence is found.
    """
    return (f"[draft] {question}", [], False)


def run_exhaustive(
    question: str,
    *,
    research_fn: ResearchFn | None = None,
    gateway=None,
    job_id: str | None = None,
    max_nodes: int = 25,
    max_depth: int = 3,
    on_node: Callable[[TreeNode, int, int], None] | None = None,
) -> ExhaustiveReport:
    """Run recursive question-tree research, bounded by ``max_nodes``/``max_depth``.

    ``research_fn(question) -> (body, citation_ids, grounded)`` researches a
    single node; defaults to an offline stub. ``on_node`` is a progress callback
    ``(node, done, total_seen)`` — used by the dispatcher to emit SSE progress.
    Returns an :class:`ExhaustiveReport` whose tree is always finite.
    """
    research = research_fn or _default_research_fn
    max_nodes = max(1, int(max_nodes))
    max_depth = max(0, int(max_depth))

    root = TreeNode(question=question, depth=0, status="known_unknown")
    seen: set[str] = {_norm(question)}
    queue: deque[TreeNode] = deque([root])
    all_nodes: list[TreeNode] = [root]
    truncated = False
    done = 0

    while queue:
        node = queue.popleft()

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
        except Exception:
            subs = []

        for sq in subs:
            if len(all_nodes) >= max_nodes:
                truncated = True
                break
            key = _norm(sq)
            if not key or key in seen:
                continue              # dedup → guarantees termination
            seen.add(key)
            child = TreeNode(question=sq, depth=node.depth + 1,
                             status="known_unknown")
            node.children.append(child)
            all_nodes.append(child)
            queue.append(child)

    grounded = sum(1 for n in all_nodes if n.status == "grounded")
    return ExhaustiveReport(
        root_question=question,
        root=root,
        total_nodes=len(all_nodes),
        grounded=grounded,
        known_unknowns=len(all_nodes) - grounded,
        max_depth_reached=max((n.depth for n in all_nodes), default=0),
        budget={"max_nodes": max_nodes, "max_depth": max_depth},
        truncated=truncated,
    )
