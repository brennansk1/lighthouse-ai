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

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..framing import FramedQuestion, run_framing
from ..gateway import Gateway
from ..governor.scheduler_gate import SchedulerGate
from ..rag.compaction import compact as compact_evidence
from ..rag.hybrid import HybridResult, HybridSearch
from ..verification import contradiction as _contradiction
from ..verification.contradiction import Contradiction
from ._gate import gate_ctx

# Fixed, deterministic timestamp stamped onto contradictions when a caller does
# not supply one. NEVER datetime.now() at import — the epoch keeps offline runs
# byte-reproducible; live dispatch passes a real `detected_at` through.
DEFAULT_DETECTED_AT = datetime(1970, 1, 1, tzinfo=UTC)

#: Detects an inline [N] or [N,M] citation marker.
_HAS_CITATION = re.compile(r"\[\d+(?:\s*,\s*\d+)*\]")

#: Explicit citation instruction. Small local models routinely drop inline
#: citations when asked vaguely ("with [N] citations"); a concrete rule + an
#: example gets them to cite reliably, which is what the discipline gate scores.
_CITE_INSTRUCTION = (
    "Write a concise, evidence-grounded answer of 1-2 short paragraphs. Cite the "
    "evidence inline: immediately after each factual claim, put the number(s) of "
    "the evidence it comes from in square brackets — e.g. '...improves insulin "
    "sensitivity [1].' or '...seen in two trials [2,3].' EVERY factual sentence "
    "must end with at least one [N] citation. Use only the numbered evidence "
    "above; never invent a citation number."
)

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
    # First-class contradiction artifacts surfaced during denoise (§6.3). Default
    # empty so every existing DraftReport(...) constructor keeps working.
    contradictions: list[Contradiction] = field(default_factory=list)
    # contradiction_ids that meet the §6.4 auto-Adjudicate preconditions. The
    # dispatcher spawns the sub-jobs (already stubbed); we only flag them here.
    auto_adjudicate_candidates: list[str] = field(default_factory=list)


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
    working_context: CompactedContext | None = None,
    gate: SchedulerGate | None = None,
) -> tuple[Section, list[HybridResult]]:
    """Fetch evidence + draft a section body. Falls back to a deterministic
    stub when the gateway is absent so the orchestrator runs in tests."""
    evidence: list[HybridResult] = []
    if hybrid is not None:
        try:
            evidence = hybrid.search(section.sub_question, top_k=top_k,
                                     rerank_candidates=rerank_candidates)
        except Exception:
            # A retrieval failure mid-run (Qdrant restart, embedder/dimension
            # mismatch, transient store error) degrades THIS section to "no
            # evidence" — consistent with how the rest of the pipeline handles
            # backend failures — instead of failing the whole job.
            evidence = []
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
                f"\n\n{_CITE_INSTRUCTION}"
                f" Build on the established facts above."
            )
        else:
            prompt = (
                f"Sub-question: {section.sub_question}\n\n"
                f"Evidence:\n" + evidence_lines
                + f"\n\n{_CITE_INSTRUCTION}"
            )
        with gate_ctx(gate):
            resp = gateway.complete("researcher", prompt, job_id=job_id)
        body = resp.text
        # Small local models sometimes still omit inline [N] markers even with
        # numbered evidence in hand — which makes a genuinely grounded section
        # look ungrounded to the discipline gate. Retry ONCE with an explicit
        # re-instruction (honest: the model does the citing; we never fabricate
        # markers). If it still won't cite, the low coverage stands — that is the
        # honest signal, not something to paper over.
        if evidence and not _HAS_CITATION.search(body):
            retry_prompt = (
                f"{prompt}\n\nYour previous answer contained NO [N] citations. "
                f"Rewrite it now, adding the correct evidence number in square "
                f"brackets after every factual claim. The evidence is numbered "
                f"1 to {len(evidence)}."
            )
            try:
                with gate_ctx(gate):
                    resp2 = gateway.complete("researcher", retry_prompt,
                                             job_id=job_id)
                if _HAS_CITATION.search(resp2.text):
                    body = resp2.text
            except Exception:
                pass
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


def _saturation_slope(cumulative_unique: list[int]) -> float:
    """Marginal-utility slope of the evidence-saturation learning curve.

    ``cumulative_unique[i]`` is the count of distinct evidence chunk ids seen
    through round ``i+1``. The slope we return is the *normalized marginal gain*
    of the latest round: how many NEW unique chunks the last round added,
    divided by the total seen so far. As research saturates, each round adds
    proportionally fewer new findings and this curve flattens toward 0.

    Deterministic and bounded in [0, 1]. Returns 1.0 before there's enough
    history to judge (never terminates on the strength of a single round).
    """
    if len(cumulative_unique) < 2:
        return 1.0
    total = cumulative_unique[-1]
    if total <= 0:
        return 0.0
    marginal = cumulative_unique[-1] - cumulative_unique[-2]
    return marginal / total


def _saturated(
    cumulative_unique: list[int],
    *,
    slope_floor: float,
    round_idx: int,
) -> bool:
    """True when the saturation curve has flattened below ``slope_floor``.

    Replaces the old hard-coded 0.1 marginal-info threshold: instead of looking
    only at the latest round in isolation, we track cumulative unique findings
    across rounds and stop when the *slope* of that learning curve drops below
    the floor — i.e. the run has stopped yielding meaningfully new evidence.
    Never fires on round 1 (needs a prior point to measure a slope).
    """
    if round_idx <= 1:
        return False
    return _saturation_slope(cumulative_unique) < slope_floor


def _emit_contradictions(
    sections: list[Section],
    evidence_chunks: list[HybridResult],
    *,
    job_id: str | None,
    detected_at: datetime,
    depth_tier: str,
    auto_adjudicate_disabled: bool,
) -> tuple[list[Contradiction], list[str]]:
    """Build claims + evidence and run :func:`contradiction.detect` over a draft.

    Each section's first-sentence-ish claim is the unit of detection; the full
    evidence pool (carrying ``metadata.skill_id`` / ``metadata.entailment_score``)
    feeds the claim + cross_skill layers. Load-bearing-ness flows from the
    section so balanced cross-skill disputes on load-bearing claims reach the
    ``high`` severity that the §6.4 auto-Adjudicate gate keys on.

    Returns ``(contradictions, auto_adjudicate_candidate_ids)``.
    """
    from ..verification.discipline import Claim as _Claim

    claims: list[_Claim] = []
    load_bearing_by_idx: list[bool] = []
    for sec in sections:
        body = (sec.body or "").strip()
        claim_text = body.split(".")[0].strip() if body else sec.sub_question
        if not claim_text:
            continue
        claims.append(_Claim(text=claim_text))
        load_bearing_by_idx.append(sec.is_load_bearing)

    if not claims:
        return [], []

    found = _contradiction.detect(
        claims,
        evidence_chunks,
        job_id=job_id or "deepdive",
        detected_at=detected_at,
        load_bearing=load_bearing_by_idx,
    )

    candidates = [
        c.contradiction_id
        for c in found
        if _contradiction.should_auto_adjudicate(
            c, depth_tier=depth_tier, user_disabled=auto_adjudicate_disabled
        )
    ]
    return found, candidates


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
    section_evidence: dict[str, list[HybridResult]] | None = None,
) -> list[Section]:
    """The TTD-DR denoiser — "the single biggest report-quality lever".

    Two paths, both deterministic for a given input:

    * **gateway is None** (offline / tests): the historical citation-dedup
      fallback. Each section keeps its body; duplicate citation ids are
      collapsed in first-seen order. No prose is changed.
    * **gateway present**: a real ``synthesizer`` pass. We hand the synthesizer
      every section draft *with its evidence* and instruct it to (1) merge the
      drafts into coherent cross-referenced prose, (2) resolve or explicitly
      mark ``[CONTRADICTION]`` between sections, and (3) mark ``[GAP]`` where a
      sub-question is left unanswered. The result is parsed back into the same
      section skeleton (titles preserved); citations are then deduped.

    ``section_evidence`` maps ``section.title`` → its evidence chunks so the
    synthesizer can ground the merge. Missing entries degrade gracefully.
    """
    from dataclasses import replace as dc_replace

    # Stub path: gateway absent (tests, offline mode) — pure citation dedup.
    if gateway is None:
        return [dc_replace(s, citations=list(dict.fromkeys(s.citations)))
                for s in sections]

    section_evidence = section_evidence or {}

    def _evidence_block(s: Section) -> str:
        evid = section_evidence.get(s.title, [])
        if not evid:
            return "(no retrieved evidence)"
        lines = [f"  [{e.chunk.id}] {e.chunk.text[:200]}" for e in evid[:5]]
        return "\n".join(lines)

    section_texts = "\n\n".join(
        f"### {s.title}\n"
        f"Sub-question: {s.sub_question}\n"
        f"Draft:\n{s.body or '[empty]'}\n"
        f"Evidence:\n{_evidence_block(s)}"
        for s in sections
    )
    prompt = (
        "You are the synthesizer in a deep-research pipeline. Below are draft "
        "sections, each with its sub-question and retrieved evidence.\n\n"
        f"{section_texts}\n\n"
        "Synthesize a single coherent report body:\n"
        "1. Merge overlapping content; rewrite each section as flowing prose.\n"
        "2. Add cross-section references where sections relate (cite the other "
        "section by title).\n"
        "3. Where two sections disagree, resolve it on evidence weight if one "
        "side clearly dominates; otherwise mark it explicitly with "
        "[CONTRADICTION] and name both sides. Never silently smooth a "
        "disagreement away.\n"
        "4. Where a sub-question is left unanswered by the evidence, mark "
        "[GAP] and say what is missing.\n"
        "5. Preserve [N] / [chunk-id] citations from the drafts.\n"
        "Return ALL sections in this exact format (preserve titles exactly):\n"
        "### <original title>\n<revised body>\n\n"
        "Do not add new sections or change section titles."
    )
    try:
        with gate_ctx(gate):
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
    gate: SchedulerGate | None = None,
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
                gate=gate,
            )
            # The first unresolved dispute becomes a new sub-question
            if result.disputes:
                crux = result.disputes[0][:120].strip()
                if crux and crux not in [s.sub_question for s in sections]:
                    new_subs.append(crux)
        except Exception:
            pass  # never let debate failures break the loop
    return new_subs[:2]  # cap at 2 new sub-questions per round to control runaway loops


def _entailment_early_stop_ok(
    sections: list[Section],
    section_evidence: dict[str, list[HybridResult]],
    *,
    floor: float,
) -> bool:
    """True when the entailed fraction of drafted sections meets ``floor``.

    Each section body is scored against its OWN evidence (the per-section
    grounding is correctly aligned, unlike the report-level evidence list).
    Conservative degradations keep behavior identical to the pre-gate code:
    no scorer installed, no scorable sections, or scorer errors → True
    (the gate only ever *blocks* an early stop, never forces one).
    """
    from ..verification import entailment as _entailment

    if not _entailment.available():
        return True
    scored = 0
    entailed = 0
    for sec in sections:
        body = sec.body.strip()
        if not body:
            continue
        evid = section_evidence.get(sec.title) or []
        grounding = "\n".join(e.chunk.text for e in evid)
        if not grounding.strip():
            continue
        score = _entailment.score_claim(body[:2000], grounding[:4000])
        if score is None:  # scorer error — unchecked, not counted either way
            continue
        scored += 1
        if score >= _entailment.MINICHECK_THRESHOLD:
            entailed += 1
    if scored == 0:
        return True
    return (entailed / scored) >= floor


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
    detected_at: datetime | None = None,
    depth_tier: str = "thorough",
    auto_adjudicate_disabled: bool = False,
    saturation_slope_floor: float | None = None,
    acquire_fn: Callable[[str], int] | None = None,
) -> DraftReport:
    # Forward the gateway so the planner-primary framing path runs (matching
    # exhaustive.py). Offline (gateway=None) this is bit-for-bit the
    # deterministic baseline, so existing offline output never moves.
    framed = run_framing(question, gateway=gateway, job_id=job_id)
    sections = _skeleton(framed)
    evidence_rounds: list[list[HybridResult]] = []
    # Cumulative count of distinct evidence chunk ids seen through round i.
    cumulative_unique: list[int] = []
    seen_chunk_ids: set[str] = set()
    if detected_at is None:
        detected_at = DEFAULT_DETECTED_AT
    # The saturation slope floor mirrors the legacy marginal-info threshold when
    # the caller does not override it, so existing tuning still applies.
    if saturation_slope_floor is None:
        saturation_slope_floor = progress_threshold

    rounds_used = 0
    prev_open_count: int | None = None
    working_context: CompactedContext | None = None
    # One stuck-but-open acquisition retry per run: when saturation would end
    # the run with open questions remaining, spend time acquiring instead of
    # stopping — but only once, so the loop stays bounded by max_rounds.
    stuck_acquired = False
    for round_idx in range(1, max_rounds + 1):
        # Iterative acquisition (frontier deep-research loop): from round 2 on,
        # lines of inquiry that came back thin trigger NEW web acquisition for
        # exactly that sub-question before being researched again. acquire_fn
        # is injected by the dispatcher (None offline → bit-identical runs);
        # it indexes into `hybrid` as a side effect and returns new-doc count.
        if acquire_fn is not None and round_idx >= 2:
            for sec in sections:
                if not sec.body.strip() or len(sec.citations) < 2:
                    try:
                        acquire_fn(sec.sub_question)
                    except Exception:
                        pass  # acquisition is best-effort, never fatal
        round_evidence: list[HybridResult] = []
        new_sections: list[Section] = []
        section_evidence: dict[str, list[HybridResult]] = {}
        for sec in sections:
            sec2, evid = _research_section(
                sec, hybrid, gateway, job_id=job_id,
                top_k=top_k,
                rerank_candidates=rerank_candidates,
                working_context=working_context,
                gate=gate,
            )
            new_sections.append(sec2)
            section_evidence[sec2.title] = evid
            round_evidence.extend(evid)
        sections = _denoise(new_sections, gateway=gateway, job_id=job_id,
                            gate=gate, section_evidence=section_evidence)

        # Debate auto-wiring: trigger on load-bearing sections with contradictions
        if gateway is not None and round_idx < max_rounds:
            new_subs = _extract_debate_subquestions(sections, gateway, job_id,
                                                    gate=gate)
            if new_subs:
                for sq in new_subs:
                    sections.append(Section(
                        title=f"Section {len(sections)+1}: {sq[:60]}",
                        sub_question=sq, body="", is_load_bearing=True,
                    ))

        evidence_rounds.append(round_evidence)
        rounds_used = round_idx

        # Evidence-saturation learning curve (gap #25): accumulate distinct
        # chunk ids and record the running total so the slope of the curve can
        # be measured across rounds.
        for r in round_evidence:
            seen_chunk_ids.add(r.chunk.id)
        cumulative_unique.append(len(seen_chunk_ids))

        # Build compacted context for next round
        provisional = DraftReport(
            question=question, framing=framed, sections=sections,
            open_questions=[s.sub_question for s in sections if not s.body.strip()],
            rounds_used=round_idx, evidence_chunks=round_evidence,
        )
        working_context = compact(provisional)

        if on_round:
            on_round(round_idx, sections)

        # Terminate when the evidence-saturation curve has flattened AND no new
        # open questions were resolved/created since the prior round (§Sprint 28,
        # gap #25). The saturation curve replaces the old hard-coded 0.1
        # single-round marginal-info threshold with a slope over cumulative
        # unique findings — a run that stops yielding new evidence flattens out
        # and is stopped.
        open_count = sum(1 for s in sections if not s.body.strip())
        stuck = _saturated(cumulative_unique, slope_floor=saturation_slope_floor,
                           round_idx=round_idx)
        open_unchanged = prev_open_count is not None and open_count == prev_open_count
        # Entailment gate: a saturated draft must not stop early while its
        # sections are unfaithful to their own evidence. Sections are scored
        # against their OWN per-section evidence (correctly aligned grounding,
        # unlike the global evidence list). 0.0 (the default) or an absent
        # scorer disables the gate — behavior is then identical to before.
        entailment_ok = True
        if min_entailment_for_early_stop > 0.0:
            entailment_ok = _entailment_early_stop_ok(
                sections, section_evidence,
                floor=min_entailment_for_early_stop)
        if stuck and open_unchanged and entailment_ok and round_idx > 1:
            # Stuck-but-open: before giving up on open questions, acquire new
            # evidence for them once and keep going — the corpus was the
            # bottleneck, not the question. No new evidence → stop as before.
            if (acquire_fn is not None and open_count > 0
                    and not stuck_acquired and round_idx < max_rounds):
                stuck_acquired = True
                gained = 0
                for sec in sections:
                    if not sec.body.strip():
                        try:
                            gained += acquire_fn(sec.sub_question)
                        except Exception:
                            pass
                if gained > 0:
                    prev_open_count = open_count
                    continue
            break
        prev_open_count = open_count

    # Anything with an empty body remains an open question.
    open_questions = [s.sub_question for s in sections if not s.body.strip()]
    all_evidence: list[HybridResult] = [e for rnd in evidence_rounds for e in rnd]

    # Contradiction emission (§6.3): detect disagreements across the final
    # sections + evidence, attach them as first-class artifacts, and flag the
    # ones that meet the §6.4 auto-Adjudicate preconditions (load-bearing,
    # balanced, cross_skill, Thorough+). Sub-job spawn is dispatcher-side.
    contradictions, auto_candidates = _emit_contradictions(
        sections, all_evidence,
        job_id=job_id, detected_at=detected_at,
        depth_tier=depth_tier,
        auto_adjudicate_disabled=auto_adjudicate_disabled,
    )

    return DraftReport(
        question=question, framing=framed, sections=sections,
        open_questions=open_questions, ruled_out=[],
        rounds_used=rounds_used,
        evidence_chunks=all_evidence,
        contradictions=contradictions,
        auto_adjudicate_candidates=auto_candidates,
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
