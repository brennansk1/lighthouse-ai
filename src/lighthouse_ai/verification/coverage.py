"""Coverage / completeness critic (design: competitive thesis #3).

Gemini Deep Research's depth comes from a self-critique loop that hunts for gaps.
We match it and make it *auditable*: coverage is scored against the explicit
research plan (the framing planner's load-bearing sub-questions). A sub-question
with no substantive, evidenced section is a **gap** that should trigger another
research round; when the depth budget is exhausted, remaining gaps are recorded
as explicit *known unknowns* rather than silently dropped.

Two layers:
- ``assess_coverage`` — deterministic, offline: which planned sub-questions are
  answered vs. open. This is the termination signal (with evidence saturation).
- ``find_missing_angles`` — optional, real-backend: asks a model what angle the
  draft hasn't considered *at all*. Offline returns ``[]`` (no model to ask).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CoverageReport:
    total: int  # planned (load-bearing) sub-questions
    covered: int  # sub-questions with a substantive section
    gaps: list[str] = field(default_factory=list)  # uncovered sub-questions
    coverage_ratio: float = 1.0
    missing_angles: list[str] = field(default_factory=list)  # real-backend extras

    @property
    def complete(self) -> bool:
        return not self.gaps and not self.missing_angles


def _field(obj, name, default=""):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def assess_coverage(sub_questions, sections, *, min_body_words: int = 8) -> CoverageReport:
    """Score plan coverage. A sub-question counts as covered when a section ties
    to it AND that section has a substantive body (>= ``min_body_words`` words).

    ``sections`` items may be dataclasses (Section) or dicts with
    ``sub_question`` and ``body``. Order of ``gaps`` follows ``sub_questions``.
    """
    covered_qs: set[str] = set()
    for s in sections:
        sq = _field(s, "sub_question", "") or ""
        body = _field(s, "body", "") or ""
        if sq and len(str(body).split()) >= min_body_words:
            covered_qs.add(sq)
    gaps = [q for q in sub_questions if q not in covered_qs]
    total = len(sub_questions)
    covered = total - len(gaps)
    ratio = round(covered / total, 3) if total else 1.0
    return CoverageReport(total=total, covered=covered, gaps=gaps, coverage_ratio=ratio)


def needs_another_round(report: CoverageReport) -> bool:
    """True while the plan still has uncovered sub-questions (deepen further)."""
    return bool(report.gaps)


_LINE = re.compile(r"^\s*[-*\d.]+\s*")


def find_missing_angles(
    question: str, draft_text: str, *, gateway=None, job_id: str | None = None, max_angles: int = 3
) -> list[str]:
    """Ask a model what angle the draft hasn't considered. Offline → ``[]``."""
    if gateway is None:
        return []
    prompt = (
        "You are a research editor. List up to "
        f"{max_angles} important angles, sub-questions, or counter-considerations "
        "that the draft below does NOT yet address for the research question. "
        "One per line, terse. If the draft is comprehensive, reply 'NONE'.\n\n"
        f"QUESTION: {question}\n\nDRAFT:\n{draft_text[:3000]}\n"
    )
    try:
        resp = gateway.complete("planner", prompt, job_id=job_id)
    except Exception:
        return []
    out: list[str] = []
    for raw in resp.text.splitlines():
        line = _LINE.sub("", raw).strip()
        if not line or line.upper() == "NONE":
            continue
        out.append(line[:200])
        if len(out) >= max_angles:
            break
    return out
