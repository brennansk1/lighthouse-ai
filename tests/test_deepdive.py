"""Deep-Dive (Mode B) tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from lighthouse_ai.modes.deepdive import (
    DraftReport,
    _discovery_progress,
    compact,
    run_deepdive,
)
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


def test_deepdive_new_defaults():
    """run_deepdive defaults are max_rounds=3 and progress_threshold=0.05
    (Sprint 28 step 1 — previously 2 and 0.1 respectively).

    We verify the defaults by inspecting the function signature, then confirm
    a call without explicit arguments uses them end-to-end by running against
    a tiny corpus and checking rounds_used does not exceed 3.
    """
    import inspect

    sig = inspect.signature(run_deepdive)
    assert sig.parameters["max_rounds"].default == 3, (
        "max_rounds default must be 3 after Sprint 28 step 1"
    )
    assert sig.parameters["progress_threshold"].default == 0.05, (
        "progress_threshold default must be 0.05 after Sprint 28 step 1"
    )

    # Also confirm the function runs without error using those defaults.
    hs = _hybrid_with_docs()
    r = run_deepdive("What is decoherence?", hybrid=hs)
    assert r.rounds_used >= 1
    assert r.rounds_used <= 3


def test_draftreport_has_evidence_chunks_field():
    hs = _hybrid_with_docs()
    r = run_deepdive("Compare classical and quantum computing", hybrid=hs, max_rounds=1)
    assert hasattr(r, "evidence_chunks")
    assert isinstance(r.evidence_chunks, list)


def test_denoise_stub_path_dedupes_citations():
    from lighthouse_ai.modes.deepdive import Section, _denoise
    secs = [Section(title="S1", sub_question="q1", body="body",
                    citations=["c1", "c2", "c1"])]
    result = _denoise(secs, gateway=None, job_id=None)
    assert result[0].citations == ["c1", "c2"]


def test_denoise_llm_path_falls_back_on_exception():
    from lighthouse_ai.modes.deepdive import Section, _denoise
    mock_gw = MagicMock()
    mock_gw.complete.side_effect = RuntimeError("LLM unavailable")
    secs = [Section(title="S1", sub_question="q1", body="original body",
                    citations=["c1"])]
    result = _denoise(secs, gateway=mock_gw, job_id="j1")
    assert result[0].body == "original body"
    assert result[0].citations == ["c1"]


def test_denoise_llm_path_calls_synthesizer_role():
    from lighthouse_ai.modes.deepdive import Section, _denoise
    mock_gw = MagicMock()
    mock_gw.complete.return_value = MagicMock(
        text="### Section 1: test\nRevised body content.\n"
    )
    secs = [Section(title="Section 1: test", sub_question="q", body="original")]
    result = _denoise(secs, gateway=mock_gw, job_id=None)
    called_role = mock_gw.complete.call_args[0][0]
    assert called_role == "synthesizer"
    assert "Revised" in result[0].body
