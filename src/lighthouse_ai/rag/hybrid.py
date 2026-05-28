"""Hybrid search orchestrator — design §14.4.

Pipeline:
  1. Dense ANN on the vector store (top 100).
  2. BM25 on the chunk corpus (top 100).
  3. RRF fusion (k=60).
  4. Optional quality_class filter.
  5. Reranker → top_k.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .bm25 import BM25Index
from .chunker import Chunk
from .embedder import Embedder
from .fusion import reciprocal_rank_fusion
from .rerank import Reranker
from .store import SearchResult, VectorStore


@dataclass(frozen=True)
class HybridResult:
    chunk: Chunk
    score: float
    dense_rank: int | None
    sparse_rank: int | None


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
               min_quality_class: int | None = None) -> list[HybridResult]:
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
            candidates.append(HybridResult(
                chunk=chunk, score=score,
                dense_rank=dense_rank.get(cid),
                sparse_rank=sparse_rank.get(cid),
            ))

        # Reranker on top of fused candidates.
        if self.reranker is not None and candidates:
            reranked = self.reranker.rerank(query, [c.chunk for c in candidates],
                                            top_k=top_k)
            return [HybridResult(chunk=ch, score=sc,
                                 dense_rank=dense_rank.get(ch.id),
                                 sparse_rank=sparse_rank.get(ch.id))
                    for ch, sc in reranked]
        return candidates[:top_k]
