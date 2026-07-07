"""RAG subsystem — chunking, embeddings, vector store, hybrid retrieval."""

from .bm25 import BM25Index
from .chunker import Chunk, Document, chunk_document
from .contextual import prepend_context
from .embedder import Embedder, HashEmbedder, cosine
from .flag_reranker import FlagReranker, RerankerUnavailable, make_reranker
from .fusion import reciprocal_rank_fusion
from .graph import (
    CorpusGraph,
    Edge,
    Node,
    build_corpus_graph,
    extract_entities,
)
from .hybrid import HybridResult, HybridSearch
from .rerank import Reranker, ScoreReranker
from .store import InMemoryStore, SearchResult, VectorStore

__all__ = [
    "BM25Index",
    "Chunk",
    "CorpusGraph",
    "Document",
    "Edge",
    "Embedder",
    "FlagReranker",
    "HashEmbedder",
    "HybridResult",
    "HybridSearch",
    "InMemoryStore",
    "Node",
    "Reranker",
    "RerankerUnavailable",
    "ScoreReranker",
    "SearchResult",
    "VectorStore",
    "build_corpus_graph",
    "chunk_document",
    "cosine",
    "extract_entities",
    "make_reranker",
    "prepend_context",
    "reciprocal_rank_fusion",
]
