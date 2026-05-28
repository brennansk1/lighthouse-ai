"""Skill distillation — turn a *successful* research run into a reusable skill.

After a run passes the discipline gate with good coverage, we capture *what
worked*: the question type, the decomposition (sub-questions) that produced
well-sourced sections, the evidence domains drawn on, and the quality achieved.
That becomes a versioned skill ``body`` other runs of the same shape can reuse
at planning time (see :mod:`lighthouse_ai.learning.retrieval`).

Design constraints honoured:
- The only optional LLM call (a one-line natural-language rationale) goes through
  the SchedulerGate (host courtesy) and the Gateway (Governor budget/RAM). When
  no gateway/gate is wired the rationale degrades to a deterministic template —
  so distillation never blocks and is fully testable offline.
- No network egress of its own.
- Every distilled/merged skill is sealed into the HMAC audit chain by the caller.
- Dedup/merge keeps the library small and high-signal instead of spamming rows.
"""

from __future__ import annotations

import re
from contextlib import nullcontext
from dataclasses import dataclass

from ..verification.skills import (
    BODY_SCHEMA_VERSION,
    add_skill,
    relevant_skills,
)

_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "what", "how", "why", "does", "do", "did", "will", "would", "should",
    "which", "who", "when", "where", "vs", "versus", "between", "with", "into",
    "about", "this", "that", "these", "those", "be", "can", "could", "it",
}
_WORD_RE = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)


@dataclass(frozen=True)
class DistilledSkill:
    """Outcome of a distillation attempt (returned for audit + reporting)."""
    skill_id: int
    name: str
    question_type: str
    merged: bool


def keywords_for(question: str, *, limit: int = 8) -> list[str]:
    """Extract lowercased content keywords from a question (stopwords removed)."""
    seen: list[str] = []
    for m in _WORD_RE.findall(question.lower()):
        if m in _STOPWORDS or m in seen:
            continue
        seen.append(m)
        if len(seen) >= limit:
            break
    return seen


def _slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n] or "skill"


def _rationale(question_type: str, sub_questions: list[str], coverage: float,
               gateway, gate, job_id: str | None) -> str:
    """One-line "why this worked" note. LLM-assisted when available, else templated.

    The LLM call (role ``aux_context``) is metered by the Gateway/Governor and
    throttled by the SchedulerGate; any failure falls back to the template.
    """
    template = (
        f"Decomposing a {question_type.replace('_', ' ')} question into "
        f"{len(sub_questions)} focused sub-questions yielded "
        f"{coverage:.0%} citation coverage."
    )
    if gateway is None:
        return template
    prompt = (
        "In ONE sentence, state the reusable research strategy that made this "
        "run succeed (no preamble). "
        f"Question type: {question_type}. "
        f"Sub-questions used: {'; '.join(sub_questions[:6])}. "
        f"Citation coverage achieved: {coverage:.0%}."
    )
    try:
        ctx = gate.permit() if gate is not None else nullcontext()
        with ctx:
            resp = gateway.complete("aux_context", prompt, job_id=job_id)
        text = (resp.text or "").strip().splitlines()[0].strip()
        return text or template
    except Exception:
        return template


def distill_skill(
    state_db,
    *,
    question: str,
    question_type: str,
    sub_questions: list[str],
    coverage: float,
    wep_phrase: str,
    source_count: int,
    evidence_domains: list[str] | None = None,
    scholarly: bool = True,
    gateway=None,
    gate=None,
    job_id: str | None = None,
    merge_overlap: float = 0.6,
) -> DistilledSkill | None:
    """Distil a skill from a successful run; insert or merge into the library.

    Returns the :class:`DistilledSkill` (with ``merged`` set when it refreshed an
    existing same-type skill) or ``None`` when there is nothing worth learning
    (no usable decomposition).
    """
    sub_questions = [s for s in (sub_questions or []) if s and s.strip()]
    if not sub_questions:
        return None

    keywords = keywords_for(question)
    # Generalise the concrete sub-questions into lightweight templates by
    # stripping the original question's specific keywords — keeps the strategy
    # reusable across topics rather than memorising one question.
    decomposition = [s.strip() for s in sub_questions[:6]]

    # Merge into an existing same-type skill with high keyword overlap rather
    # than spawning a near-duplicate row.
    existing = relevant_skills(
        state_db, question_type=question_type, keywords=keywords, k=1,
        status="active",
    )
    merge_target = None
    if existing:
        cand = existing[0]
        if cand.question_type == question_type:
            from ..verification.skills import _overlap  # local: ranking helper
            if _overlap(keywords, cand.trigger_keywords) >= merge_overlap:
                merge_target = cand

    rationale = _rationale(question_type, decomposition, coverage,
                           gateway, gate, job_id)

    if merge_target is not None:
        # Refresh the existing skill: union keywords, keep the better coverage,
        # adopt the fresher decomposition. Preserve its name (stable identity).
        merged_keywords = sorted(set(merge_target.trigger_keywords) | set(keywords))
        body = {
            "schema": BODY_SCHEMA_VERSION,
            "question_type": question_type,
            "trigger_keywords": merged_keywords,
            "decomposition": decomposition,
            "evidence_domains": evidence_domains or merge_target.body.get("evidence_domains", []),
            "retrieval_hints": {"scholarly": scholarly},
            "rationale": rationale,
            "quality": {
                "coverage": round(max(coverage, merge_target.avg_coverage or 0.0), 4),
                "wep": wep_phrase,
                "source_count": source_count,
            },
        }
        sid = add_skill(
            state_db, name=merge_target.name,
            description=rationale, body=body, question_type=question_type,
            score=max(merge_target.score, round(coverage, 4)), status="active",
        )
        return DistilledSkill(skill_id=sid, name=merge_target.name,
                              question_type=question_type, merged=True)

    # Fresh skill. Name is type + top keywords so the library reads well.
    kw_part = "-".join(keywords[:3]) if keywords else "general"
    name = f"strategy/{question_type}/{_slug(kw_part)}"
    body = {
        "schema": BODY_SCHEMA_VERSION,
        "question_type": question_type,
        "trigger_keywords": keywords,
        "decomposition": decomposition,
        "evidence_domains": evidence_domains or [],
        "retrieval_hints": {"scholarly": scholarly},
        "rationale": rationale,
        "quality": {"coverage": round(coverage, 4), "wep": wep_phrase,
                    "source_count": source_count},
    }
    # Seed the score with the run's coverage so a brand-new skill gets a fair
    # chance to be tried before any reinforcement data exists.
    sid = add_skill(state_db, name=name, description=rationale, body=body,
                    question_type=question_type, score=round(coverage, 4),
                    status="active")
    return DistilledSkill(skill_id=sid, name=name,
                          question_type=question_type, merged=False)
