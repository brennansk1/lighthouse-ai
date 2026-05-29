"""Offline tests for the adversarial claim-refutation pass (no real LLM)."""

from __future__ import annotations

from dataclasses import dataclass

from lighthouse_ai.verification.adversarial import (
    refute_claim,
    refute_claims,
    summarize,
)


@dataclass
class _Resp:
    text: str


class _FakeGateway:
    """Returns a scripted skeptic reply per call (FIFO)."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    def complete(self, role, prompt, *, job_id=None):
        self.calls += 1
        return _Resp(self._replies.pop(0) if self._replies else "STANDS\nok")


# --- offline (deterministic) ---

def test_offline_uncited_claim_is_contested():
    v = refute_claim("Remote work boosts output.", "evidence", gateway=None)
    assert v.status == "contested"
    assert not v.survives


def test_offline_cited_claim_stands():
    v = refute_claim("Remote work boosts output [1].", "evidence", gateway=None)
    assert v.status == "stands"
    assert v.survives


def test_offline_never_refutes():
    # Without a model there is no evidence-based refutation.
    vs = refute_claims(["A [1].", "B.", "C [2]."], "ev", gateway=None)
    assert all(v.status != "refuted" for v in vs)


# --- real-ish (fake gateway) ---

def test_gateway_refuted_verdict():
    gw = _FakeGateway(["REFUTED\nThe evidence shows the opposite."])
    v = refute_claim("X causes Y [1].", "ev", gateway=gw)
    assert v.status == "refuted"
    assert "opposite" in v.reason


def test_gateway_ambiguous_reply_is_contested():
    gw = _FakeGateway(["I'm not sure about this one."])
    v = refute_claim("X causes Y [1].", "ev", gateway=gw)
    assert v.status == "contested"  # vague reply must not pass


def test_gateway_error_is_contested():
    class _Boom:
        def complete(self, *a, **k):
            raise RuntimeError("down")
    v = refute_claim("X [1].", "ev", gateway=_Boom())
    assert v.status == "contested"


def test_refute_claims_preserves_order_and_summarize():
    gw = _FakeGateway(["STANDS\nok", "REFUTED\nno", "CONTESTED\nmixed"])
    vs = refute_claims(["a [1].", "b [1].", "c [1]."], "ev", gateway=gw)
    assert [v.status for v in vs] == ["stands", "refuted", "contested"]
    s = summarize(vs)
    assert s == {"checked": 3, "stands": 1, "contested": 1, "refuted": 1,
                 "survival_rate": round(1 / 3, 3)}
