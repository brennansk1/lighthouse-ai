"""Skill retrieval — pick learned strategies relevant to a new question and
format them for injection into the planner prompt.

This is the "apply" half of the self-learning loop. It is pure/deterministic
(no LLM, no network): given a question it classifies the type, extracts
keywords, and asks the skill store for the most relevant active skills. The
caller threads the formatted block into framing and records applications so the
reinforcement step can later attribute outcomes.
"""

from __future__ import annotations

from ..verification.skills import Skill, relevant_skills
from .distiller import keywords_for


def select_skills(state_db, question: str, *, question_type: str | None = None,
                  k: int = 3) -> list[Skill]:
    """Return up to ``k`` active learned skills relevant to ``question``.

    ``question_type`` may be passed when the caller has already framed the
    question; otherwise type-matching is skipped and ranking falls back to
    keyword overlap + effectiveness.
    """
    keywords = keywords_for(question)
    return relevant_skills(state_db, question_type=question_type or "",
                           keywords=keywords, k=k, status="active")


def format_for_planner(skills: list[Skill]) -> str:
    """Render skills as a compact, additive planner-prompt block.

    Returns "" when there are no skills so the caller can omit the section
    entirely (keeps the deterministic-framing path byte-identical when nothing
    has been learned yet).
    """
    if not skills:
        return ""
    lines = ["Learned strategies that worked on similar questions before "
             "(use as guidance, adapt as needed):"]
    for i, s in enumerate(skills, 1):
        decomp = "; ".join(s.decomposition[:5])
        rationale = (s.description or s.body.get("rationale") or "").strip()
        lines.append(f"{i}. [{s.question_type or 'general'}] {rationale}")
        if decomp:
            lines.append(f"   Decomposition that worked: {decomp}")
    return "\n".join(lines)
