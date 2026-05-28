"""Loop detection — the Governor's runaway-agent circuit breaker (design §24.6).

A 24/7 multi-agent system that can spawn sub-agents, recurse through LangGraph
nodes, and re-issue tool calls will, sooner or later, get stuck: the same query
fired in a tight loop, a recursion that never bottoms out, or a node that keeps
calling tools without making progress. Left unchecked these burn the cost budget
(§24.2) and, worse, can corrupt cross-store state through repeated side effects.

This module owns the *non-budgetary* loop guards so they live in one auditable
place rather than being scattered across the runtime. Per §24.6 the layers are:

  * Tool-call counters — a per-job global cap (default 1500 for the Exhaustive
    depth tier) and a tighter per-node cap (default 25). The global cap is the
    backstop; the per-node cap catches a single node spinning.
  * Recursion-depth ceiling — LangGraph node-call-stack depth (default 8). A
    deeper stack almost always means the planner is decomposing forever.
  * Exact-query repeat — the cheapest possible dedupe: hash the *normalized*
    query (case/whitespace folded) into a per-job set and block on the second
    sighting. Catches the common "ask the identical thing twice" loop.
  * Semantic-query repeat — exact-match misses paraphrases, so we also keep a
    bounded LRU of recent query embeddings and block when cosine similarity
    exceeds a threshold (default 0.95). We do not own an embedding model here:
    the caller passes embeddings (or an embed callable) so this module stays
    pure stdlib and testable without ML dependencies.

Everything returns an explicit :class:`LoopDecision` (allow/deny + reason)
rather than raising, so the runtime can fold refusals into ``GovernorWarning``
exactly the way the budget buckets do (§24.4).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import OrderedDict, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

# Defaults mirror the [governor.loops] block in §24.12 for the Exhaustive tier.
DEFAULT_PER_JOB_TOOL_CALLS: int = 1_500
DEFAULT_PER_NODE_TOOL_CALLS: int = 25
DEFAULT_RECURSION_DEPTH: int = 8
DEFAULT_SEMANTIC_THRESHOLD: float = 0.95
# Bounding the embedding LRU keeps memory flat over a 120-minute Exhaustive job;
# older queries are unlikely to be the target of a fresh loop.
DEFAULT_SEMANTIC_LRU_SIZE: int = 256

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class LoopConfig:
    """Tunable ceilings for one depth tier (§24.12 ``[governor.loops]``)."""

    per_job_tool_calls: int = DEFAULT_PER_JOB_TOOL_CALLS
    per_node_tool_calls: int = DEFAULT_PER_NODE_TOOL_CALLS
    recursion_depth: int = DEFAULT_RECURSION_DEPTH
    semantic_repeat_threshold: float = DEFAULT_SEMANTIC_THRESHOLD
    semantic_lru_size: int = DEFAULT_SEMANTIC_LRU_SIZE


LOOP_DEFAULTS = LoopConfig()


@dataclass(frozen=True)
class LoopDecision:
    """Allow/deny verdict for one loop-guard check.

    ``layer`` names the §24.6 mechanism that produced the verdict so the
    dashboard and audit log can attribute the trip without string-parsing the
    human-readable ``reason``.
    """

    allowed: bool
    layer: str = ""
    reason: str = ""
    detail: dict[str, float] = field(default_factory=dict)


def normalize_query(query: str) -> str:
    """Fold a query to its canonical form for exact-repeat hashing.

    Two queries that differ only in case or whitespace are, for loop-detection
    purposes, the same query. We do *not* stem or drop stopwords here — that is
    the semantic layer's job — so this stays a fast, deterministic backstop.
    """

    return _WHITESPACE_RE.sub(" ", query.strip().lower())


def query_hash(query: str) -> str:
    """Stable hash of the normalized query (sha256, hex) for the per-job set."""

    normalized = normalize_query(query)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two equal-length vectors.

    Returns 0.0 for a zero-norm vector rather than raising; a zero embedding
    carries no semantic signal and should never be treated as a repeat.
    """

    if len(a) != len(b):
        raise ValueError("embeddings must have equal dimensionality")
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class LoopDetector:
    """Per-detector instance enforcing the §24.6 loop guards across many jobs.

    A single instance is shared by the runtime; all per-job state is keyed on
    ``job_id`` so concurrent jobs never alias each other's counters or query
    sets. The detector is intentionally side-effect-free apart from its own
    in-memory bookkeeping — it makes a decision; the runtime acts on it.
    """

    def __init__(self, config: LoopConfig | None = None) -> None:
        self._config = config or LOOP_DEFAULTS
        self._job_calls: dict[str, int] = defaultdict(int)
        self._node_calls: dict[tuple[str, str], int] = defaultdict(int)
        self._seen_hashes: dict[str, set[str]] = defaultdict(set)
        # job_id -> ordered {query_hash: embedding}; OrderedDict gives us LRU.
        self._embeddings: dict[str, OrderedDict[str, list[float]]] = defaultdict(
            OrderedDict
        )

    @property
    def config(self) -> LoopConfig:
        return self._config

    # --- tool-call counters (§24.6 row 1) ---

    def record_call(self, job_id: str, node: str | None = None) -> LoopDecision:
        """Account for one tool call; deny once a per-job or per-node cap trips.

        The call is recorded *before* the check so the counter reflects reality
        even on the call that trips: the runtime should not execute this call,
        but the audit log must show that the attempt happened.
        """

        self._job_calls[job_id] += 1
        job_count = self._job_calls[job_id]
        if job_count > self._config.per_job_tool_calls:
            return LoopDecision(
                allowed=False,
                layer="tool_call_counter",
                reason=(
                    f"per-job tool-call cap exceeded "
                    f"({job_count} > {self._config.per_job_tool_calls})"
                ),
                detail={"job_calls": float(job_count)},
            )

        if node is not None:
            key = (job_id, node)
            self._node_calls[key] += 1
            node_count = self._node_calls[key]
            if node_count > self._config.per_node_tool_calls:
                return LoopDecision(
                    allowed=False,
                    layer="tool_call_counter",
                    reason=(
                        f"per-node tool-call cap exceeded for {node!r} "
                        f"({node_count} > {self._config.per_node_tool_calls})"
                    ),
                    detail={"node_calls": float(node_count)},
                )
            return LoopDecision(
                allowed=True,
                layer="tool_call_counter",
                detail={
                    "job_calls": float(job_count),
                    "node_calls": float(node_count),
                },
            )

        return LoopDecision(
            allowed=True,
            layer="tool_call_counter",
            detail={"job_calls": float(job_count)},
        )

    def job_call_count(self, job_id: str) -> int:
        return self._job_calls[job_id]

    def node_call_count(self, job_id: str, node: str) -> int:
        return self._node_calls[(job_id, node)]

    # --- recursion-depth ceiling (§24.6 row 2) ---

    def check_recursion(self, depth: int) -> LoopDecision:
        """Deny when the LangGraph node-call-stack is too deep.

        Depth is supplied by the runtime rather than tracked here because the
        call stack is owned by LangGraph; the Governor only enforces the
        ceiling. ``depth`` equal to the ceiling is allowed; exceeding it denies.
        """

        if depth > self._config.recursion_depth:
            return LoopDecision(
                allowed=False,
                layer="recursion_depth",
                reason=(
                    f"recursion depth {depth} exceeds ceiling "
                    f"{self._config.recursion_depth}"
                ),
                detail={"depth": float(depth)},
            )
        return LoopDecision(
            allowed=True, layer="recursion_depth", detail={"depth": float(depth)}
        )

    # --- exact-query repeat (§24.6 row 3) ---

    def seen_query(self, job_id: str, query: str) -> LoopDecision:
        """Record a query and deny if its normalized form was already seen.

        The first sighting is allowed and remembered; the second (and beyond)
        is denied. This is the cheap backstop — paraphrases slip past it and are
        caught by :meth:`check_semantic_repeat`.
        """

        digest = query_hash(query)
        seen = self._seen_hashes[job_id]
        if digest in seen:
            return LoopDecision(
                allowed=False,
                layer="exact_query_repeat",
                reason="exact (normalized) query already issued in this job",
                detail={"distinct_queries": float(len(seen))},
            )
        seen.add(digest)
        return LoopDecision(
            allowed=True,
            layer="exact_query_repeat",
            detail={"distinct_queries": float(len(seen))},
        )

    # --- semantic-query repeat (§24.6 row 4) ---

    def check_semantic_repeat(
        self,
        job_id: str,
        query: str,
        embed: Callable[[str], Sequence[float]] | Sequence[float],
    ) -> LoopDecision:
        """Deny when ``query`` is near-duplicate of a recent query (cosine > θ).

        ``embed`` may be either a precomputed embedding vector or a callable
        that produces one — the caller owns the model, keeping this module free
        of ML dependencies. New embeddings are added to a bounded LRU so a long
        Exhaustive job does not grow memory without bound.
        """

        vector = list(embed(query)) if callable(embed) else list(embed)
        lru = self._embeddings[job_id]
        threshold = self._config.semantic_repeat_threshold

        best_sim = 0.0
        for prior in lru.values():
            sim = cosine_similarity(vector, prior)
            if sim > best_sim:
                best_sim = sim
            if sim > threshold:
                return LoopDecision(
                    allowed=False,
                    layer="semantic_query_repeat",
                    reason=(
                        f"query cosine-similar to a prior query "
                        f"(cos {sim:.4f} > {threshold})"
                    ),
                    detail={"max_similarity": sim},
                )

        digest = query_hash(query)
        # Touch-as-MRU: re-inserting moves an existing key to the end.
        if digest in lru:
            lru.move_to_end(digest)
        lru[digest] = vector
        while len(lru) > self._config.semantic_lru_size:
            lru.popitem(last=False)

        return LoopDecision(
            allowed=True,
            layer="semantic_query_repeat",
            detail={"max_similarity": best_sim},
        )

    # --- lifecycle ---

    def reset_job(self, job_id: str) -> None:
        """Drop all per-job state once a job completes or is reset.

        Keeps the long-lived detector from leaking memory across the thousands
        of jobs a 24/7 instance runs, and ensures a re-run of the same job id
        starts from a clean slate after a budget reset (§24.5).
        """

        self._job_calls.pop(job_id, None)
        self._seen_hashes.pop(job_id, None)
        self._embeddings.pop(job_id, None)
        for key in [k for k in self._node_calls if k[0] == job_id]:
            self._node_calls.pop(key, None)
