"""Mode E — Multi-perspective adversarial debate (§9.5).

For controversial claims, instantiate N perspectives (steelman, devil's
advocate, base-rate, fragility) and have them critique a draft answer.
A judge sums up agreements and unresolved disputes.

Sprint 17 ships a deterministic orchestrator + perspective stubs; in
production each perspective is a Gateway role with its own system prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..gateway import Gateway


@dataclass(frozen=True)
class Perspective:
    name: str
    stance: str  # short description of the perspective's prior
    prompt_template: str


@dataclass(frozen=True)
class PerspectiveResponse:
    perspective: Perspective
    critique: str
    agrees: bool


@dataclass(frozen=True)
class DebateResult:
    claim: str
    draft: str
    responses: list[PerspectiveResponse]
    judge_summary: str
    agreements: list[str]
    disputes: list[str]


# --- canonical perspective set (extend per topic in production) ---

PERSPECTIVES: tuple[Perspective, ...] = (
    Perspective("steelman", "strongest version of the claim",
                "Strengthen the claim '{claim}' with the best supporting argument."),
    Perspective("devils_advocate", "strongest counter-claim",
                "Refute '{claim}' with the strongest counter-argument."),
    Perspective("base_rate", "reference-class outside view",
                "What is the historical base rate that bears on '{claim}'?"),
    Perspective("fragility", "if-wrong analysis",
                "If '{claim}' is wrong, what fails first?"),
)


def _heuristic_response(perspective: Perspective, claim: str, draft: str) -> str:
    """Deterministic perspective response used when no Gateway is wired."""
    return (f"[{perspective.name}] On '{claim}': {perspective.stance}. "
            f"Considering the draft ({len(draft)} chars), proceed with caution.")


def run_debate(
    claim: str,
    draft: str,
    *,
    gateway: Gateway | None = None,
    perspectives: tuple[Perspective, ...] = PERSPECTIVES,
    agree_predicate: Callable[[str], bool] | None = None,
    job_id: str | None = None,
) -> DebateResult:
    """Run each perspective on the claim+draft and collect responses."""
    responses: list[PerspectiveResponse] = []
    for p in perspectives:
        if gateway is None:
            critique = _heuristic_response(p, claim, draft)
        else:
            prompt = (
                f"{p.prompt_template.format(claim=claim)}\n\n"
                f"DRAFT:\n{draft}\n\nCritique in 3-4 sentences."
            )
            resp = gateway.complete("researcher", prompt, job_id=job_id)
            critique = resp.text
        agrees = (agree_predicate or _default_agree)(critique)
        responses.append(PerspectiveResponse(perspective=p, critique=critique,
                                             agrees=agrees))

    agreements = [r.critique for r in responses if r.agrees]
    disputes = [r.critique for r in responses if not r.agrees]
    summary = (f"{len(agreements)}/{len(responses)} perspectives agree. "
               f"{len(disputes)} disputes remain.")
    return DebateResult(claim=claim, draft=draft, responses=responses,
                        judge_summary=summary, agreements=agreements,
                        disputes=disputes)


def _default_agree(critique: str) -> bool:
    """Naive sentiment: 'agree' or 'support' present and 'refute'/'wrong' absent."""
    low = critique.lower()
    pos = any(k in low for k in ("agree", "support", "consistent", "proceed"))
    neg = any(k in low for k in ("refute", "wrong", "fragile", "fails", "counter"))
    return pos and not neg
