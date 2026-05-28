"""RAG subsystem (design §14).

Sprint 5 ships the interfaces + in-memory implementations:
  * :class:`Document`, :class:`Chunk` — payload model.
  * :func:`chunk_document` — semantic-boundary + 800-token + 100-overlap.
  * :class:`Embedder` (Protocol) + :class:`HashEmbedder` (deterministic stub).
  * :class:`VectorStore` (Protocol) + :class:`InMemoryStore`.
  * :class:`BM25Index` — pure-Python BM25 over an in-memory corpus.
  * :func:`reciprocal_rank_fusion` — RRF with k=60.
  * :class:`Reranker` (Protocol) + :class:`ScoreReranker`.
  * :class:`HybridSearch` — orchestrates the design §14.4 pipeline.
  * :func:`prepend_context` — Anthropic contextual retrieval helper.

Real adapters (Qdrant, BGE-M3, Qwen3-Reranker) plug in by implementing the
Protocols and are wired in later sprints.
"""

from __future__ import annotations

from .chunker import chunk_document, Chunk, Document
from .embedder import Embedder, HashEmbedder
from .store import InMemoryStore, SearchResult, VectorStore
from .bm25 import BM25Index
from .fusion import reciprocal_rank_fusion
from .rerank import Reranker, ScoreReranker
from .hybrid import HybridSearch
from .contextual import prepend_context

__all__ = [
    "BM25Index",
    "Chunk",
    "Document",
    "Embedder",
    "HashEmbedder",
    "HybridSearch",
    "InMemoryStore",
    "Reranker",
    "ScoreReranker",
    "SearchResult",
    "VectorStore",
    "chunk_document",
    "prepend_context",
    "reciprocal_rank_fusion",
]
