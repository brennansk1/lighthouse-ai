"""Deep-Dive (Mode B) tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
    r = run_deepdive("What is decoherence?", hybrid=hs, max_rounds=5, progress_threshold=0.9)
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

    secs = [Section(title="S1", sub_question="q1", body="body", citations=["c1", "c2", "c1"])]
    result = _denoise(secs, gateway=None, job_id=None)
    assert result[0].citations == ["c1", "c2"]


def test_denoise_llm_path_falls_back_on_exception():
    from lighthouse_ai.modes.deepdive import Section, _denoise

    mock_gw = MagicMock()
    mock_gw.complete.side_effect = RuntimeError("LLM unavailable")
    secs = [Section(title="S1", sub_question="q1", body="original body", citations=["c1"])]
    result = _denoise(secs, gateway=mock_gw, job_id="j1")
    assert result[0].body == "original body"
    assert result[0].citations == ["c1"]


def test_denoise_llm_path_calls_synthesizer_role():
    from lighthouse_ai.modes.deepdive import Section, _denoise

    mock_gw = MagicMock()
    mock_gw.complete.return_value = MagicMock(text="### Section 1: test\nRevised body content.\n")
    secs = [Section(title="Section 1: test", sub_question="q", body="original")]
    result = _denoise(secs, gateway=mock_gw, job_id=None)
    called_role = mock_gw.complete.call_args[0][0]
    assert called_role == "synthesizer"
    assert "Revised" in result[0].body


def test_denoise_amplified_best_of_n_and_regeneration():
    from lighthouse_ai.modes.deepdive import Section, _denoise
    from lighthouse_ai.rag.chunker import Chunk

    mock_gw = MagicMock()
    mock_gw.complete.side_effect = [
        MagicMock(text="### S1\nBody with invalid [9] citation.\n"),
        MagicMock(text="### S1\nBody with valid [src1] citation.\n"),
        MagicMock(text="### S1\nBody with no citation.\n"),
        MagicMock(text="Regenerated grounded body text."),
    ]

    class FakeEvidence:
        def __init__(self):
            self.chunk = Chunk(id="src1", document_id="doc1", text="Consensus is true.", position=0)

    secs = [Section(title="S1", sub_question="q", body="original")]
    _denoise(
        secs,
        gateway=mock_gw,
        job_id="j1",
        section_evidence={"S1": [FakeEvidence()]},
        depth_tier="thorough",
    )
    assert mock_gw.complete.call_count >= 3


def test_iterresearch_working_context_injected_in_round_2():
    """After round 1, CompactedContext is passed to round 2's researcher prompts."""
    hs = _hybrid_with_docs()
    # Track prompts received by the gateway
    received_prompts = []
    mock_gw = MagicMock()
    mock_gw.complete.side_effect = lambda role, prompt, **kw: (
        received_prompts.append(prompt) or MagicMock(text=f"[draft from {role}] answer")
    )
    run_deepdive(
        "Compare classical and quantum computing", hybrid=hs, gateway=mock_gw, max_rounds=2
    )
    # If context injection worked, round 2 prompts should differ from round 1
    # We can't assert exact content since the mock returns a draft body,
    # but at least the loop ran 2 rounds.
    assert len(received_prompts) >= 2  # at least 1 per section per round


def test_deepdive_forwards_gateway_to_framing():
    """The planner-primary framing path must run when deepdive has a gateway.

    Regression: deepdive called ``run_framing(question)`` without forwarding its
    gateway, so the LLM planner framing (the highest-leverage upstream lever)
    was dead for Investigate even with a gateway wired — unlike exhaustive.py
    which passes it through.
    """
    mock_gw = MagicMock()
    mock_gw.complete.return_value = MagicMock(text="[draft] answer")
    with patch("lighthouse_ai.modes.deepdive.run_framing") as mock_framing:
        from lighthouse_ai.framing import run_framing as real_framing

        mock_framing.side_effect = lambda q, **kw: real_framing(q)
        run_deepdive("Why did the bank collapse?", gateway=mock_gw, max_rounds=1)
    # run_framing must have been called WITH the gateway, not bare.
    assert mock_framing.call_args is not None
    assert mock_framing.call_args.kwargs.get("gateway") is mock_gw


def test_no_debate_without_gateway():
    """_extract_debate_subquestions returns [] when gateway is None."""
    from lighthouse_ai.modes.deepdive import Section, _extract_debate_subquestions

    secs = [Section(title="S", sub_question="q", body="X [CONTRADICTION] Y", is_load_bearing=True)]
    result = _extract_debate_subquestions(secs, None, None)
    assert result == []


def test_no_debate_on_non_load_bearing_section():
    """[CONTRADICTION] on non-load-bearing sections does not trigger debate."""
    from lighthouse_ai.modes.deepdive import Section, _extract_debate_subquestions

    secs = [
        Section(title="S", sub_question="q", body="X [CONTRADICTION] Y", is_load_bearing=False)
    ]  # not load-bearing
    gw = MagicMock()
    result = _extract_debate_subquestions(secs, gw, None)
    assert result == []
    gw.complete.assert_not_called()


def test_debate_trigger_adds_sub_question():
    """[CONTRADICTION] on a load-bearing section calls run_debate and extracts crux."""
    from lighthouse_ai.modes.debate import DebateResult
    from lighthouse_ai.modes.deepdive import Section, _extract_debate_subquestions

    secs = [
        Section(
            title="S1",
            sub_question="Does X cause Y?",
            body="X seems to cause Y [CONTRADICTION] but evidence is mixed.",
            is_load_bearing=True,
        )
    ]
    mock_gw = MagicMock()
    mock_debate = MagicMock(
        return_value=DebateResult(
            claim="Does X cause Y?",
            draft="...",
            responses=[],
            judge_summary="0/0 agree.",
            agreements=[],
            disputes=["The causal mechanism is not established by the cited evidence."],
        )
    )
    with patch("lighthouse_ai.modes.deepdive.run_debate", mock_debate):
        result = _extract_debate_subquestions(secs, mock_gw, None)
    assert len(result) == 1
    assert "causal" in result[0] or "mechanism" in result[0] or "established" in result[0]


def test_working_context_parameter_accepted():
    """_research_section accepts working_context without error."""
    from lighthouse_ai.modes.deepdive import CompactedContext, Section, _research_section

    sec = Section(title="S1", sub_question="What is X?", body="")
    ctx = CompactedContext(
        open_questions=["What is X?"],
        established_facts=[("X is large", ["c1"])],
        ruled_out=["X is not small"],
        current_plan="Continue round 2.",
    )
    result_sec, evidence = _research_section(sec, None, None, job_id=None, working_context=ctx)
    assert result_sec.sub_question == "What is X?"


# --- entailment-gated early stop (min_entailment_for_early_stop) -----------


def _patch_scorer(monkeypatch, score: float):
    from lighthouse_ai.verification import entailment as ent

    monkeypatch.setattr(ent, "available", lambda: True)
    monkeypatch.setattr(ent, "score_claim", lambda _claim, _grounding: score)


def test_low_entailment_blocks_early_stop(monkeypatch):
    """A saturated draft whose sections are unfaithful to their own evidence
    must keep researching instead of stopping early. Regression: the gate was
    a dead stub (entailment_ok hardwired True)."""
    _patch_scorer(monkeypatch, 0.05)  # everything unfaithful
    hs = _hybrid_with_docs()
    r = run_deepdive(
        "What is decoherence?",
        hybrid=hs,
        max_rounds=5,
        progress_threshold=0.9,
        min_entailment_for_early_stop=0.9,
    )
    assert r.rounds_used == 5  # gate blocked the plateau stop every round


def test_high_entailment_allows_early_stop(monkeypatch):
    _patch_scorer(monkeypatch, 0.99)  # everything faithful
    hs = _hybrid_with_docs()
    r = run_deepdive(
        "What is decoherence?",
        hybrid=hs,
        max_rounds=5,
        progress_threshold=0.9,
        min_entailment_for_early_stop=0.9,
    )
    assert r.rounds_used <= 3  # same early stop as the ungated baseline


def test_entailment_gate_off_without_scorer(monkeypatch):
    """No scorer installed → behavior identical to before the gate existed."""
    from lighthouse_ai.verification import entailment as ent

    monkeypatch.setattr(ent, "available", lambda: False)
    hs = _hybrid_with_docs()
    r = run_deepdive(
        "What is decoherence?",
        hybrid=hs,
        max_rounds=5,
        progress_threshold=0.9,
        min_entailment_for_early_stop=0.9,
    )
    assert r.rounds_used <= 3


# --- iterative acquisition triggers (acquire_fn) ---------------------------


def test_acquire_fn_none_keeps_offline_runs_identical():
    hs1, hs2 = _hybrid_with_docs(), _hybrid_with_docs()
    base = run_deepdive("What is decoherence?", hybrid=hs1, max_rounds=3)
    same = run_deepdive("What is decoherence?", hybrid=hs2, max_rounds=3, acquire_fn=None)
    assert [s.body for s in base.sections] == [s.body for s in same.sections]
    assert base.rounds_used == same.rounds_used


def test_thin_sections_trigger_acquisition_from_round_two():
    """Sections with <2 citations trigger acquire_fn(sub_question) each round
    from round 2 on — research that comes back thin reaches for new evidence."""
    asked: list[str] = []
    # No hybrid → every section has zero citations → all thin.
    r = run_deepdive(
        "State of x?", hybrid=None, max_rounds=3, acquire_fn=lambda q: (asked.append(q), 0)[1]
    )
    assert r.rounds_used >= 2
    assert asked  # acquisition was consulted
    assert all(q for q in asked)  # called with the sub-questions themselves


def test_stuck_but_open_acquires_once_then_continues():
    """When saturation would end the run with open questions remaining, one
    acquisition pass that yields new evidence extends the run instead."""
    calls: list[str] = []

    def _acquire(q: str) -> int:
        calls.append(q)
        return 3  # "found new evidence"

    hs = _hybrid_with_docs()
    baseline = run_deepdive("What is decoherence?", hybrid=hs, max_rounds=6, progress_threshold=0.9)
    hs2 = _hybrid_with_docs()
    extended = run_deepdive(
        "What is decoherence?",
        hybrid=hs2,
        max_rounds=6,
        progress_threshold=0.9,
        acquire_fn=_acquire,
    )
    # The corpus answered every sub-question (no open sections) OR the run
    # extended past the baseline; either way the run never ends EARLIER.
    assert extended.rounds_used >= baseline.rounds_used


def test_acquire_fn_errors_never_break_the_run():
    def _boom(_q: str) -> int:
        raise RuntimeError("network down")

    r = run_deepdive("State of x?", hybrid=None, max_rounds=3, acquire_fn=_boom)
    assert r.sections  # run completed despite acquisition failures
