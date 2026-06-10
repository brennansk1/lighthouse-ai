"""Mode E — Multi-perspective adversarial debate (§9.5).

For controversial claims, instantiate N perspectives (steelman, devil's
advocate, base-rate, fragility) and have them critique a draft answer.
A judge analyzes the critiques and names the single *load-bearing crux* — the
dispute that, if resolved, flips the conclusion — not a keyword agreement count.

Sprint 17 shipped a deterministic orchestrator + perspective stubs. This module
now adds the real LLM judge (gap #22): with a Gateway, the judge is a
``synthesizer`` role call that distinguishes substantive from rhetorical
disputes and surfaces the crux on :class:`DebateResult`. With ``gateway=None``
the judge degrades to the original deterministic heuristic — so offline tests
stay reproducible and there is no regression in the no-gateway path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..gateway import Gateway
from ..governor.scheduler_gate import SchedulerGate
from ._gate import gate_ctx


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
    # Additive fields (gap #22 — real LLM judge). Defaults keep existing
    # constructors valid and the offline heuristic path unchanged.
    #   crux: the single load-bearing dispute the judge names — the one that, if
    #         resolved, would flip the conclusion. Empty when the judge finds no
    #         load-bearing dispute (e.g. unanimous agreement) or runs offline.
    #   crux_perspective: which perspective surfaced the crux, if attributable.
    #   resolves_with: what evidence/observation would settle the crux.
    #   judge_backend: "llm" when a Gateway produced the verdict, else
    #         "heuristic" — lets callers/audit see which path ran.
    crux: str = ""
    crux_perspective: str | None = None
    resolves_with: str = ""
    judge_backend: str = "heuristic"


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
    gate: SchedulerGate | None = None,
) -> DebateResult:
    """Run each perspective on the claim+draft, then judge for the crux.

    With ``gateway=None`` every perspective is a deterministic stub and the
    judge is the keyword heuristic (``judge_backend="heuristic"``) — the
    original behaviour, preserved for offline/deterministic tests. With a
    Gateway, each perspective is a ``researcher`` role call and the judge is a
    ``synthesizer`` role call that names the load-bearing crux
    (``judge_backend="llm"``).
    """
    responses: list[PerspectiveResponse] = []
    for p in perspectives:
        if gateway is None:
            critique = _heuristic_response(p, claim, draft)
        else:
            prompt = (
                f"{p.prompt_template.format(claim=claim)}\n\n"
                f"DRAFT:\n{draft}\n\nCritique in 3-4 sentences."
            )
            # A gateway error on a *single* perspective must not abort the whole
            # debate (the "never crashes" contract). Degrade that perspective to
            # its deterministic heuristic stub and continue — only the judge call
            # was previously guarded, so one failing PERSPECTIVE took everything
            # down.
            try:
                with gate_ctx(gate):
                    resp = gateway.complete("researcher", prompt, job_id=job_id)
                critique = resp.text
            except Exception:
                critique = _heuristic_response(p, claim, draft)
        agrees = (agree_predicate or _default_agree)(critique)
        responses.append(PerspectiveResponse(perspective=p, critique=critique,
                                             agrees=agrees))

    agreements = [r.critique for r in responses if r.agrees]
    disputes = [r.critique for r in responses if not r.agrees]

    if gateway is None:
        return _heuristic_verdict(claim, draft, responses, agreements, disputes)
    return _llm_verdict(gateway, claim, draft, responses, agreements, disputes,
                        job_id=job_id, gate=gate)


def _heuristic_verdict(
    claim: str,
    draft: str,
    responses: list[PerspectiveResponse],
    agreements: list[str],
    disputes: list[str],
) -> DebateResult:
    """Deterministic fallback judge (no Gateway). Preserves the original summary
    format ('N/M perspectives agree. K disputes remain.') so existing callers
    and tests do not regress. The crux is left empty — the heuristic cannot
    reliably tell a load-bearing dispute from a rhetorical one."""
    summary = (f"{len(agreements)}/{len(responses)} perspectives agree. "
               f"{len(disputes)} disputes remain.")
    return DebateResult(claim=claim, draft=draft, responses=responses,
                        judge_summary=summary, agreements=agreements,
                        disputes=disputes, crux="", crux_perspective=None,
                        resolves_with="", judge_backend="heuristic")


# Sentinel lines the judge prompt asks the model to emit, so we can parse a
# structured verdict back without a JSON dependency.
_CRUX_TAG = "CRUX:"
_PERSPECTIVE_TAG = "PERSPECTIVE:"
_RESOLVES_TAG = "RESOLVES_WITH:"
_SUMMARY_TAG = "SUMMARY:"


def _judge_prompt(claim: str, draft: str,
                  responses: list[PerspectiveResponse]) -> str:
    """Build the synthesizer prompt that asks for the load-bearing crux.

    We deliberately instruct the judge to ignore rhetorical disagreement
    (tone, emphasis, restatement) and find the *one* substantive dispute whose
    resolution would flip the conclusion — the trustworthiness north star."""
    blocks = []
    for r in responses:
        blocks.append(
            f"[{r.perspective.name}] ({r.perspective.stance})\n{r.critique}"
        )
    perspectives_text = "\n\n".join(blocks)
    valid_names = ", ".join(r.perspective.name for r in responses)
    return (
        "You are the judge of an adversarial debate. The claim under debate "
        f"is:\n\n{claim}\n\nThe draft answer being critiqued:\n\n{draft}\n\n"
        "The perspectives' critiques:\n\n"
        f"{perspectives_text}\n\n"
        "Your job is NOT to count who agrees. Distinguish SUBSTANTIVE disputes "
        "(different facts, different load-bearing assumptions, different "
        "evidence) from RHETORICAL ones (tone, emphasis, restatement). Then "
        "name the single LOAD-BEARING CRUX: the one dispute that, if resolved, "
        "would FLIP the conclusion. If the perspectives substantively agree and "
        "no dispute is load-bearing, say so.\n\n"
        "Reply in exactly these lines:\n"
        f"{_CRUX_TAG} <one sentence naming the load-bearing crux, or 'none'>\n"
        f"{_PERSPECTIVE_TAG} <which perspective raised it: one of "
        f"[{valid_names}], or 'none'>\n"
        f"{_RESOLVES_TAG} <what evidence or observation would resolve it>\n"
        f"{_SUMMARY_TAG} <one-sentence verdict>"
    )


def _parse_judge(text: str, valid_names: set[str]) -> dict:
    """Parse the tagged judge reply. Tolerant of missing/extra lines and of a
    model that ignores the format (returns empties so callers degrade)."""
    out = {"crux": "", "crux_perspective": None, "resolves_with": "",
           "summary": ""}
    for raw in text.splitlines():
        line = raw.strip()
        if line.upper().startswith(_CRUX_TAG):
            val = line[len(_CRUX_TAG):].strip()
            out["crux"] = "" if val.lower() in ("none", "n/a", "") else val
        elif line.upper().startswith(_PERSPECTIVE_TAG):
            val = line[len(_PERSPECTIVE_TAG):].strip()
            out["crux_perspective"] = val if val in valid_names else None
        elif line.upper().startswith(_RESOLVES_TAG):
            out["resolves_with"] = line[len(_RESOLVES_TAG):].strip()
        elif line.upper().startswith(_SUMMARY_TAG):
            out["summary"] = line[len(_SUMMARY_TAG):].strip()
    return out


def _llm_verdict(
    gateway: Gateway,
    claim: str,
    draft: str,
    responses: list[PerspectiveResponse],
    agreements: list[str],
    disputes: list[str],
    *,
    job_id: str | None,
    gate: SchedulerGate | None = None,
) -> DebateResult:
    """Real judge: a ``synthesizer`` role call analyses every critique and names
    the load-bearing crux. Any failure (gateway error, unparseable reply) falls
    back to the deterministic heuristic verdict so a run never crashes on the
    judge step."""
    valid_names = {r.perspective.name for r in responses}
    try:
        prompt = _judge_prompt(claim, draft, responses)
        with gate_ctx(gate):
            resp = gateway.complete("synthesizer", prompt, job_id=job_id)
        parsed = _parse_judge(resp.text, valid_names)
    except Exception:
        return _heuristic_verdict(claim, draft, responses, agreements, disputes)

    crux = parsed["crux"]
    if not crux:
        # Judge found no load-bearing dispute → unanimous-enough verdict.
        summary = parsed["summary"] or (
            f"{len(agreements)}/{len(responses)} perspectives agree; "
            "no load-bearing dispute identified."
        )
        return DebateResult(claim=claim, draft=draft, responses=responses,
                            judge_summary=summary, agreements=agreements,
                            disputes=disputes, crux="",
                            crux_perspective=parsed["crux_perspective"],
                            resolves_with=parsed["resolves_with"],
                            judge_backend="llm")

    summary = parsed["summary"] or (
        f"Load-bearing crux: {crux}"
    )
    return DebateResult(claim=claim, draft=draft, responses=responses,
                        judge_summary=summary, agreements=agreements,
                        disputes=disputes, crux=crux,
                        crux_perspective=parsed["crux_perspective"],
                        resolves_with=parsed["resolves_with"],
                        judge_backend="llm")


def _default_agree(critique: str) -> bool:
    """Naive sentiment: 'agree' or 'support' present and 'refute'/'wrong' absent."""
    low = critique.lower()
    pos = any(k in low for k in ("agree", "support", "consistent", "proceed"))
    neg = any(k in low for k in ("refute", "wrong", "fragile", "fails", "counter"))
    return pos and not neg
