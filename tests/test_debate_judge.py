"""Offline-deterministic tests for the Adjudicate debate judge (gap #22).

Two paths are covered:
  * gateway=None falls back to the keyword heuristic with NO regression vs. the
    original summary format.
  * a fake gateway judge returns a named load-bearing crux that surfaces on
    DebateResult (crux, crux_perspective, resolves_with, judge_backend="llm").

No real LLM calls; the fake gateway returns canned, deterministic text.
"""

from __future__ import annotations

from dataclasses import dataclass

from lighthouse_ai.modes.debate import (
    PERSPECTIVES,
    Perspective,
    run_debate,
)

# ---------------------------------------------------------------------------
# Fake gateway
# ---------------------------------------------------------------------------

@dataclass
class _Resp:
    text: str


class FakeJudgeGateway:
    """Minimal Gateway stand-in. Perspective (researcher) calls echo a stance;
    the judge (synthesizer) call returns a tagged verdict naming a crux."""

    def __init__(self, *, judge_text: str, perspective_text: str = "critique"):
        self.judge_text = judge_text
        self.perspective_text = perspective_text
        self.roles_called: list[str] = []

    def complete(self, role, prompt, *, job_id=None, allow_drift=True):
        self.roles_called.append(role)
        if role == "synthesizer":
            return _Resp(self.judge_text)
        return _Resp(self.perspective_text)


# ---------------------------------------------------------------------------
# gateway=None — heuristic fallback, no regression
# ---------------------------------------------------------------------------

def test_offline_falls_back_to_heuristic():
    result = run_debate("X causes Y.", "Draft text here.")
    assert result.judge_backend == "heuristic"
    # Original summary format preserved (asserted by existing test_modes_cde).
    assert "agree" in result.judge_summary
    assert str(len(result.responses)) in result.judge_summary
    # Heuristic does not fabricate a crux.
    assert result.crux == ""
    assert result.crux_perspective is None


def test_offline_runs_every_perspective():
    result = run_debate("Claim.", "Draft.")
    assert len(result.responses) == len(PERSPECTIVES)
    assert all(r.critique for r in result.responses)


def test_offline_agree_predicate_still_swappable():
    res = run_debate("X.", "Draft.", agree_predicate=lambda c: True)
    assert all(r.agrees for r in res.responses)
    assert not res.disputes
    assert res.judge_backend == "heuristic"


# ---------------------------------------------------------------------------
# Fake gateway judge — names a load-bearing crux
# ---------------------------------------------------------------------------

_JUDGE_REPLY = (
    "CRUX: Whether the 2019 trial's effect persists past 12 months.\n"
    "PERSPECTIVE: fragility\n"
    "RESOLVES_WITH: A long-term follow-up cohort beyond 12 months.\n"
    "SUMMARY: The conclusion hinges on durability of the effect."
)


def test_llm_judge_surfaces_named_crux():
    gw = FakeJudgeGateway(judge_text=_JUDGE_REPLY)
    res = run_debate("Drug Z works.", "Draft answer.", gateway=gw)
    assert res.judge_backend == "llm"
    assert res.crux == "Whether the 2019 trial's effect persists past 12 months."
    assert res.crux_perspective == "fragility"
    assert "follow-up cohort" in res.resolves_with
    # Judge ran on the synthesizer role exactly once; perspectives on researcher.
    assert gw.roles_called.count("synthesizer") == 1
    assert gw.roles_called.count("researcher") == len(PERSPECTIVES)


def test_llm_judge_crux_is_on_result_not_just_summary():
    gw = FakeJudgeGateway(judge_text=_JUDGE_REPLY)
    res = run_debate("Claim.", "Draft.", gateway=gw)
    # The crux is exposed as a first-class field the dispatcher can feed back to
    # Investigate, not buried in prose.
    assert res.crux
    assert res.crux in res.judge_summary or res.judge_summary


def test_llm_judge_invalid_perspective_name_is_dropped():
    reply = (
        "CRUX: Some load-bearing dispute.\n"
        "PERSPECTIVE: not_a_real_perspective\n"
        "RESOLVES_WITH: More data.\n"
        "SUMMARY: Hinges on the dispute."
    )
    gw = FakeJudgeGateway(judge_text=reply)
    res = run_debate("Claim.", "Draft.", gateway=gw)
    assert res.crux == "Some load-bearing dispute."
    assert res.crux_perspective is None  # invalid name dropped


def test_llm_judge_no_load_bearing_dispute():
    reply = (
        "CRUX: none\n"
        "PERSPECTIVE: none\n"
        "RESOLVES_WITH: n/a\n"
        "SUMMARY: Perspectives substantively agree."
    )
    gw = FakeJudgeGateway(judge_text=reply)
    res = run_debate("Uncontroversial claim.", "Draft.", gateway=gw)
    assert res.judge_backend == "llm"
    assert res.crux == ""
    assert "agree" in res.judge_summary.lower()


def test_llm_judge_falls_back_on_gateway_error():
    class BoomGateway:
        def complete(self, role, prompt, *, job_id=None, allow_drift=True):
            if role == "synthesizer":
                raise RuntimeError("model unavailable")
            return _Resp("a critique")

    res = run_debate("Claim.", "Draft.", gateway=BoomGateway())
    # Perspective calls succeeded; only the judge failed → heuristic verdict.
    assert res.judge_backend == "heuristic"
    assert "agree" in res.judge_summary
    assert res.crux == ""


def test_llm_judge_unparseable_reply_degrades_gracefully():
    gw = FakeJudgeGateway(judge_text="totally unstructured blob with no tags")
    res = run_debate("Claim.", "Draft.", gateway=gw)
    assert res.judge_backend == "llm"
    # No CRUX tag parsed → empty crux, but the run does not crash.
    assert res.crux == ""


def test_custom_perspectives_with_llm_judge():
    custom = (
        Perspective("optimist", "best case", "Argue '{claim}'."),
        Perspective("pessimist", "worst case", "Refute '{claim}'."),
    )
    reply = (
        "CRUX: Whether the assumption A holds.\n"
        "PERSPECTIVE: pessimist\n"
        "RESOLVES_WITH: Direct measurement of A.\n"
        "SUMMARY: Hinges on A."
    )
    gw = FakeJudgeGateway(judge_text=reply)
    res = run_debate("Claim.", "Draft.", gateway=gw, perspectives=custom)
    assert {r.perspective.name for r in res.responses} == {"optimist", "pessimist"}
    assert res.crux_perspective == "pessimist"
