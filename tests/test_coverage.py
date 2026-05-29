"""Offline tests for the coverage/completeness critic (no real LLM)."""

from __future__ import annotations

from dataclasses import dataclass

from lighthouse_ai.verification.coverage import (
    assess_coverage,
    find_missing_angles,
    needs_another_round,
)


@dataclass
class _Section:
    sub_question: str
    body: str


SUBS = ["What is the cost?", "What is the risk?", "What is the timeline?"]


def test_all_covered_is_complete():
    secs = [_Section(q, "A substantive answer with more than eight words here indeed.")
            for q in SUBS]
    rep = assess_coverage(SUBS, secs)
    assert rep.total == 3 and rep.covered == 3
    assert rep.gaps == []
    assert rep.complete
    assert not needs_another_round(rep)


def test_uncovered_subquestion_is_a_gap():
    secs = [
        _Section(SUBS[0], "A substantive answer with more than eight words here indeed."),
        _Section(SUBS[1], "short"),          # too short → not covered
        # SUBS[2] missing entirely
    ]
    rep = assess_coverage(SUBS, secs)
    assert rep.covered == 1
    assert SUBS[1] in rep.gaps and SUBS[2] in rep.gaps
    assert needs_another_round(rep)
    assert 0.0 < rep.coverage_ratio < 1.0


def test_accepts_dict_sections():
    secs = [{"sub_question": SUBS[0], "body": "word " * 10}]
    rep = assess_coverage(SUBS, secs)
    assert rep.covered == 1
    assert len(rep.gaps) == 2


def test_find_missing_angles_offline_returns_empty():
    assert find_missing_angles("Q", "draft", gateway=None) == []


def test_find_missing_angles_parses_model_lines():
    @dataclass
    class _Resp:
        text: str

    class _GW:
        def complete(self, role, prompt, *, job_id=None):
            return _Resp("- Long-term maintenance cost\n- Vendor lock-in\nNONE")
    angles = find_missing_angles("Q", "draft", gateway=_GW())
    assert angles == ["Long-term maintenance cost", "Vendor lock-in"]
