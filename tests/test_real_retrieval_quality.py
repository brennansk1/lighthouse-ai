"""Real retrieval quality gate — precision@5 with bge-m3 + FlagReranker.

Gated on LIGHTHOUSE_REAL_BACKEND=1 AND a reachable Ollama daemon (for
embeddings).  The FlagReranker sub-test additionally requires ``FlagEmbedding``
to be importable; it is further skipped when that package is absent.

Thresholds (from PRODUCTION_CHECKLIST.md §C):
  * precision@5 ≥ 0.40  — base (real bge-m3 embeddings, ScoreReranker fallback)
  * precision@5 ≥ 0.55  — with contextual retrieval / FlagReranker active
  * Skill-recommender recall@k is also exercised via eval/skill_eval.run_skill_eval

Run locally:
    LIGHTHOUSE_REAL_BACKEND=1 uv run python -m pytest tests/test_real_retrieval_quality.py -v
"""

from __future__ import annotations

import importlib.util
import os

import httpx
import pytest

# ---------------------------------------------------------------------------
# Shared skip guard
# ---------------------------------------------------------------------------


def _ollama_reachable() -> bool:
    try:
        with httpx.Client(timeout=2.0) as c:
            return c.get("http://127.0.0.1:11434/api/tags").status_code == 200
    except Exception:
        return False


_REAL_BACKEND_OK = (
    os.environ.get("LIGHTHOUSE_REAL_BACKEND") == "1"
    and _ollama_reachable()
)
_SKIP_REASON = (
    "set LIGHTHOUSE_REAL_BACKEND=1 and have ollama running on 127.0.0.1:11434"
)

_FLAG_EMBEDDING_AVAILABLE = importlib.util.find_spec("FlagEmbedding") is not None

pytestmark = pytest.mark.skipif(not _REAL_BACKEND_OK, reason=_SKIP_REASON)

# ---------------------------------------------------------------------------
# Thresholds (§ PRODUCTION_CHECKLIST "Deployment readiness / C")
# ---------------------------------------------------------------------------

_PRECISION_AT_5_BASE = 0.40     # minimum with real bge-m3, ScoreReranker
_PRECISION_AT_5_RERANKER = 0.55  # minimum when FlagReranker is active


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bge_m3_pulled() -> bool:
    """Return True if bge-m3 is in the Ollama model list."""
    try:
        from lighthouse_ai.backends.ollama import OllamaBackend

        b = OllamaBackend()
        if not b.available():
            return False
        return any("bge-m3" in m.name for m in b.list_models())
    except Exception:
        return False


def _build_real_embedder():
    """Construct an OllamaEmbedder backed by bge-m3 (1024-dim)."""
    from lighthouse_ai.backends.ollama import OllamaBackend
    from lighthouse_ai.rag.ollama_embedder import OllamaEmbedder

    return OllamaEmbedder(backend=OllamaBackend(), model="bge-m3", dim=1024)


# ---------------------------------------------------------------------------
# Test: base retrieval quality with real bge-m3 embeddings
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_retrieval_precision_bge_m3() -> None:
    """Golden-set precision@5 ≥ 0.40 with real bge-m3 embeddings."""
    if not _bge_m3_pulled():
        pytest.skip(
            "bge-m3 not pulled in Ollama — run: ollama pull bge-m3"
        )

    from lighthouse_ai.eval.golden import build_golden_set, build_index, evaluate
    from lighthouse_ai.rag.rerank import ScoreReranker
    from lighthouse_ai.rag.store import InMemoryStore

    golden = build_golden_set()
    embedder = _build_real_embedder()

    hybrid = build_index(
        golden,
        embedder=embedder,
        store=InMemoryStore(),
        reranker=ScoreReranker(),
    )

    metrics = evaluate(hybrid, golden, k=5)
    p5 = metrics["precision@5"]
    recall5 = metrics["recall@5"]
    mrr = metrics["mrr"]

    print(
        f"\n[bge-m3 base] precision@5={p5:.3f}  recall@5={recall5:.3f}  "
        f"mrr={mrr:.3f}  (threshold={_PRECISION_AT_5_BASE})"
    )

    assert p5 >= _PRECISION_AT_5_BASE, (
        f"precision@5 {p5:.3f} < threshold {_PRECISION_AT_5_BASE} "
        f"(recall@5={recall5:.3f}, mrr={mrr:.3f}).  "
        "Hint: check that bge-m3 is the correct model and the golden corpus "
        "is indexed with 1024-dim vectors."
    )


# ---------------------------------------------------------------------------
# Test: retrieval quality WITH FlagReranker (higher bar)
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(
    not _FLAG_EMBEDDING_AVAILABLE,
    reason="FlagEmbedding not installed — pip install FlagEmbedding to enable",
)
def test_retrieval_precision_with_flag_reranker() -> None:
    """Golden-set precision@5 ≥ 0.55 with bge-m3 + FlagReranker."""
    if not _bge_m3_pulled():
        pytest.skip("bge-m3 not pulled — run: ollama pull bge-m3")

    from lighthouse_ai.eval.golden import build_golden_set, build_index, evaluate
    from lighthouse_ai.rag.flag_reranker import FlagReranker
    from lighthouse_ai.rag.store import InMemoryStore

    golden = build_golden_set()
    embedder = _build_real_embedder()
    reranker = FlagReranker(model="BAAI/bge-reranker-v2-m3")

    if not reranker.available():
        pytest.skip("FlagReranker.available() returned False")

    hybrid = build_index(
        golden,
        embedder=embedder,
        store=InMemoryStore(),
        reranker=reranker,
    )

    metrics = evaluate(hybrid, golden, k=5)
    p5 = metrics["precision@5"]
    recall5 = metrics["recall@5"]
    mrr = metrics["mrr"]

    print(
        f"\n[bge-m3+FlagReranker] precision@5={p5:.3f}  recall@5={recall5:.3f}  "
        f"mrr={mrr:.3f}  (threshold={_PRECISION_AT_5_RERANKER})"
    )

    assert p5 >= _PRECISION_AT_5_RERANKER, (
        f"precision@5 {p5:.3f} < threshold {_PRECISION_AT_5_RERANKER} "
        f"(recall@5={recall5:.3f}, mrr={mrr:.3f}).  "
        "Hint: verify BAAI/bge-reranker-v2-m3 weights are cached and that "
        "FlagReranker.compute_score is returning sensible relevance scores."
    )


# ---------------------------------------------------------------------------
# Test: skill-recommender recall@k (offline metric, but run here for full
# real-env validation report)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_skill_recommender_recall_at_k() -> None:
    """Skill-recommender recall@k ≥ 0.50 on the built-in held-out set.

    This metric is offline-deterministic (token overlap, no network) but is
    included in the real-backend suite so the full quality report is produced
    together.  Threshold 0.50: the recommender should surface the correct skill
    in the top-5 for at least half the held-out cases.
    """
    from lighthouse_ai.eval.skill_eval import run_skill_eval

    result = run_skill_eval(k=5)
    macro = result["macro_recall"]
    n = result["n_cases"]

    print(
        f"\n[skill-recommender] macro_recall@5={macro:.3f}  n_cases={n}"
    )
    if result["note"]:
        print(f"  note: {result['note']}")

    # Only assert when the library is populated (n_scored > 0).
    if result["n_scored"] == 0:
        pytest.skip("Skill library is empty — no skills to evaluate")

    assert macro >= 0.50, (
        f"Skill-recommender recall@5 {macro:.3f} < 0.50.  "
        f"Per-skill breakdown: {result['per_skill']}"
    )
