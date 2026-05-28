"""Hybrid search orchestrator — design §14.4.

Pipeline:
  1. Dense ANN on the vector store (top 100).
  2. BM25 on the chunk corpus (top 100).
  3. RRF fusion (k=60).
  4. Optional freshness boost applied to RRF scores.
  5. Optional quality_class filter.
  6. MMR semantic deduplication.
  7. Reranker → top_k.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .bm25 import BM25Index
from .chunker import Chunk
from .embedder import Embedder
from .fusion import reciprocal_rank_fusion
from .rerank import Reranker
from .store import VectorStore


@dataclass(frozen=True)
class HybridResult:
    chunk: Chunk
    score: float
    dense_rank: int | None
    sparse_rank: int | None


def _freshness_boost(metadata: dict, *, half_life_days: float = 365.0) -> float:
    """Return a freshness multiplier in [0.85, 1.15] based on published_date.

    Recent papers get a small boost; older ones a small penalty.
    Returns 1.0 when published_date is absent.
    """
    pub = metadata.get("published_date") or metadata.get("published") or ""
    if not pub:
        return 1.0
    try:
        # Accept ISO date strings: "2024-03-15" or "2024-03-15T..."
        date_str = str(pub)[:10]
        pub_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_days = (now - pub_dt).days
        if age_days < 0:
            age_days = 0
        decay = math.exp(-age_days / half_life_days)  # 0..1
        # Map to [0.85, 1.15]
        return 0.85 + 0.30 * decay
    except (ValueError, TypeError):
        return 1.0


def _mmr_dedup(
    results: list[HybridResult],
    *,
    lambda_param: float = 0.7,
    similarity_threshold: float = 0.92,
) -> list[HybridResult]:
    """MMR deduplication: remove near-duplicates, keep diverse top results.

    Falls back to original order if embeddings unavailable.
    """
    if not results:
        return results

    # Check if embeddings are available on chunks
    if not hasattr(results[0].chunk, "embedding") or results[0].chunk.embedding is None:
        # No embeddings: fall back to text-based dedup (first 100 chars as key)
        seen_texts: set[str] = set()
        deduped = []
        for r in results:
            key = r.chunk.text[:100].lower().strip()
            if key not in seen_texts:
                seen_texts.add(key)
                deduped.append(r)
        return deduped

    import numpy as np

    def _cosine(a, b):
        a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    selected = []
    remaining = list(results)

    while remaining:
        if not selected:
            # Always pick the highest-scoring result first
            selected.append(remaining.pop(0))
            continue

        best_idx, best_score = 0, -float("inf")
        for i, candidate in enumerate(remaining):
            rel = candidate.score
            max_sim = max(
                _cosine(candidate.chunk.embedding, s.chunk.embedding)
                for s in selected
            )
            if max_sim >= similarity_threshold:
                # Near-duplicate: skip entirely
                score = -float("inf")
            else:
                score = lambda_param * rel - (1 - lambda_param) * max_sim
            if score > best_score:
                best_score, best_idx = score, i

        if best_score == -float("inf"):
            break  # all remaining are near-duplicates
        selected.append(remaining.pop(best_idx))

    return selected


class HybridSearch:
    def __init__(self, store: VectorStore, embedder: Embedder, bm25: BM25Index,
                 reranker: Reranker | None = None):
        self.store = store
        self.embedder = embedder
        self.bm25 = bm25
        self.reranker = reranker
        self._chunks_by_id: dict[str, Chunk] = {}

    def add(self, chunks: Iterable[Chunk]) -> None:
        chunks_list = list(chunks)
        if not chunks_list:
            return
        vectors = self.embedder.embed(c.text for c in chunks_list)
        self.store.upsert(chunks_list, vectors)
        self.bm25.add(chunks_list)
        for c in chunks_list:
            self._chunks_by_id[c.id] = c

    def search(self, query: str, *, top_k: int = 5, dense_k: int = 100,
               sparse_k: int = 100, filter: dict[str, Any] | None = None,
               min_quality_class: int | None = None,
               rerank_candidates: int | None = None) -> list[HybridResult]:
        q_vec = self.embedder.embed([query])[0]
        dense = self.store.search(q_vec, k=dense_k, filter=filter)
        sparse = self.bm25.search(query, k=sparse_k)

        dense_ranking = [r.chunk_id for r in dense]
        sparse_ranking = [chunk_id for chunk_id, _ in sparse]
        fused = reciprocal_rank_fusion([dense_ranking, sparse_ranking])

        dense_rank = {cid: i + 1 for i, cid in enumerate(dense_ranking)}
        sparse_rank = {cid: i + 1 for i, cid in enumerate(sparse_ranking)}

        # Resolve to chunks and apply filters.
        candidates: list[HybridResult] = []
        for cid, score in fused:
            chunk = self._chunks_by_id.get(cid)
            if chunk is None:
                # Could be a chunk we evicted; skip.
                continue
            if filter and not all(chunk.metadata.get(k) == v for k, v in filter.items()):
                continue
            if (min_quality_class is not None
                and int(chunk.metadata.get("quality_class", 0)) < min_quality_class):
                continue
            # Apply freshness boost to the RRF score.
            boosted_score = score * _freshness_boost(chunk.metadata)
            candidates.append(HybridResult(
                chunk=chunk, score=boosted_score,
                dense_rank=dense_rank.get(cid),
                sparse_rank=sparse_rank.get(cid),
            ))

        # Re-sort candidates by boosted score (freshness may have changed order).
        candidates.sort(key=lambda r: r.score, reverse=True)

        # MMR semantic deduplication after RRF fusion.
        candidates = _mmr_dedup(candidates)

        # Reranker on top of fused candidates. Cap the pool fed to the (costly)
        # cross-encoder to `rerank_candidates` by fusion order — the canonical
        # "retrieve N → rerank → top_k" shape (e.g. 50 → rerank → 8).
        if self.reranker is not None and candidates:
            pool = candidates[:rerank_candidates] if rerank_candidates else candidates
            reranked = self.reranker.rerank(query, [c.chunk for c in pool],
                                            top_k=top_k)
            return [HybridResult(chunk=ch, score=sc,
                                 dense_rank=dense_rank.get(ch.id),
                                 sparse_rank=sparse_rank.get(ch.id))
                    for ch, sc in reranked]
        return candidates[:top_k]
