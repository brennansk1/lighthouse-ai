"""Regression tests for the 2026-07 night-sprint hardening fixes.

Each test pins a specific bug found in the user-facing path so it can't
silently come back. Grouped by the subsystem the fix landed in.
"""

from __future__ import annotations

import sys
import types
import warnings

import pytest

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
        section, _BoomHybrid(), None, job_id="j1"
    )  # gateway=None → stub body
    assert evidence == []  # degraded, not raised
    assert out_section.body  # still produced a (stub) body


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


# --- C1: disk-pull preflight sizes real Ollama tags, not just class names ----


def test_preflight_sizes_real_ollama_tags():
    """The disk-safety preflight must estimate a size for the REAL tags
    recommend_pull_tag hands users (e.g. 'qwen3:14b-q4_K_M'), not fall through
    to the 'unknown size' branch that bypassed the headroom check."""
    from lighthouse_ai.gateway import estimate_download_gb, preflight_pull

    est = estimate_download_gb("qwen3:14b-q4_K_M")
    assert 7.0 <= est <= 11.0, f"14B tag should size ~9 GB, got {est}"
    # On a tight disk the recommended pull is now correctly REFUSED (the bug:
    # it was allowed because size was treated as unknown).
    assert preflight_pull("qwen3:14b-q4_K_M", free_disk_gb=12.0).ok is False
    # With ample room it proceeds.
    assert preflight_pull("qwen3:14b-q4_K_M", free_disk_gb=26.0).ok is True


# --- W2: an empty-but-present table still exports its headers ----------------


def test_empty_survey_table_csv_keeps_headers():
    """A survey whose screening kept zero rows must still export the attribute
    headers, not silently collapse to a one-column title CSV."""
    from lighthouse_ai.web.api import _artifact_to_csv

    body = {"rows": [], "attributes": [{"label": "sample size"}, {"label": "outcome"}]}
    csv_text = _artifact_to_csv({"title": "Empty Survey"}, body)
    header = csv_text.splitlines()[0]
    assert "doc_id" in header and "sample size" in header and "outcome" in header
    assert header != "title"


# --- W4: an overflowed SSE subscriber gets a reconnect sentinel -------------


def test_sse_overflow_enqueues_reconnect_sentinel():
    """When a subscriber's queue fills, the bus must enqueue the overflow
    sentinel (so the stream closes + client reconnects) rather than silently
    orphaning the queue (which left the tab permanently without live updates)."""
    from lighthouse_ai.web.events import _OVERFLOW, EventBus

    bus = EventBus(max_queue=1)
    q = bus.subscribe()  # no running loop → publish delivers inline
    bus.publish("job.step", {"n": 1})  # fills the depth-1 queue
    bus.publish("job.step", {"n": 2})  # overflow → drop oldest, enqueue sentinel
    assert q.get_nowait() is _OVERFLOW


# --- Phase E: SSRF / DNS-rebinding egress guard -----------------------------


def test_egress_blocks_link_local_metadata_endpoint():
    """The cloud-metadata endpoint (link-local) is never a legitimate target,
    even as a literal IP."""
    from lighthouse_ai.net import EgressBlocked, _reject_non_public_host

    with pytest.raises(EgressBlocked):
        _reject_non_public_host("http://169.254.169.254/latest/meta-data")


def test_egress_blocks_public_name_resolving_to_private(monkeypatch):
    """A public hostname that resolves into internal space is the DNS-rebinding
    attack the hostname-only allowlist misses — it must be refused."""
    from lighthouse_ai import net

    monkeypatch.setattr(net.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 0))])
    with pytest.raises(net.EgressBlocked):
        net._reject_non_public_host("http://evil.example.com/x")


def test_egress_allows_intentional_local_services():
    """Literal loopback/LAN IPs and localhost are legitimate local targets
    (SearXNG, Qdrant) — the guard must not block them."""
    from lighthouse_ai.net import _reject_non_public_host

    # None of these raise.
    _reject_non_public_host("http://127.0.0.1:8888/search")
    _reject_non_public_host("http://192.168.1.10:6333/collections")
    _reject_non_public_host("http://localhost:8765/")
    _reject_non_public_host("http://8.8.8.8/x")  # public literal IP


def test_egress_private_guard_opt_out(monkeypatch):
    from lighthouse_ai import net

    monkeypatch.setenv("LIGHTHOUSE_ALLOW_PRIVATE_EGRESS", "1")
    monkeypatch.setattr(net.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 0))])
    net._reject_non_public_host("http://evil.example.com/x")  # opted out → no raise
