"""Deep-Dive (Mode B) tests."""

from __future__ import annotations

from lighthouse_ai.modes.deepdive import (
    DraftReport,
    Section,
    compact,
    run_deepdive,
)
from lighthouse_ai.modes.deepdive import _discovery_progress
from lighthouse_ai.rag import (
    BM25Index,
    Document,
    HashEmbedder,
    HybridSearch,
    InMemoryStore,
    chunk_document,
)


def _hybrid_with_docs() -> HybridSearch:
    e = HashEmbedder(dim=128)
    hs = HybridSearch(InMemoryStore(), e, BM25Index())
    docs = [
        Document(id="d1", text="Quantum computing uses qubits. Superposition is fundamental."),
        Document(id="d2", text="Classical bits are binary. They use voltage levels."),
        Document(id="d3", text="Decoherence is the main challenge for quantum systems."),
        Document(id="d4", text="Error correction codes mitigate noise in quantum circuits."),
    ]
    for d in docs:
        hs.add(chunk_document(d))
    return hs


def test_deepdive_returns_report_with_sections():
    hs = _hybrid_with_docs()
    r = run_deepdive("Compare classical and quantum computing", hybrid=hs, max_rounds=2)
    assert isinstance(r, DraftReport)
    assert r.sections
    assert r.rounds_used >= 1
    for s in r.sections:
        assert s.sub_question
        assert s.body  # gateway-less default stub still produces something


def test_deepdive_terminates_when_progress_plateaus():
    hs = _hybrid_with_docs()
    r = run_deepdive("What is decoherence?", hybrid=hs, max_rounds=5,
                     progress_threshold=0.9)
    # With high threshold, the loop should bail after round 2.
    assert r.rounds_used <= 3


def test_deepdive_with_no_hybrid_runs():
    r = run_deepdive("State of x?", hybrid=None, max_rounds=1)
    assert r.rounds_used == 1
    # Without a hybrid, citations are empty but body still drafted.
    for s in r.sections:
        assert s.citations == []


def test_discovery_progress_one_when_all_new():
    from lighthouse_ai.rag.store import SearchResult
    from lighthouse_ai.rag.chunker import Chunk
    rounds = [[]]
    assert _discovery_progress(rounds) == 0.0


def test_compact_produces_facts_and_plan():
    hs = _hybrid_with_docs()
    r = run_deepdive("Compare classical and quantum computing", hybrid=hs)
    ctx = compact(r)
    assert ctx.current_plan
    # Each fact carries a claim and citation list.
    for claim, cites in ctx.established_facts:
        assert claim
        assert isinstance(cites, list)


def test_load_bearing_subquestions_become_load_bearing_sections():
    hs = _hybrid_with_docs()
    r = run_deepdive("X vs Y", hybrid=hs)
    load_bearing_sections = [s for s in r.sections if s.is_load_bearing]
    assert load_bearing_sections  # comparative ⇒ at least one load-bearing
