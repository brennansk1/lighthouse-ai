"""Zone P — synthesizer denoiser, contradiction emission, saturation curve.

These tests are offline-deterministic: the no-gateway path must preserve the
historical citation-dedup behavior, and a fake gateway returning a canned
synthesized body exercises the real synthesizer pass without any LLM.
"""

from __future__ import annotations

from datetime import UTC, datetime

from lighthouse_ai.modes.deepdive import (
    DraftReport,
    Section,
    _denoise,
    _emit_contradictions,
    _saturated,
    _saturation_slope,
    run_deepdive,
)
from lighthouse_ai.rag import (
    BM25Index,
    Document,
    HashEmbedder,
    HybridResult,
    HybridSearch,
    InMemoryStore,
    chunk_document,
)
from lighthouse_ai.rag.chunker import Chunk

FIXED_TS = datetime(2026, 1, 1, tzinfo=UTC)


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


class _FakeGateway:
    """Minimal gateway stub: records prompts, returns a canned synthesized body."""

    def __init__(self, canned: str):
        self.canned = canned
        self.calls: list[tuple[str, str]] = []

    def complete(self, role, prompt, *, job_id=None, **kw):
        self.calls.append((role, prompt))

        class _Resp:
            text = self.canned

        return _Resp()


# --------------------------------------------------------------------------- #
# 1. No-gateway denoise: still dedups, no regression
# --------------------------------------------------------------------------- #


def test_denoise_offline_still_dedups_citations():
    secs = [Section(title="S1", sub_question="q1", body="body", citations=["c1", "c2", "c1", "c2"])]
    result = _denoise(secs, gateway=None, job_id=None)
    assert result[0].citations == ["c1", "c2"]
    assert result[0].body == "body"  # offline path never rewrites prose


def test_run_deepdive_offline_no_regression():
    hs = _hybrid_with_docs()
    r = run_deepdive("Compare classical and quantum computing", hybrid=hs, max_rounds=2)
    assert isinstance(r, DraftReport)
    assert r.sections
    assert r.rounds_used >= 1
    for s in r.sections:
        assert s.body
    # New fields exist with sane defaults.
    assert isinstance(r.contradictions, list)
    assert isinstance(r.auto_adjudicate_candidates, list)


# --------------------------------------------------------------------------- #
# 2. Synthesizer pass: sections merge, [CONTRADICTION]/[GAP] markers survive
# --------------------------------------------------------------------------- #


def test_denoise_synthesizer_merges_and_preserves_markers():
    secs = [
        Section(
            title="Section 1: alpha",
            sub_question="What is alpha?",
            body="alpha draft",
            citations=["c1", "c1"],
        ),
        Section(
            title="Section 2: beta",
            sub_question="What is beta?",
            body="beta draft",
            citations=["c2"],
        ),
    ]
    canned = (
        "### Section 1: alpha\n"
        "Alpha is established. See Section 2: beta for the related angle. "
        "[CONTRADICTION] source A says X, source B says not-X.\n\n"
        "### Section 2: beta\n"
        "Beta is partially answered. [GAP] no evidence on the cost dimension.\n"
    )
    gw = _FakeGateway(canned)
    result = _denoise(secs, gateway=gw, job_id="j1")

    # synthesizer role was called
    assert gw.calls and gw.calls[0][0] == "synthesizer"
    # merged prose parsed back into the same skeleton, markers survive
    s1 = next(s for s in result if s.title == "Section 1: alpha")
    s2 = next(s for s in result if s.title == "Section 2: beta")
    assert "[CONTRADICTION]" in s1.body
    assert "Section 2: beta" in s1.body  # cross-section reference survives
    assert "[GAP]" in s2.body
    # citations still deduped
    assert s1.citations == ["c1"]


def test_denoise_synthesizer_prompt_includes_evidence():
    secs = [Section(title="Section 1: x", sub_question="q", body="d", citations=[])]
    chunk = Chunk(
        id="ev1", document_id="d", text="grounding evidence text", position=0, metadata={}
    )
    section_evidence = {
        "Section 1: x": [HybridResult(chunk=chunk, score=1.0, dense_rank=0, sparse_rank=0)]
    }
    gw = _FakeGateway("### Section 1: x\nrevised\n")
    _denoise(secs, gateway=gw, job_id=None, section_evidence=section_evidence)
    prompt = gw.calls[0][1]
    assert "grounding evidence text" in prompt
    assert "ev1" in prompt


def test_denoise_synthesizer_falls_back_on_exception():
    class _BoomGateway:
        def complete(self, *a, **k):
            raise RuntimeError("LLM down")

    secs = [Section(title="S1", sub_question="q", body="original", citations=["c1"])]
    result = _denoise(secs, gateway=_BoomGateway(), job_id="j1")
    assert result[0].body == "original"


# --------------------------------------------------------------------------- #
# 3. Contradiction emission across skill_id
# --------------------------------------------------------------------------- #


def _ev(chunk_id: str, skill_id: str, entailment: float) -> HybridResult:
    chunk = Chunk(
        id=chunk_id,
        document_id=chunk_id,
        text=f"evidence {chunk_id}",
        position=0,
        metadata={"skill_id": skill_id, "entailment_score": entailment},
    )
    return HybridResult(chunk=chunk, score=1.0, dense_rank=0, sparse_rank=0)


def test_contradictions_attach_when_evidence_disagrees_cross_skill():
    sections = [
        Section(
            title="S1",
            sub_question="Does X hold?",
            body="X holds according to the data.",
            is_load_bearing=True,
        )
    ]
    # support from skill A, oppose from skill B -> cross_skill disagreement.
    evidence = [
        _ev("a1", "skill_a", 0.9),
        _ev("a2", "skill_a", 0.8),
        _ev("b1", "skill_b", 0.1),
        _ev("b2", "skill_b", 0.2),
    ]
    found, candidates = _emit_contradictions(
        sections,
        evidence,
        job_id="job1",
        detected_at=FIXED_TS,
        depth_tier="thorough",
        auto_adjudicate_disabled=False,
    )
    cross = [c for c in found if c.detection_layer == "cross_skill"]
    assert cross, "expected a cross_skill contradiction"
    c = cross[0]
    assert c.severity == "high"  # balanced + load-bearing + cross_skill
    assert c.detected_at == FIXED_TS
    # high cross_skill on a load-bearing claim at Thorough+ is an auto-Adjudicate candidate
    assert c.contradiction_id in candidates


def test_no_auto_adjudicate_when_user_disabled():
    sections = [
        Section(title="S1", sub_question="Does X hold?", body="X holds.", is_load_bearing=True)
    ]
    evidence = [_ev("a1", "skill_a", 0.9), _ev("b1", "skill_b", 0.1)]
    _, candidates = _emit_contradictions(
        sections,
        evidence,
        job_id="job1",
        detected_at=FIXED_TS,
        depth_tier="thorough",
        auto_adjudicate_disabled=True,
    )
    assert candidates == []


def test_no_contradiction_when_evidence_agrees():
    sections = [Section(title="S1", sub_question="Does X hold?", body="X holds.")]
    evidence = [_ev("a1", "skill_a", 0.9), _ev("b1", "skill_b", 0.85)]
    found, candidates = _emit_contradictions(
        sections,
        evidence,
        job_id="job1",
        detected_at=FIXED_TS,
        depth_tier="thorough",
        auto_adjudicate_disabled=False,
    )
    assert [c for c in found if c.detection_layer in ("claim", "cross_skill")] == []
    assert candidates == []


# --------------------------------------------------------------------------- #
# 4. Evidence-saturation learning curve
# --------------------------------------------------------------------------- #


def test_saturation_slope_flattens():
    # cumulative unique findings: round1=10, then +5, +1, +0
    assert _saturation_slope([10]) == 1.0  # not enough history
    assert _saturation_slope([10, 15]) == 5 / 15  # marginal/total
    assert _saturation_slope([10, 15, 16]) == 1 / 16
    assert _saturation_slope([10, 15, 16, 16]) == 0.0  # fully saturated


def test_saturated_predicate():
    # round 1 never terminates
    assert _saturated([10], slope_floor=0.5, round_idx=1) is False
    # flat curve below floor terminates from round 2 on
    assert _saturated([10, 10], slope_floor=0.1, round_idx=2) is True
    # steep curve keeps going
    assert _saturated([10, 30], slope_floor=0.1, round_idx=2) is False


def test_run_terminates_when_findings_stop_growing():
    """A corpus that yields the same chunks every round saturates and stops
    before max_rounds because the cumulative-unique curve flattens."""
    hs = _hybrid_with_docs()
    r = run_deepdive("What is decoherence?", hybrid=hs, max_rounds=8, saturation_slope_floor=0.2)
    # Same evidence every round -> after round 2 the slope is 0 -> terminate.
    assert r.rounds_used < 8
    assert r.rounds_used <= 3
