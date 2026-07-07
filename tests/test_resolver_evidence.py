"""Evidence-grounded resolution + human deferral (improvement-memo change 1).

The resolver must NEVER grade a claim from the model's own memory: it resolves
only from retrieved evidence, else defers to the human queue.
"""

from __future__ import annotations

import pytest

from lighthouse_ai.persistence import open_db
from lighthouse_ai.verification import resolver as R
from lighthouse_ai.verification.positions import (
    _ensure_extras,
    list_human_queue,
    record_position,
)


class _Resp:
    def __init__(self, text):
        self.text = text


class _Gateway:
    def __init__(self, text):
        self._text = text

    def complete(self, role, prompt, **kw):
        return _Resp(self._text)


def _retriever(
    text="As of the date, the agency published the approval.", src="https://example.gov/doc"
):
    return lambda claim, criterion, as_of: (text, src)


_NONE_RETRIEVER = lambda c, cr, a: None  # noqa: E731 — offline / nothing found


def test_defers_without_criterion():
    r = R.attempt_auto_resolve(
        1,
        "Will the drug be approved?",
        0.7,
        criterion=None,
        retriever=_retriever(),
        gateway=_Gateway("TRUE: 0.9 — yes"),
    )
    assert r.auto_resolved is False and r.outcome is None
    assert r.resolver_kind == "human"


def test_defers_human_claim():
    r = R.attempt_auto_resolve(
        1,
        "Should we invest in nuclear energy?",
        0.6,
        criterion="net-positive ROI",
        retriever=_retriever(),
        gateway=_Gateway("TRUE: 0.9 — yes"),
    )
    assert r.auto_resolved is False and r.resolver_kind == "human"


def test_defers_offline_no_evidence():
    # criterion + machine claim, but the retriever finds nothing → defer, NOT a
    # memory-based guess.
    r = R.attempt_auto_resolve(
        1,
        "Did the agency approve the drug by 2026?",
        0.7,
        criterion="FDA approval notice exists",
        retriever=_NONE_RETRIEVER,
        gateway=_Gateway("TRUE: 0.99 — yes"),
    )
    assert r.auto_resolved is False and r.outcome is None
    assert "evidence" in r.defer_reason.lower()


def test_defers_when_no_gateway():
    r = R.attempt_auto_resolve(
        1,
        "Did the agency approve the drug by 2026?",
        0.7,
        criterion="approval notice",
        retriever=_retriever(),
        gateway=None,
    )
    assert r.auto_resolved is False


def test_resolves_from_evidence_records_provenance():
    r = R.attempt_auto_resolve(
        1,
        "Did the agency approve the drug by 2026?",
        0.8,
        criterion="An official approval notice exists",
        retriever=_retriever(
            "The agency issued an approval notice in March 2025.", "https://example.gov/approval"
        ),
        gateway=_Gateway("TRUE: 0.9 — the notice confirms approval"),
    )
    assert r.auto_resolved is True and r.outcome is True
    assert r.resolver_kind == "machine_retrieval" and r.resolved_via == "retrieval"
    assert r.resolution_source == "https://example.gov/approval"
    assert r.evidence_snapshot and "approval notice" in r.evidence_snapshot
    assert r.brier == pytest.approx((0.8 - 1.0) ** 2, abs=1e-9)


def test_defers_on_uncertain_or_lowconf():
    unc = R.attempt_auto_resolve(
        1,
        "Did X happen by 2026?",
        0.7,
        criterion="X recorded",
        retriever=_retriever(),
        gateway=_Gateway("UNCERTAIN: — evidence unclear"),
    )
    assert unc.auto_resolved is False
    low = R.attempt_auto_resolve(
        1,
        "Did X happen by 2026?",
        0.7,
        criterion="X recorded",
        retriever=_retriever(),
        gateway=_Gateway("TRUE: 0.4 — weakly"),
    )
    assert low.auto_resolved is False


def test_run_pass_resolves_and_defers(migrated_paths):
    db = migrated_paths.positions_db
    _ensure_extras(db)
    # one machine-resolvable (with criterion), one with no criterion → human queue.
    p1 = record_position(
        db,
        claim="Did the agency approve the drug by 2026?",
        probability=0.8,
        resolve_by="2000-01-01T00:00:00",
        resolution_criterion="An approval notice exists",
    )
    p2 = record_position(
        db, claim="Will it rain a lot next year?", probability=0.6, resolve_by="2000-01-01T00:00:00"
    )
    results = R.run_resolver_pass(
        db,
        gateway=_Gateway("TRUE: 0.9 — confirmed by the notice"),
        retriever=_retriever("Approval notice issued.", "u1"),
    )
    assert len(results) == 2
    # p1 resolved with provenance; p2 deferred to the human queue.
    row = (
        open_db(db)
        .execute("SELECT outcome, resolver_kind, resolved_via FROM positions WHERE id=?", (p1.id,))
        .fetchone()
    )
    assert row[0] == 1 and row[1] == "machine_retrieval" and row[2] == "retrieval"
    queue = list_human_queue(db)
    assert any(q["position_id"] == p2.id for q in queue)
