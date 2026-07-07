"""Adversarial claim-refutation pass (design: competitive thesis #2).

After synthesis, every *key* claim is handed to an independent skeptic that tries
to **refute** it against the same evidence. A claim that the skeptic can refute,
or that cannot be re-grounded, is downgraded — never asserted. This is the pass
single-shot frontier "deep research" skips: it makes survival, not fluency, the
bar for a claim.

Deterministic + offline by default. With ``gateway=None`` there is no model to
argue with, so we fall back to a conservative heuristic: a claim with no citation
is ``contested`` (unsupported), a cited claim ``stands``. Nothing is ever
*refuted* offline — refutation requires a model that found contradicting
evidence, so the offline path cannot manufacture one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Status = Literal["stands", "contested", "refuted"]

_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# Skeptic verdict markers the model is asked to emit on its first line.
_REFUTED = re.compile(r"\brefut", re.I)
_CONTESTED = re.compile(r"\bcontest|\bpartial|\bunclear|\bunsupported", re.I)
_STANDS = re.compile(r"\bstands?\b|\bsupported\b|\bupheld\b", re.I)


@dataclass(frozen=True)
class RefutationVerdict:
    claim: str
    status: Status
    reason: str = ""

    @property
    def survives(self) -> bool:
        return self.status == "stands"


def _has_citation(claim: str) -> bool:
    return bool(_CITATION.search(claim))


def _parse_verdict(text: str) -> tuple[Status, str]:
    """Map a skeptic reply to a status. First line is the verdict; rest is reason."""
    line, _, rest = text.strip().partition("\n")
    head = line.strip()
    reason = (rest.strip() or head)[:300]
    if _REFUTED.search(head):
        return "refuted", reason
    if _CONTESTED.search(head):
        return "contested", reason
    if _STANDS.search(head):
        return "stands", reason
    # Ambiguous reply → contested (precaution: don't let a vague answer pass).
    return "contested", reason


def _skeptic_prompt(claim: str, evidence: str) -> str:
    return (
        "You are a skeptical reviewer. Try to REFUTE the claim below using ONLY "
        "the evidence. Reply on the first line with exactly one word: REFUTED "
        "(evidence contradicts it), CONTESTED (evidence is insufficient or mixed), "
        "or STANDS (evidence clearly supports it). Then one sentence of reason.\n\n"
        f"CLAIM: {claim}\n\nEVIDENCE:\n{evidence[:2000]}\n"
    )


def refute_claim(
    claim: str, evidence: str, *, gateway=None, job_id: str | None = None
) -> RefutationVerdict:
    """Refutation verdict for a single claim. Deterministic offline."""
    if gateway is None:
        if not _has_citation(claim):
            return RefutationVerdict(claim, "contested", "no citation to support it")
        return RefutationVerdict(claim, "stands", "offline: cited, not adversarially tested")
    try:
        resp = gateway.complete("researcher", _skeptic_prompt(claim, evidence), job_id=job_id)
        status, reason = _parse_verdict(resp.text)
        return RefutationVerdict(claim, status, reason)
    except Exception:
        # A skeptic that errors must not silently pass the claim.
        return RefutationVerdict(claim, "contested", "skeptic unavailable")


def refute_claims(
    claims: list[str], evidence: str, *, gateway=None, job_id: str | None = None
) -> list[RefutationVerdict]:
    """Run the refutation pass over key claims. Order preserved."""
    return [refute_claim(c, evidence, gateway=gateway, job_id=job_id) for c in claims]


def summarize(verdicts: list[RefutationVerdict]) -> dict:
    """Compact roll-up for an artifact's body_json / provenance metrics."""
    n = len(verdicts)
    stands = sum(1 for v in verdicts if v.status == "stands")
    contested = sum(1 for v in verdicts if v.status == "contested")
    refuted = sum(1 for v in verdicts if v.status == "refuted")
    return {
        "checked": n,
        "stands": stands,
        "contested": contested,
        "refuted": refuted,
        "survival_rate": round(stands / n, 3) if n else 0.0,
    }
