"""Quality discipline layer (design §12) — the mechanical enforcement that
makes Lighthouse output *honest*: every claim must be sourced, high-stakes
claims need two independent sources, and unsourced claims get their
confidence (WEP band) downgraded rather than silently asserted.

This is deliberately rule-based and deterministic — the design's principle
is "enforced by linters and gates, not by hoping the LLM behaves."
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .wep import WEPBand, band_for_probability

# A claim is a declarative sentence. We split on sentence boundaries and drop
# fragments / questions. Citation markers look like [1], [2,3], or [n].
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass(frozen=True)
class Claim:
    text: str
    citation_ids: list[int] = field(default_factory=list)

    @property
    def is_sourced(self) -> bool:
        return len(self.citation_ids) >= 1

    @property
    def is_two_sourced(self) -> bool:
        return len(set(self.citation_ids)) >= 2


@dataclass(frozen=True)
class DisciplineReport:
    claims: list[Claim]
    sourced: int
    unsourced: int
    two_sourced: int
    citation_coverage: float          # fraction of claims with >=1 citation
    passed: bool                      # meets the configured floor
    notes: list[str] = field(default_factory=list)


def extract_claims(text: str) -> list[Claim]:
    """Pull declarative, citeable claims out of a synthesis block.

    Skips questions and very short fragments. Captures inline [N] citations.
    """
    claims: list[Claim] = []
    # Strip HTML tags if any slipped in.
    plain = re.sub(r"<[^>]+>", " ", text)
    for raw in _SENTENCE_SPLIT.split(plain):
        s = raw.strip()
        if len(s.split()) < 3:          # 1-2 word fragment / heading
            continue
        if s.endswith("?"):             # a question is not a claim
            continue
        ids: list[int] = []
        for m in _CITATION.finditer(s):
            ids.extend(int(x) for x in re.split(r"\s*,\s*", m.group(1)))
        claims.append(Claim(text=s, citation_ids=ids))
    return claims


def check(text: str, *, min_coverage: float = 0.6,
          high_stakes: bool = False) -> DisciplineReport:
    """Run the discipline gate over a synthesis block.

    ``min_coverage`` — required fraction of claims carrying >=1 citation.
    ``high_stakes`` — when True, claims should satisfy the two-source rule.
    """
    claims = extract_claims(text)
    if not claims:
        return DisciplineReport(claims=[], sourced=0, unsourced=0, two_sourced=0,
                                citation_coverage=0.0, passed=False,
                                notes=["no extractable claims"])
    sourced = sum(1 for c in claims if c.is_sourced)
    unsourced = len(claims) - sourced
    two = sum(1 for c in claims if c.is_two_sourced)
    coverage = sourced / len(claims)
    notes: list[str] = []
    passed = coverage >= min_coverage
    if not passed:
        notes.append(f"citation coverage {coverage:.0%} below floor {min_coverage:.0%}")
    if high_stakes and two < sourced:
        notes.append(f"two-source rule: only {two}/{sourced} sourced claims "
                     f"have >=2 independent citations")
        passed = passed and (two >= sourced)
    return DisciplineReport(claims=claims, sourced=sourced, unsourced=unsourced,
                            two_sourced=two, citation_coverage=round(coverage, 3),
                            passed=passed, notes=notes)


def downgrade_wep(probability: float, report: DisciplineReport) -> WEPBand:
    """Lower the confidence band when sourcing is weak.

    Honest-over-impressive: a well-written but poorly-sourced answer should
    not be presented as 'almost certain'. We scale the stated probability by
    citation coverage before mapping to a band.
    """
    adjusted = probability * max(report.citation_coverage, 0.1)
    return band_for_probability(min(max(adjusted, 0.0), 1.0))
