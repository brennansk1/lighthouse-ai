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
from contextlib import nullcontext
from dataclasses import dataclass, field

from ..framing import FramedQuestion, run_framing
from ..gateway import Gateway
from ..governor.scheduler_gate import SchedulerGate
from ..rag.compaction import compact as compact_evidence
from ..rag.hybrid import HybridResult, HybridSearch


def _gate_ctx(gate: SchedulerGate | None):
    """Host-courtesy permit around an LLM call; no-op when no gate is wired."""
    return gate.permit() if gate is not None else nullcontext()

# Imported at module level so tests can patch lighthouse_ai.modes.deepdive.run_debate
try:
    from .debate import run_debate
except Exception:  # pragma: no cover
    run_debate = None  # type: ignore[assignment]


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


def _expand_queries(sub_question: str, gateway: Gateway | None, job_id: str | None) -> list[str]:
    """Generate 2 alternative phrasings of the sub-question for ensemble search."""
    if gateway is None:
        return [sub_question]
    prompt = (
        f"Rephrase this research question in 2 different ways to improve search recall. "
        f"Return ONLY the 2 rephrased questions, one per line, no numbering or explanation.\n\n"
        f"Question: {sub_question}"
    )
    try:
        resp = gateway.complete("aux_context", prompt)
        lines = [l.strip() for l in resp.text.strip().split("\n") if l.strip()]
        variants = lines[:2]
        return [sub_question] + variants  # original + 2 variants
    except Exception:
        return [sub_question]


def _research_section(
    section: Section,
    hybrid: HybridSearch | None,
    gateway: Gateway | None,
    *,
    job_id: str | None,
    top_k: int = 5,
    rerank_candidates: int | None = None,
    working_context: CompactedContext | None = None,
    gate: SchedulerGate | None = None,
) -> tuple[Section, list[HybridResult]]:
    """Fetch evidence + draft a section body. Falls back to a deterministic
    stub when the gateway is absent so the orchestrator runs in tests."""
    evidence: list[HybridResult] = []
    if hybrid is not None:
        queries = _expand_queries(section.sub_question, gateway, job_id)
        all_results: list[HybridResult] = []
        seen_ids: set[str] = set()
        for q in queries:
            for r in hybrid.search(q, top_k=top_k, rerank_candidates=rerank_candidates):
                if r.chunk.id not in seen_ids:
                    seen_ids.add(r.chunk.id)
                    all_results.append(r)
        # Re-sort by score descending, keep top_k
        evidence = sorted(all_results, key=lambda r: r.score, reverse=True)[:top_k]
    citations = [e.chunk.id for e in evidence]
    # `citations` mirrors the chunk ids of the evidence list above.
    if gateway is None:
        body = f"[draft] {section.sub_question}\n\n" + "\n\n".join(
            f"- {e.chunk.text[:200]}…" for e in evidence
        )
    else:
        evidence_lines = "\n".join(f"[{i+1}] {e.chunk.text[:300]}"
                                   for i, e in enumerate(evidence))
        # §5 wiring: deterministic, LLM-free compaction of evidence payload
        # before it enters the researcher prompt.  Only applied when the
        # evidence is non-trivial (>200 chars or more than 3 chunks) to avoid
        # overhead on tiny prompts.
        if len(evidence_lines) > 200 or len(evidence) > 3:
            evidence_lines, _compact_stats = compact_evidence(evidence_lines)
        if working_context is not None:
            open_qs = ", ".join(working_context.open_questions[:5])
            facts = "; ".join(
                f[0][:80] for f in working_context.established_facts[:5]
            )
            ruled_out = ", ".join(working_context.ruled_out[:3])
            prompt = (
                f"Prior research context:\n"
                f"- Open questions: {open_qs}\n"
                f"- Established facts: {facts}\n"
                f"- Ruled out: {ruled_out}\n\n"
                f"Sub-question: {section.sub_question}\n\n"
                f"Evidence:\n{evidence_lines}"
                f"\n\nDraft a 2-paragraph answer with [N] citations."
                f" Build on the established facts above."
            )
        else:
            prompt = (
                f"Sub-question: {section.sub_question}\n\n"
                f"Evidence:\n" + evidence_lines
                + "\n\nDraft a 2-paragraph answer with [N] citations."
            )
        with _gate_ctx(gate):
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
    gate: SchedulerGate | None = None,
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
        with _gate_ctx(gate):
            resp = gateway.complete("synthesizer", prompt, job_id=job_id)
        revised = _parse_synthesizer_sections(resp.text, sections)
    except Exception:
        revised = sections

    return [dc_replace(s, citations=list(dict.fromkeys(s.citations)))
            for s in revised]


def _extract_debate_subquestions(
    sections: list[Section],
    gateway: Gateway | None,
    job_id: str | None,
) -> list[str]:
    """Run Debate on load-bearing sections with [CONTRADICTION] markers.

    Returns a list of dispute crux strings to add as new sub-questions.
    Empty list when gateway is None or no contradictions found.
    """
    if gateway is None:
        return []
    new_subs: list[str] = []
    for sec in sections:
        if not sec.is_load_bearing:
            continue
        if "[CONTRADICTION]" not in sec.body:
            continue
        try:
            if run_debate is None:
                continue
            result = run_debate(
                claim=sec.sub_question,
                draft=sec.body,
                gateway=gateway,
                job_id=job_id,
            )
            # The first unresolved dispute becomes a new sub-question
            if result.disputes:
                crux = result.disputes[0][:120].strip()
                if crux and crux not in [s.sub_question for s in sections]:
                    new_subs.append(crux)
        except Exception:
            pass  # never let debate failures break the loop
    return new_subs[:2]  # cap at 2 new sub-questions per round to control runaway loops


def _should_crag_fetch(draft: DraftReport, progress: float) -> bool:
    """Trigger mid-loop web fetch when gaps found or progress stalled."""
    has_gaps = any("[GAP]" in (s.body or "") for s in draft.sections)
    return has_gaps or progress < 0.1


def _crag_fetch(
    draft: DraftReport,
    hybrid: HybridSearch,
    cfg: object,
    gate: SchedulerGate | None,
    gateway: Gateway | None,
    job_id: str | None,
) -> None:
    """Fetch from SearXNG for open questions/gaps, ingest into hybrid store."""
    import structlog
    from ..rag.chunker import chunk_document
    from ..sources.searxng import SearXNGUnavailable, search_as_documents  # noqa: F401

    # Collect gap-bearing sub-questions as queries
    queries = [
        s.sub_question for s in draft.sections
        if "[GAP]" in (s.body or "") and s.sub_question
    ]
    if not queries:
        # Fall back to using the original question
        queries = [draft.question] if draft.question else []
    if not queries:
        return

    log = structlog.get_logger(__name__)

    for query in queries[:3]:  # cap at 3 queries to avoid hammering
        docs = search_as_documents(query, max_results=5, scholarly=True)
        if not docs:
            continue
        for doc in docs:
            chunks = chunk_document(doc)
            hybrid.add(chunks)
        log.info("deepdive.crag_fetch", query=query[:60], docs=len(docs))


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
    min_entailment_for_early_stop: float = 0.0,
    gate: SchedulerGate | None = None,
) -> DraftReport:
    framed = run_framing(question)
    sections = _skeleton(framed)
    evidence_rounds: list[list[HybridResult]] = []

    rounds_used = 0
    prev_open_count: int | None = None
    working_context: CompactedContext | None = None
    for round_idx in range(1, max_rounds + 1):
        round_evidence: list[HybridResult] = []
        new_sections: list[Section] = []
        for sec in sections:
            sec2, evid = _research_section(
                sec, hybrid, gateway, job_id=job_id,
                top_k=top_k,
                rerank_candidates=rerank_candidates,
                working_context=working_context,
                gate=gate,
            )
            new_sections.append(sec2)
            round_evidence.extend(evid)
        sections = _denoise(new_sections, gateway=gateway, job_id=job_id, gate=gate)

        # Debate auto-wiring: trigger on load-bearing sections with contradictions
        if gateway is not None and round_idx < max_rounds:
            new_subs = _extract_debate_subquestions(sections, gateway, job_id)
            if new_subs:
                for sq in new_subs:
                    sections.append(Section(
                        title=f"Section {len(sections)+1}: {sq[:60]}",
                        sub_question=sq, body="", is_load_bearing=True,
                    ))

        evidence_rounds.append(round_evidence)
        rounds_used = round_idx

        # Build compacted context for next round
        provisional = DraftReport(
            question=question, framing=framed, sections=sections,
            open_questions=[s.sub_question for s in sections if not s.body.strip()],
            rounds_used=round_idx, evidence_chunks=round_evidence,
        )
        working_context = compact(provisional)

        if on_round:
            on_round(round_idx, sections)

        # Terminate when the discovery curve has flattened AND no new open
        # questions were resolved/created since the prior round (§Sprint 28).
        open_count = sum(1 for s in sections if not s.body.strip())
        progress = _discovery_progress(evidence_rounds)

        # CRAG: mid-loop web fetch when gaps detected or progress stalled
        if hybrid is not None and round_idx < max_rounds and _should_crag_fetch(provisional, progress):
            _crag_fetch(provisional, hybrid, None, gate, gateway, job_id)
        stuck = progress < progress_threshold
        open_unchanged = prev_open_count is not None and open_count == prev_open_count
        # Entailment gate (seam for pipeline.py to pass a threshold later)
        entailment_ok = True
        if min_entailment_for_early_stop > 0.0:
            entailment_ok = True  # conservative default; pipeline fills this in
        if stuck and open_unchanged and entailment_ok and round_idx > 1:
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
