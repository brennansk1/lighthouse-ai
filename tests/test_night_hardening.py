"""Regression tests for the 2026-07 night-sprint hardening fixes.

Each test pins a specific bug found in the user-facing path so it can't
silently come back. Grouped by the subsystem the fix landed in.
"""

from __future__ import annotations

import sys
import types
import warnings


# --- C3: no pynvml deprecation warning on macOS ------------------------------

def test_detect_nvidia_returns_empty_on_darwin_without_warning(monkeypatch):
    """On darwin, GPU detection must not import pynvml (which prints a
    FutureWarning on every command). It returns [] cleanly."""
    import lighthouse_ai.hardware as hw
    monkeypatch.setattr(sys, "platform", "darwin")
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning becomes an exception
        assert hw._detect_nvidia_gpus() == []


# --- P1: entailment scorer caches a construction failure ---------------------

def test_entailment_caches_load_failure(monkeypatch):
    """If MiniCheck is importable but construction throws, the failure is cached
    with a sentinel so subsequent claims don't each re-attempt the 770M load."""
    import lighthouse_ai.verification.entailment as ent

    calls = {"n": 0}

    class _BoomMiniCheck:
        def __init__(self, **_kw):
            calls["n"] += 1
            raise RuntimeError("broken weights / cache_dir")

    fake_pkg = types.ModuleType("minicheck")
    fake_mod = types.ModuleType("minicheck.minicheck")
    fake_mod.MiniCheck = _BoomMiniCheck
    monkeypatch.setitem(sys.modules, "minicheck", fake_pkg)
    monkeypatch.setitem(sys.modules, "minicheck.minicheck", fake_mod)
    monkeypatch.setattr(ent, "_minicheck_available", lambda: True)
    monkeypatch.setattr(ent, "_scorer", None, raising=False)
    monkeypatch.setattr(ent, "_scorer_kind", None, raising=False)

    assert ent.score_claim("a claim", "some grounding") is None
    assert ent.score_claim("another", "more grounding") is None
    assert calls["n"] == 1  # constructed once; failure cached, not retried


# --- P3: a mid-run retrieval failure degrades the section, not the job -------

def test_research_section_degrades_when_retrieval_raises():
    """If hybrid.search raises mid-run (Qdrant restart / dim mismatch), the
    section degrades to no-evidence instead of the whole job crashing."""
    from lighthouse_ai.modes.deepdive import Section, _research_section

    class _BoomHybrid:
        def search(self, *_a, **_k):
            raise RuntimeError("qdrant connection dropped")

    section = Section(title="S1", sub_question="what changed?", body="")
    out_section, evidence = _research_section(
        section, _BoomHybrid(), None, job_id="j1")  # gateway=None → stub body
    assert evidence == []                 # degraded, not raised
    assert out_section.body               # still produced a (stub) body


# --- W1: one malformed JSON row must not 500 a whole list endpoint -----------

def test_json_field_degrades_malformed_row_to_empty():
    """_json_field returns {} on malformed JSON instead of raising (which would
    500 the entire jobs/audit list on a single corrupt row)."""
    from lighthouse_ai.web.api import _json_field

    assert _json_field({"metadata_json": "{not valid json"}, "metadata_json") == {}
    assert _json_field({"metadata_json": None}, "metadata_json") == {}
    assert _json_field({"metadata_json": '{"a": 1}'}, "metadata_json") == {"a": 1}
    # A valid-but-non-object JSON (e.g. a bare list) also degrades to {}.
    assert _json_field({"metadata_json": "[1,2,3]"}, "metadata_json") == {}
