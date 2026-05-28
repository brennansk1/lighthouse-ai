"""Mode B — Bounded Deep-Dive (TTD-DR backbone).

TTD-DR pattern (Google, "Test-Time Diffusion for Deep Research"):
  1. Skeleton draft from the planner.
  2. Researcher fan-out: one researcher per skeleton section, retrieving
     and writing into that section.
  3. Denoiser merges the researcher outputs, filling gaps and resolving
     contradictions.
  4. Iterate (3-5 rounds) until termination signal: discovery-progress
     curve flattens, or budget exhausted, or all sub-questions answered.

Plus ReSum context management (§14.11): when a researcher's working set
exceeds the per-node context budget (default 60%), invoke a compaction
sub-agent to summarize-and-replace.

This module is the orchestrator only — it composes the framing pipeline,
RAG subsystem, and Gateway built earlier. Sprint 10-12 ship the contract;
plug LangGraph in later if desired.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..framing import FramedQuestion, run_framing
from ..gateway import Gateway
from ..rag.hybrid import HybridResult, HybridSearch


@dataclass(frozen=True)
class Section:
    title: str
    sub_question: str
    body: str = ""
    citations: list[str] = field(default_factory=list)
    is_load_bearing: bool = False


@dataclass(frozen=True)
class DraftReport:
    question: str
    framing: FramedQuestion
    sections: list[Section]
    open_questions: list[str] = field(default_factory=list)
    ruled_out: list[str] = field(default_factory=list)
    rounds_used: int = 0


@dataclass
class _ResearcherContext:
    section: Section
    evidence: list[HybridResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _skeleton(framed: FramedQuestion) -> list[Section]:
    """Map the framing's sub-questions to skeleton sections."""
    sections: list[Section] = []
    for i, sq in enumerate(framed.sub_questions):
        load_bearing = sq in framed.load_bearing
        title = f"Section {i+1}: {sq[:60]}"
        sections.append(Section(title=title, sub_question=sq,
                                body="", is_load_bearing=load_bearing))
    return sections


def _research_section(
    section: Section,
    hybrid: HybridSearch | None,
    gateway: Gateway | None,
    *,
    job_id: str | None,
    top_k: int = 5,
) -> tuple[Section, list[HybridResult]]:
    """Fetch evidence + draft a section body. Falls back to a deterministic
    stub when the gateway is absent so the orchestrator runs in tests."""
    evidence: list[HybridResult] = []
    if hybrid is not None:
        evidence = hybrid.search(section.sub_question, top_k=top_k)
    citations = [e.chunk.id for e in evidence]
    # `citations` mirrors the chunk ids of the evidence list above.
    if gateway is None:
        body = f"[draft] {section.sub_question}\n\n" + "\n\n".join(
            f"- {e.chunk.text[:200]}…" for e in evidence
        )
    else:
        prompt = (
            f"Sub-question: {section.sub_question}\n\n"
            f"Evidence:\n" + "\n".join(f"[{i+1}] {e.chunk.text[:300]}"
                                       for i, e in enumerate(evidence))
            + "\n\nDraft a 2-paragraph answer with [N] citations."
        )
        resp = gateway.complete("researcher", prompt, job_id=job_id)
        body = resp.text
    from dataclasses import replace
    return replace(section, body=body, citations=citations), evidence


def _discovery_progress(evidence_rounds: list[list[HybridResult]]) -> float:
    """Marginal information gain in the latest round.

    Returns the fraction of round-N evidence chunk IDs that are NEW relative
    to all prior rounds. When this drops below a threshold (e.g. 0.1) the
    loop is "stuck" and should terminate — modeled on Undermind's discovery
    curve discussed in design §11.
    """
    if len(evidence_rounds) < 1:
        return 1.0
    seen: set[str] = set()
    for prior in evidence_rounds[:-1]:
        for r in prior:
            seen.add(r.chunk.id)
    latest = {r.chunk.id for r in evidence_rounds[-1]}
    if not latest:
        return 0.0
    new = latest - seen
    return len(new) / len(latest)


def _denoise(sections: list[Section]) -> list[Section]:
    """Merge step. In production: a synthesizer pass that resolves
    contradictions and fills cross-section references. Here we just dedupe
    citation lists per section."""
    from dataclasses import replace
    out: list[Section] = []
    for s in sections:
        out.append(replace(s, citations=list(dict.fromkeys(s.citations))))
    return out


def run_deepdive(
    question: str,
    *,
    hybrid: HybridSearch | None = None,
    gateway: Gateway | None = None,
    max_rounds: int = 3,
    progress_threshold: float = 0.1,
    job_id: str | None = None,
    on_round: Callable[[int, list[Section]], None] | None = None,
) -> DraftReport:
    framed = run_framing(question)
    sections = _skeleton(framed)
    evidence_rounds: list[list[HybridResult]] = []
    open_q = list(framed.sub_questions)

    rounds_used = 0
    for round_idx in range(1, max_rounds + 1):
        round_evidence: list[HybridResult] = []
        new_sections: list[Section] = []
        for sec in sections:
            sec2, evid = _research_section(sec, hybrid, gateway,
                                           job_id=job_id, top_k=5)
            new_sections.append(sec2)
            round_evidence.extend(evid)
        sections = _denoise(new_sections)
        evidence_rounds.append(round_evidence)
        rounds_used = round_idx
        if on_round:
            on_round(round_idx, sections)
        progress = _discovery_progress(evidence_rounds)
        if progress < progress_threshold and round_idx > 1:
            break

    # Anything with an empty body remains an open question.
    open_questions = [s.sub_question for s in sections if not s.body.strip()]
    return DraftReport(
        question=question, framing=framed, sections=sections,
        open_questions=open_questions, ruled_out=[],
        rounds_used=rounds_used,
    )


# --- ReSum-style compaction (§14.11) ---

@dataclass(frozen=True)
class CompactedContext:
    open_questions: list[str]
    established_facts: list[tuple[str, list[str]]]  # (claim, source_ids)
    ruled_out: list[str]
    current_plan: str


def compact(report: DraftReport, *, max_facts: int = 10) -> CompactedContext:
    facts: list[tuple[str, list[str]]] = []
    for sec in report.sections[:max_facts]:
        if not sec.body:
            continue
        # First sentence-ish chunk is the claim.
        claim = sec.body.split(".")[0].strip()
        if claim:
            facts.append((claim, sec.citations))
    plan = (f"Continue rounds 2..{report.rounds_used + 1}; "
            f"prioritize load-bearing sub-questions: "
            f"{report.framing.load_bearing}")
    return CompactedContext(
        open_questions=report.open_questions,
        established_facts=facts,
        ruled_out=report.ruled_out,
        current_plan=plan,
    )
