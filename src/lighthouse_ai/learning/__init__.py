"""Self-learning research skills — distil reusable strategies from successful
runs, retrieve and apply them on future questions, reinforce what works, and
archive what doesn't (Hermes/Voyager-style skill library).

The closed loop:
  distil  → :func:`lighthouse_ai.learning.distiller.distill_skill`
  retrieve→ :func:`lighthouse_ai.learning.retrieval.select_skills`
  apply   → planner-prompt injection (framing) + record_application
  reinforce→ verification.skills.complete_application (updates score)
  prune   → verification.skills.prune_skills

All persistence + scoring lives in :mod:`lighthouse_ai.verification.skills`.
"""

from __future__ import annotations

from .distiller import DistilledSkill, distill_skill, keywords_for
from .retrieval import format_for_planner, select_skills

__all__ = [
    "DistilledSkill",
    "distill_skill",
    "format_for_planner",
    "keywords_for",
    "select_skills",
]
