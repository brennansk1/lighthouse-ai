"""Unit tests for the LoopDetector circuit breaker (design §24.6).

Covers: exact-query repeat, semantic-query repeat, tool-call counters,
recursion-depth ceiling, and the reset/clear lifecycle.
"""

from __future__ import annotations

import pytest

from lighthouse_ai.governor.loop_detector import (
    DEFAULT_RECURSION_DEPTH,
    DEFAULT_SEMANTIC_THRESHOLD,
    LoopConfig,
    LoopDecision,
    LoopDetector,
    cosine_similarity,
    normalize_query,
    query_hash,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit_vec(n: int, dim: int = 4) -> list[float]:
    """Return a unit vector with a 1.0 at position n (mod dim)."""
    v = [0.0] * dim
    v[n % dim] = 1.0
    return v


# ---------------------------------------------------------------------------
# normalize_query / query_hash
# ---------------------------------------------------------------------------


def test_normalize_folds_case_and_whitespace():
    assert normalize_query("  Hello   World  ") == "hello world"


def test_normalize_lowercases():
    assert normalize_query("UPPERCASE") == "uppercase"


def test_query_hash_is_deterministic():
    assert query_hash("some query") == query_hash("some query")


def test_query_hash_case_insensitive():
    assert query_hash("Hello") == query_hash("hello")


# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------


def test_cosine_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-9


def test_cosine_orthogonal_vectors():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(cosine_similarity(a, b)) < 1e-9


def test_cosine_zero_vector_returns_zero():
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_cosine_raises_on_dimension_mismatch():
    with pytest.raises(ValueError):
        cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# exact-query repeat (§24.6 row 3)
# ---------------------------------------------------------------------------


def test_short_non_repeating_sequence_does_not_trigger():
    det = LoopDetector()
    for q in ["What is inflation?", "How do interest rates work?", "Explain GDP."]:
        decision = det.seen_query("job1", q)
        assert decision.allowed is True


def test_repeated_query_triggers_detection():
    det = LoopDetector()
    q = "What caused the 2008 financial crisis?"
    first = det.seen_query("job1", q)
    assert first.allowed is True
    second = det.seen_query("job1", q)
    assert second.allowed is False
    assert second.layer == "exact_query_repeat"


def test_repeated_query_case_insensitive():
    det = LoopDetector()
    det.seen_query("j", "What is the capital of France?")
    decision = det.seen_query("j", "WHAT IS THE CAPITAL OF FRANCE?")
    assert decision.allowed is False


def test_different_jobs_dont_alias():
    det = LoopDetector()
    det.seen_query("job-A", "shared query")
    # Same query in a different job should be allowed on first sight.
    decision = det.seen_query("job-B", "shared query")
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# tool-call counters (§24.6 row 1)
# ---------------------------------------------------------------------------


def test_call_under_cap_is_allowed():
    cfg = LoopConfig(per_job_tool_calls=10, per_node_tool_calls=5)
    det = LoopDetector(config=cfg)
    decision = det.record_call("j1", node="search")
    assert decision.allowed is True


def test_call_over_per_job_cap_is_denied():
    cfg = LoopConfig(per_job_tool_calls=3, per_node_tool_calls=100)
    det = LoopDetector(config=cfg)
    for _ in range(3):
        det.record_call("j1")
    decision = det.record_call("j1")
    assert decision.allowed is False
    assert decision.layer == "tool_call_counter"


def test_call_over_per_node_cap_is_denied():
    cfg = LoopConfig(per_job_tool_calls=1000, per_node_tool_calls=2)
    det = LoopDetector(config=cfg)
    det.record_call("j1", node="fetch_url")
    det.record_call("j1", node="fetch_url")
    decision = det.record_call("j1", node="fetch_url")
    assert decision.allowed is False
    assert "fetch_url" in decision.reason


def test_different_nodes_dont_share_counter():
    cfg = LoopConfig(per_job_tool_calls=100, per_node_tool_calls=1)
    det = LoopDetector(config=cfg)
    # node A hits its cap
    det.record_call("j1", node="A")
    assert det.record_call("j1", node="A").allowed is False
    # node B is still fresh
    assert det.record_call("j1", node="B").allowed is True


# ---------------------------------------------------------------------------
# recursion-depth ceiling (§24.6 row 2)
# ---------------------------------------------------------------------------


def test_recursion_at_ceiling_is_allowed():
    det = LoopDetector()
    decision = det.check_recursion(DEFAULT_RECURSION_DEPTH)
    assert decision.allowed is True


def test_recursion_above_ceiling_is_denied():
    det = LoopDetector()
    decision = det.check_recursion(DEFAULT_RECURSION_DEPTH + 1)
    assert decision.allowed is False
    assert decision.layer == "recursion_depth"


# ---------------------------------------------------------------------------
# semantic-query repeat (§24.6 row 4)
# ---------------------------------------------------------------------------


def test_semantic_distinct_queries_allowed():
    det = LoopDetector()
    # Orthogonal embeddings → similarity 0 → always allowed
    for i in range(4):
        decision = det.check_semantic_repeat("j1", f"query {i}", embed=_unit_vec(i))
        assert decision.allowed is True


def test_semantic_identical_embedding_triggers():
    det = LoopDetector()
    vec = [0.6, 0.8, 0.0, 0.0]
    det.check_semantic_repeat("j1", "first query", embed=vec)
    # Same embedding → cosine 1.0 > threshold
    decision = det.check_semantic_repeat("j1", "paraphrased query", embed=vec)
    assert decision.allowed is False
    assert decision.layer == "semantic_query_repeat"


def test_semantic_callable_embed():
    """embed argument may be a callable rather than a pre-computed vector."""
    det = LoopDetector()
    call_count = 0

    def embed_fn(text: str) -> list[float]:
        nonlocal call_count
        call_count += 1
        return [1.0, 0.0, 0.0, 0.0]

    det.check_semantic_repeat("j1", "q1", embed=embed_fn)
    assert call_count == 1


# ---------------------------------------------------------------------------
# reset_job / lifecycle
# ---------------------------------------------------------------------------


def test_reset_clears_exact_query_state():
    det = LoopDetector()
    det.seen_query("j1", "repeating question")
    det.reset_job("j1")
    # After reset the same query should be allowed again
    decision = det.seen_query("j1", "repeating question")
    assert decision.allowed is True


def test_reset_clears_tool_call_counters():
    cfg = LoopConfig(per_job_tool_calls=1)
    det = LoopDetector(config=cfg)
    det.record_call("j1")
    det.reset_job("j1")
    decision = det.record_call("j1")
    assert decision.allowed is True


def test_reset_does_not_affect_other_jobs():
    det = LoopDetector()
    det.seen_query("j1", "shared topic")
    det.seen_query("j2", "shared topic")
    det.reset_job("j1")
    # j2 should still remember the query
    decision = det.seen_query("j2", "shared topic")
    assert decision.allowed is False


def test_reset_nonexistent_job_is_safe():
    det = LoopDetector()
    # Resetting a job that never existed should not raise.
    det.reset_job("ghost-job")
