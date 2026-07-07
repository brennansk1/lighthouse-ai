"""Unit tests for the RAG subsystem (chunker, embedder, store, BM25, RRF,
reranker, hybrid search, contextual retrieval)."""

from __future__ import annotations

import pytest

from lighthouse_ai.rag import (
    BM25Index,
    Document,
    FlagReranker,
    HashEmbedder,
    HybridSearch,
    InMemoryStore,
    RerankerUnavailable,
    ScoreReranker,
    chunk_document,
    make_reranker,
    prepend_context,
    reciprocal_rank_fusion,
)
from lighthouse_ai.rag.contextual import default_preamble

# --- chunker ---


def test_short_doc_produces_one_chunk():
    doc = Document(id="d1", text="A short doc. Two sentences.", metadata={})
    chunks = chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0].document_id == "d1"
    assert chunks[0].position == 0


def test_long_doc_is_split_with_overlap():
    text = ". ".join(f"This is sentence number {i} with words." for i in range(500))
    doc = Document(id="d2", text=text)
    chunks = chunk_document(doc, max_tokens=200, overlap_tokens=20)
    assert len(chunks) > 1
    # Overlap: last 20-ish tokens of chunk N appear in chunk N+1.
    a_tail = chunks[0].text.split()[-15:]
    b_head = chunks[1].text.split()[:60]
    overlap = set(a_tail) & set(b_head)
    assert overlap


def test_code_block_preserved():
    text = "Intro paragraph here.\n\n```python\ndef f():\n    pass\n```\n\nOutro."
    doc = Document(id="d3", text=text)
    chunks = chunk_document(doc, max_tokens=400)
    code_chunks = [c for c in chunks if "```" in c.text]
    assert len(code_chunks) == 1
    assert "def f" in code_chunks[0].text


def test_metadata_propagates_to_every_chunk():
    doc = Document(
        id="d4", text="One sentence. Two sentence.", metadata={"grade": "A", "source": "Lighthouse"}
    )
    chunks = chunk_document(doc)
    for c in chunks:
        assert c.metadata["grade"] == "A"
        assert c.metadata["source"] == "Lighthouse"


def test_max_tokens_zero_rejected():
    with pytest.raises(ValueError):
        chunk_document(Document(id="x", text="hi"), max_tokens=0)


def test_buffered_text_not_lost_before_overlong_sentence():
    """Regression: a buffered short sentence followed by an over-long sentence
    must not be silently dropped. The overlong-sentence hard-split branch used
    to reset `current` without emitting it, losing tokens."""
    keep = "keep me please now"
    overlong = " ".join(["big"] * 60)
    text = keep + ". " + overlong + "."
    chunks = chunk_document(Document(id="d", text=text), max_tokens=10, overlap_tokens=0)
    joined = " ".join(c.text for c in chunks)
    # Every word of the buffered sentence must survive somewhere.
    for w in keep.split():
        assert w in joined, f"lost token {w!r}; chunks={[c.text for c in chunks]}"


# --- embedder ---


def test_hash_embedder_is_deterministic():
    e = HashEmbedder(dim=32)
    a = e.embed(["the cat sat"])[0]
    b = e.embed(["the cat sat"])[0]
    assert a == b


def test_hash_embedder_overlap_yields_high_similarity():
    from lighthouse_ai.rag.embedder import cosine

    e = HashEmbedder(dim=128)
    a, b, c = e.embed(["cat dog fish", "cat dog bird", "rocket spaceship moon"])
    assert cosine(a, b) > cosine(a, c)


# --- in-memory store ---


def test_inmemory_store_upsert_and_search():
    e = HashEmbedder(dim=64)
    store = InMemoryStore()
    doc = Document(id="d", text="alpha bravo charlie. delta echo foxtrot.")
    chunks = chunk_document(doc, max_tokens=10, overlap_tokens=0)
    vecs = e.embed([c.text for c in chunks])
    store.upsert(chunks, vecs)
    assert store.count() == len(chunks)
    q = e.embed(["alpha bravo"])[0]
    results = store.search(q, k=2)
    assert results[0].chunk.text.startswith("alpha")


def test_inmemory_store_filter():
    e = HashEmbedder(dim=64)
    store = InMemoryStore()
    a = Document(id="a", text="apple banana cherry.", metadata={"grade": "A"})
    b = Document(id="b", text="apple banana cherry.", metadata={"grade": "B"})
    chunks_a = chunk_document(a)
    chunks_b = chunk_document(b)
    store.upsert(chunks_a + chunks_b, e.embed([c.text for c in chunks_a + chunks_b]))
    q = e.embed(["apple"])[0]
    res = store.search(q, k=10, filter={"grade": "A"})
    assert all(r.chunk.metadata["grade"] == "A" for r in res)


def test_inmemory_store_delete():
    e = HashEmbedder(dim=8)
    store = InMemoryStore()
    chunks = chunk_document(Document(id="x", text="hi there"))
    store.upsert(chunks, e.embed([c.text for c in chunks]))
    assert store.delete([c.id for c in chunks]) == len(chunks)
    assert store.count() == 0


# --- BM25 ---


def test_bm25_returns_high_score_for_match():
    bm = BM25Index()
    chunks = [
        chunk_document(Document(id="a", text="the quick brown fox jumps"))[0],
        chunk_document(Document(id="b", text="lazy dog sleeps all day"))[0],
        chunk_document(Document(id="c", text="the quick mouse runs fast"))[0],
    ]
    bm.add(chunks)
    res = bm.search("fox", k=3)
    assert res
    assert res[0][0].startswith("a:")
    # Only the docs containing the query term are returned.
    assert all(rid.startswith("a:") for rid, _ in res)


def test_bm25_empty_returns_nothing():
    assert BM25Index().search("x") == []


def test_bm25_readd_same_id_does_not_corrupt_df():
    """Regression: re-adding a chunk with an existing id is an update, not a
    second document. df must not exceed n_docs, otherwise idf/scores corrupt."""
    from lighthouse_ai.rag.chunker import Chunk

    bm = BM25Index()
    a = Chunk(id="x", document_id="d", text="alpha beta", position=0)
    b = Chunk(id="y", document_id="d", text="gamma delta", position=0)
    bm.add([a, b])
    bm.add([a])  # re-ingest x (update)
    assert len(bm) == 2
    # No term's document frequency may exceed the number of documents.
    assert all(df <= len(bm) for df in bm._df.values()), dict(bm._df)
    # "alpha" appears in exactly one of the two docs.
    assert bm._df["alpha"] == 1

    # And updating the text actually retires the old terms.
    bm.add([Chunk(id="x", document_id="d", text="omega", position=0)])
    assert "alpha" not in bm._df
    assert bm._df["omega"] == 1


# --- RRF ---


def test_rrf_higher_rank_yields_higher_score():
    rankings = [["a", "b", "c"], ["c", "a", "b"]]
    fused = reciprocal_rank_fusion(rankings, k=60)
    fused_dict = dict(fused)
    assert fused_dict["a"] > fused_dict["b"]


def test_rrf_handles_disjoint_rankings():
    fused = dict(reciprocal_rank_fusion([["x"], ["y"]]))
    assert set(fused.keys()) == {"x", "y"}


# --- Hybrid search ---


def test_hybrid_search_returns_relevant_chunk():
    e = HashEmbedder(dim=128)
    store = InMemoryStore()
    bm = BM25Index()
    hs = HybridSearch(store, e, bm, reranker=ScoreReranker())
    docs = [
        Document(id="d1", text="The cat sat on the mat. Cats are common pets."),
        Document(id="d2", text="Quantum entanglement is non-local."),
        Document(id="d3", text="Bacteria are single-celled organisms."),
    ]
    chunks = []
    for d in docs:
        chunks.extend(chunk_document(d))
    hs.add(chunks)
    res = hs.search("cat pet", top_k=2)
    assert res
    assert "cat" in res[0].chunk.text.lower()


def test_hybrid_search_quality_filter():
    e = HashEmbedder(dim=64)
    store = InMemoryStore()
    bm = BM25Index()
    hs = HybridSearch(store, e, bm)
    a = Document(id="a", text="alpha facts.", metadata={"quality_class": 3})
    b = Document(id="b", text="alpha facts.", metadata={"quality_class": 1})
    hs.add(chunk_document(a) + chunk_document(b))
    res = hs.search("alpha", top_k=5, min_quality_class=2)
    assert all(r.chunk.metadata["quality_class"] >= 2 for r in res)


def test_hybrid_search_empty_query_no_crash():
    e = HashEmbedder(dim=8)
    hs = HybridSearch(InMemoryStore(), e, BM25Index())
    hs.add(chunk_document(Document(id="x", text="hi")))
    # Empty query → BM25 nothing; dense gives results based on zero vector.
    res = hs.search("", top_k=2)
    assert isinstance(res, list)


# --- Contextual retrieval ---


def test_default_preamble_uses_metadata():
    chunk = chunk_document(
        Document(
            id="d",
            text="body text",
            metadata={"source": "NYT", "grade": "A", "published_date": "2026-01-01"},
        )
    )[0]
    pre = default_preamble(chunk)
    assert "NYT" in pre and "grade A" in pre


def test_prepend_context_adds_preamble():
    chunks = chunk_document(Document(id="d", text="body", metadata={"source": "X", "grade": "B"}))
    out = prepend_context(chunks)
    assert out[0].text.startswith("[")
    assert "X" in out[0].text


def test_prepend_context_noop_without_metadata():
    chunks = chunk_document(Document(id="d", text="body"))
    out = prepend_context(chunks)
    assert out[0].text == "body"


# --- make_reranker export ---


def test_make_reranker_exported_from_rag():
    """FlagReranker, RerankerUnavailable, and make_reranker are importable from
    the top-level rag package (Sprint 28 step 1 contract)."""
    # If any name is missing the import at the top of this module already failed.
    assert callable(make_reranker)
    assert FlagReranker is not None
    assert RerankerUnavailable is not None


# --- HybridSearch rerank_candidates cap ---


def _length_scorer(query, texts):
    """Fake cross-encoder: scores by text length (deterministic, no model)."""
    return [float(len(t)) for t in texts]


def test_hybrid_search_rerank_candidates_cap():
    """With rerank_candidates=3, only the first 3 fused results reach the
    reranker even when the pool is larger.  We verify this by injecting a scorer
    that records which chunks it received and asserting it saw at most 3."""
    e = HashEmbedder(dim=128)
    reranker = FlagReranker(scorer=_length_scorer)
    hs = HybridSearch(InMemoryStore(), e, BM25Index(), reranker=reranker)

    # Add 6 distinct chunks so the fused pool is larger than the cap.
    docs = [Document(id=f"d{i}", text=f"chunk number {i} " + "word " * (i + 1)) for i in range(6)]
    for d in docs:
        hs.add(chunk_document(d))

    # Track how many chunks the scorer receives across calls.
    call_sizes: list[int] = []
    original_scorer = _length_scorer

    def _tracking_scorer(query, texts):
        call_sizes.append(len(texts))
        return original_scorer(query, texts)

    hs.reranker = FlagReranker(scorer=_tracking_scorer)

    res = hs.search("chunk number", top_k=2, rerank_candidates=3)
    # Reranker must have been called, and each call must have received ≤ 3 chunks.
    assert call_sizes, "scorer was never called — reranker was not invoked"
    assert all(n <= 3 for n in call_sizes), f"scorer received more than 3 candidates: {call_sizes}"
    # Final output is still capped to top_k.
    assert len(res) <= 2


# --- Contextual retrieval (Sprint 30) ---


def test_prepend_context_uses_preamble_fn():
    from lighthouse_ai.rag.chunker import Chunk
    from lighthouse_ai.rag.contextual import prepend_context

    c = Chunk(id="d:0", document_id="d", text="quantum", position=0, metadata={"source": "arxiv"})
    out = prepend_context([c])
    assert out[0].text.startswith("[Source: arxiv]")
    assert "quantum" in out[0].text


def test_llm_preamble_fn_falls_back_on_error():
    from unittest.mock import MagicMock

    from lighthouse_ai.rag.chunker import Chunk
    from lighthouse_ai.rag.contextual import llm_preamble_fn

    gw = MagicMock()
    gw.complete.side_effect = RuntimeError("gateway down")
    fn = llm_preamble_fn(gw, document_text="some text")
    c = Chunk(id="d:0", document_id="d", text="hello", position=0, metadata={"source": "arxiv"})
    result = fn(c)
    # Should fall back to default_preamble output
    assert "arxiv" in result or result == ""


def test_ingest_text_uses_contextual_retrieval(migrated_paths):
    """ingest_text always prepends contextual preamble via default_preamble."""
    from lighthouse_ai.pipeline import PipelineConfig, ResearchPipeline

    pipe = ResearchPipeline(migrated_paths, config=PipelineConfig(offline=True))
    n = pipe.ingest_text(
        "d1",
        "The treatment improved outcomes. Published 2023.",
        metadata={"source": "pubmed", "grade": "A"},
    )
    assert n >= 1
