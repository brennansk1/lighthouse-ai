# rag/

Retrieval-Augmented Generation subsystem (design §14): chunking, embedding,
BM25 + ANN hybrid retrieval with RRF fusion, contextual preamble injection,
cross-encoder reranking, and deterministic pre-context compaction.

## Public surface

- `hybrid.py` — `HybridSearch`, `HybridResult`. Orchestrates the full
  retrieval pipeline (§14.4): dense ANN top-100 → BM25 sparse top-100 →
  RRF fusion (k=60) → optional `quality_class` filter → reranker → top_k.
  `search` accepts `filter` (metadata equality) and `rerank_candidates`
  (pool cap for the cross-encoder, e.g. 50 → rerank → 8).
- `chunker.py` — `chunk_document`, `Chunk`, `Document`. Sentence-boundary
  chunker: 800-token target, 100-token overlap, code blocks and pipe-tables
  emitted whole. Chunk IDs are `{doc_id}:{pos:04d}:{uuid5_hex[:8]}`.
  Document metadata propagates to every child chunk (§14.2).
- `embedder.py` — `Embedder` (Protocol), `HashEmbedder`, `cosine`.
  Production backend is BGE-M3 via sentence-transformers. `HashEmbedder`
  is a deterministic, dependency-free fake for tests (bag-of-tokens → L2-
  normalized fixed-dim vector).
- `bm25.py` — `BM25Index`. Pure-Python Okapi BM25 (k1=1.2, b=0.75) over
  an in-memory chunk corpus. Identical math to Qdrant's native BM25 sparse
  encoder so the swap-in is mechanical.
- `store.py` — `VectorStore` (Protocol), `InMemoryStore`, `SearchResult`.
  `InMemoryStore` is a brute-force cosine-scan store for tests and tiers
  ≤ 10k chunks. Production uses `QdrantStore`.
- `qdrant_store.py` — `QdrantStore`. `VectorStore` Protocol backed by
  Qdrant: HNSW m=16 / ef_construct=100, scalar int8 quantization
  (`always_ram=True`), payload indexes on `source`, `grade`,
  `published_date`, `quality_class` (§14.15). Lazy client init; `.available()`
  probe for health checks.
- `compaction.py` — `compact`, `load_rules`, `CompactionRule`,
  `CompactionStats`, `BUILTIN_RULES`, `estimate_tokens`. Deterministic
  pre-context payload compaction (OpenHuman §5, TokenJuice-style): applies
  a three-layer rule overlay (builtin < user < project) of transforms
  (`html2md`, `dedupe_lines`, `shorten_urls`, `strip_boilerplate`,
  `regex_sub`) before text enters the LLM context. Grapheme-safe (operates
  on Unicode code points, never bytes).
- `contextual.py` — `prepend_context`, `llm_preamble_fn`, `default_preamble`.
  Anthropic Contextual Retrieval (§14.3): prepends a 50-100 token preamble
  to each chunk before embedding and BM25 indexing. `llm_preamble_fn`
  generates the preamble via the `aux_context` Gateway role (gated by an
  optional `SchedulerGate`); `default_preamble` is the deterministic
  metadata-only fallback.
- `rerank.py` — `Reranker` (Protocol), `ScoreReranker`. `ScoreReranker`
  is a stateless IDF-weighted token-overlap reranker used in tests;
  production swaps in `FlagReranker`.
- `flag_reranker.py` — `FlagReranker`, `RerankerUnavailable`, `make_reranker`.
  Cross-encoder reranker backed by FlagEmbedding (Qwen3-Reranker-0.6B /
  bge-reranker-v2-m3). Lazy import: `torch` and model weights are never
  loaded at module import time. Raises `RerankerUnavailable` (not a bare
  `ImportError`) when the dep is absent so callers can degrade cleanly.
  `make_reranker` returns `FlagReranker` when available, else `ScoreReranker`.
- `fusion.py` — `reciprocal_rank_fusion`. RRF score:
  `sum(1 / (k + rank_i))` with k=60 (Cormack et al. 2009).
- `ollama_embedder.py` — `OllamaEmbedder`. `Embedder` Protocol backed by
  Ollama `/api/embed`; default `nomic-embed-text` (768-dim); supports
  `bge-m3` (1024-dim) for multilingual + sparse + multi-vector (§14.1).
  Raises `OllamaUnavailable` on daemon unreachability; callers downgrade to
  `HashEmbedder`.

## Calls into

- `..gateway.Gateway` — `contextual.llm_preamble_fn` uses the
  `aux_context` LLM role to generate per-chunk preambles.
- `..governor.scheduler_gate.SchedulerGate` — `llm_preamble_fn` accepts
  an optional `gate` and wraps the preamble LLM call in a host-courtesy
  `permit()`.
- `..backends.ollama.OllamaBackend` — `OllamaEmbedder` delegates embed
  calls to the shared Ollama backend wrapper.

## Called by

- `..pipeline` — wires `HybridSearch` with the configured embedder, store,
  BM25 index, and reranker; calls `prepend_context` and `compact` during
  ingest.
- `..modes.deepdive` — `HybridSearch.search` retrieves per-section evidence
  in every TTD-DR round.
- `..modes.quc` — `HybridSearch.search` retrieves evidence for substantive
  user turns (query length ≥ `retrieve_threshold` words).

## Invariants

- `HybridSearch.search` is read-only after `add`; calling it on an empty
  index returns an empty list without error.
- `chunk_document` with `max_tokens ≤ 0` raises `ValueError`; all other
  inputs produce ≥ 1 chunk.
- `reciprocal_rank_fusion` is deterministic: same rankings always yield the
  same ordered output.
- `compact` operates on Unicode `str`, never `bytes`; multi-byte text is
  never split mid-character.
- `FlagReranker` loaded without a scorer and without `FlagEmbedding`
  installed raises `RerankerUnavailable`, never a bare `ImportError`.
- `OllamaEmbedder.embed` raises `OllamaUnavailable` on a dim mismatch
  (wrong model pulled), not a silent wrong-shape vector.
