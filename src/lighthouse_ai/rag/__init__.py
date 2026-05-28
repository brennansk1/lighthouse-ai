"""RAG subsystem — chunking, embeddings, vector store, hybrid retrieval."""
from .bm25 import BM25Index
from .chunker import Chunk, Document, chunk_document
from .contextual import prepend_context
from .embedder import Embedder, HashEmbedder, cosine
from .flag_reranker import FlagReranker, RerankerUnavailable, make_reranker
from .fusion import reciprocal_rank_fusion
from .hybrid import HybridResult, HybridSearch
from .rerank import Reranker, ScoreReranker
from .store import InMemoryStore, SearchResult, VectorStore

__all__ = [
    "BM25Index",
    "Chunk",
    "Document",
    "Embedder",
    "FlagReranker",
    "HashEmbedder",
    "HybridResult",
    "HybridSearch",
    "InMemoryStore",
    "Reranker",
    "RerankerUnavailable",
    "ScoreReranker",
    "SearchResult",
    "VectorStore",
    "chunk_document",
    "cosine",
    "make_reranker",
    "prepend_context",
    "reciprocal_rank_fusion",
]
