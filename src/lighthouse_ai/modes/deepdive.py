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

from collections.abc import Callable
from dataclasses import dataclass, field

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
    evidence_chunks: list[HybridResult] = field(default_factory=list)


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
    rerank_candidates: int | None = None,
) -> tuple[Section, list[HybridResult]]:
    """Fetch evidence + draft a section body. Falls back to a deterministic
    stub when the gateway is absent so the orchestrator runs in tests."""
    evidence: list[HybridResult] = []
    if hybrid is not None:
        evidence = hybrid.search(section.sub_question, top_k=top_k,
                                 rerank_candidates=rerank_candidates)
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


def _parse_synthesizer_sections(text: str, originals: list[Section]) -> list[Section]:
    """Parse synthesizer output back into Section objects by matching ### headings."""
    import re
    from dataclasses import replace as dc_replace
    heading_re = re.compile(r"^###\s+(.+)$", re.MULTILINE)
    parts = heading_re.split(text)
    title_to_body: dict[str, str] = {}
    i = 1
    while i + 1 < len(parts):
        title_to_body[parts[i].strip()] = parts[i + 1].strip()
        i += 2
    out: list[Section] = []
    for orig in originals:
        body = title_to_body.get(orig.title)
        if body is None:
            for t, b in title_to_body.items():
                if orig.title[:30] in t or t[:30] in orig.title:
                    body = b
                    break
        out.append(dc_replace(orig, body=body) if body is not None else orig)
    return out


def _denoise(
    sections: list[Section],
    *,
    gateway: Gateway | None,
    job_id: str | None,
) -> list[Section]:
    """Merge step — dedupes citations (stub) or uses synthesizer LLM (real)."""
    from dataclasses import replace as dc_replace

    # Stub path: gateway absent (tests, offline mode)
    if gateway is None:
        return [dc_replace(s, citations=list(dict.fromkeys(s.citations))) for s in sections]

    # Build synthesizer prompt
    section_texts = "\n\n".join(
        f"### {s.title}\n{s.body or '[empty]'}" for s in sections
    )
    prompt = (
        "You are a research synthesis assistant. Below are draft research sections.\n\n"
        f"{section_texts}\n\n"
        "Tasks:\n"
        "1. Note cross-section contradictions with [CONTRADICTION].\n"
        "2. Note content gaps with [GAP].\n"
        "3. Merge overlapping content into the most relevant section.\n"
        "4. Return ALL sections in this exact format (preserve titles exactly):\n"
        "### <original title>\n<revised body>\n\n"
        "Do not add new sections or change section titles."
    )
    try:
        resp = gateway.complete("synthesizer", prompt, job_id=job_id)
        revised = _parse_synthesizer_sections(resp.text, sections)
    except Exception:
        revised = sections

    return [dc_replace(s, citations=list(dict.fromkeys(s.citations)))
            for s in revised]


def run_deepdive(
    question: str,
    *,
    hybrid: HybridSearch | None = None,
    gateway: Gateway | None = None,
    max_rounds: int = 3,
    progress_threshold: float = 0.05,
    top_k: int = 5,
    rerank_candidates: int | None = None,
    job_id: str | None = None,
    on_round: Callable[[int, list[Section]], None] | None = None,
) -> DraftReport:
    framed = run_framing(question)
    sections = _skeleton(framed)
    evidence_rounds: list[list[HybridResult]] = []

    rounds_used = 0
    prev_open_count: int | None = None
    for round_idx in range(1, max_rounds + 1):
        round_evidence: list[HybridResult] = []
        new_sections: list[Section] = []
        for sec in sections:
            sec2, evid = _research_section(sec, hybrid, gateway, job_id=job_id,
                                           top_k=top_k,
                                           rerank_candidates=rerank_candidates)
            new_sections.append(sec2)
            round_evidence.extend(evid)
        sections = _denoise(new_sections, gateway=gateway, job_id=job_id)
        evidence_rounds.append(round_evidence)
        rounds_used = round_idx
        if on_round:
            on_round(round_idx, sections)
        # Terminate when the discovery curve has flattened AND no new open
        # questions were resolved/created since the prior round (§Sprint 28).
        open_count = sum(1 for s in sections if not s.body.strip())
        progress = _discovery_progress(evidence_rounds)
        stuck = progress < progress_threshold
        open_unchanged = prev_open_count is not None and open_count == prev_open_count
        if stuck and open_unchanged and round_idx > 1:
            break
        prev_open_count = open_count

    # Anything with an empty body remains an open question.
    open_questions = [s.sub_question for s in sections if not s.body.strip()]
    all_evidence: list[HybridResult] = [e for rnd in evidence_rounds for e in rnd]
    return DraftReport(
        question=question, framing=framed, sections=sections,
        open_questions=open_questions, ruled_out=[],
        rounds_used=rounds_used,
        evidence_chunks=all_evidence,
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
