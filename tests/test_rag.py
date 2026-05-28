"""Unit tests for the RAG subsystem (chunker, embedder, store, BM25, RRF,
reranker, hybrid search, contextual retrieval)."""

from __future__ import annotations

import pytest

from lighthouse_ai.rag import (
    BM25Index,
    Document,
    HashEmbedder,
    HybridSearch,
    InMemoryStore,
    ScoreReranker,
    chunk_document,
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
    doc = Document(id="d4", text="One sentence. Two sentence.",
                   metadata={"grade": "A", "source": "Lighthouse"})
    chunks = chunk_document(doc)
    for c in chunks:
        assert c.metadata["grade"] == "A"
        assert c.metadata["source"] == "Lighthouse"


def test_max_tokens_zero_rejected():
    with pytest.raises(ValueError):
        chunk_document(Document(id="x", text="hi"), max_tokens=0)


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
    store.upsert(chunks_a + chunks_b,
                 e.embed([c.text for c in chunks_a + chunks_b]))
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
    chunk = chunk_document(Document(id="d", text="body text",
                                    metadata={"source": "NYT", "grade": "A",
                                              "published_date": "2026-01-01"}))[0]
    pre = default_preamble(chunk)
    assert "NYT" in pre and "grade A" in pre


def test_prepend_context_adds_preamble():
    chunks = chunk_document(Document(id="d", text="body",
                                     metadata={"source": "X", "grade": "B"}))
    out = prepend_context(chunks)
    assert out[0].text.startswith("[")
    assert "X" in out[0].text


def test_prepend_context_noop_without_metadata():
    chunks = chunk_document(Document(id="d", text="body"))
    out = prepend_context(chunks)
    assert out[0].text == "body"
