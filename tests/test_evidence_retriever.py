"""Resolver evidence retriever — re-fetch at the deadline, never parametric memory.

Covers ``resolver.default_criterion`` (machine vs human) and
``evidence.build_evidence_retriever`` (graceful None paths + joined evidence).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lighthouse_ai.verification import evidence as E
from lighthouse_ai.verification import resolver as R


# --- default_criterion -------------------------------------------------------
def test_default_criterion_machine_gets_one_human_defers():
    assert R.default_criterion("Did the agency approve the drug by 2026?") is not None
    assert R.default_criterion("Should we invest in nuclear energy?") is None


# --- build_evidence_retriever: graceful None paths ---------------------------
def test_retriever_none_without_gateway(migrated_paths):
    assert E.build_evidence_retriever(migrated_paths, gateway=None) is None


def test_retriever_none_without_broker(migrated_paths, monkeypatch):
    monkeypatch.setattr("lighthouse_ai.sandbox.broker.build_default_broker", lambda *a, **k: None)
    assert E.build_evidence_retriever(migrated_paths, gateway=object()) is None


# --- build_evidence_retriever: behavior with a (faked) broker + skills -------
@dataclass
class _Doc:
    id: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class _Run:
    documents: list


def _patch_broker_and_skill(monkeypatch, run_result):
    monkeypatch.setattr(
        "lighthouse_ai.sandbox.broker.build_default_broker", lambda *a, **k: object()
    )  # any non-None broker
    monkeypatch.setattr("lighthouse_ai.skills.load_skill", lambda sid: object())
    monkeypatch.setattr("lighthouse_ai.skills.run_skill", lambda *a, **k: run_result)


def test_retriever_joins_evidence_and_picks_source(migrated_paths, monkeypatch):
    docs = [
        _Doc("d1", "First evidence.", {"url": "https://ex/1"}),
        _Doc("d2", "Second evidence.", {}),
    ]
    _patch_broker_and_skill(monkeypatch, _Run(docs))
    retr = E.build_evidence_retriever(migrated_paths, gateway=object())
    assert retr is not None
    out = retr("Did X happen?", "criterion", "2026-01-01")
    assert out is not None
    text, src = out
    assert "First evidence." in text and "Second evidence." in text
    assert src == "https://ex/1"  # first doc's url wins as the source id


def test_retriever_none_when_no_documents(migrated_paths, monkeypatch):
    _patch_broker_and_skill(monkeypatch, _Run([]))
    retr = E.build_evidence_retriever(migrated_paths, gateway=object())
    assert retr("q", None, "") is None


def test_retriever_none_when_all_docs_empty(migrated_paths, monkeypatch):
    _patch_broker_and_skill(monkeypatch, _Run([_Doc("d", "   ", {})]))
    retr = E.build_evidence_retriever(migrated_paths, gateway=object())
    assert retr("q", None, "") is None


def test_retriever_swallows_fetch_errors(migrated_paths, monkeypatch):
    monkeypatch.setattr(
        "lighthouse_ai.sandbox.broker.build_default_broker", lambda *a, **k: object()
    )

    def _boom(_sid):
        raise RuntimeError("network down")

    monkeypatch.setattr("lighthouse_ai.skills.load_skill", _boom)
    retr = E.build_evidence_retriever(migrated_paths, gateway=object())
    assert retr("q", None, "") is None  # degrades to defer, never raises
