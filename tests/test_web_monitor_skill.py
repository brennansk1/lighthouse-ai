"""Tests for the web_monitor watchable skill (Watch v2).

Loading + import-guard are exercised against the real skill folder via
``load_skill``. The run/run_watchable logic is driven with a fake ``ctx`` so the
tests are fully offline and deterministic (no broker, no network, no clock).
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path

from lighthouse_ai.skills import load_skill

SKILL_ID = "web_monitor"

# Import the skill module directly so we can call run / run_watchable with a
# fake ctx without going through the dispatcher's real SkillContext.
_SKILL_PY = (
    Path(__file__).resolve().parents[1] / "src/lighthouse_ai/skills/library/web_monitor/skill.py"
)
_spec = importlib.util.spec_from_file_location("_web_monitor_skill", _SKILL_PY)
assert _spec and _spec.loader
skill_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(skill_mod)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeResponse:
    status_code: int = 200
    headers: dict = field(default_factory=dict)
    content: bytes = b""


@dataclass
class FakeDoc:
    id: str
    text: str
    metadata: dict


class FakeCtx:
    """Duck-typed SkillContext: fetch returns canned responses; document funcs
    record what they made. ``responses`` maps URL -> (bytes, headers)."""

    def __init__(self, responses: dict[str, tuple[bytes, dict]]):
        self._responses = responses
        self.effective_domains = frozenset({"example.com"})

    def fetch(self, url: str, **_kw):
        body, headers = self._responses.get(url, (b"", {}))
        return FakeResponse(status_code=200, headers=headers, content=body)

    def fetch_and_document(self, url: str, *, extra_meta=None, **_kw):
        body, _headers = self._responses.get(url, (None, {}))
        if body is None:
            return None
        # Mimic the broker+extract step by decoding the body as text.
        text = body.decode("utf-8", errors="replace")
        meta = dict(extra_meta or {})
        return FakeDoc(id=f"doc:{url}", text=text, metadata=meta)

    def make_document(self, *, doc_id: str, text: str, metadata=None):
        return FakeDoc(id=doc_id, text=text, metadata=dict(metadata or {}))


# ---------------------------------------------------------------------------
# load + import guard
# ---------------------------------------------------------------------------


def test_skill_loads_and_passes_import_guard():
    skill = load_skill(SKILL_ID)
    assert skill.manifest.id == SKILL_ID
    assert skill.manifest.watchable is True
    assert skill.watchable_entrypoint is not None
    assert callable(skill.watchable_entrypoint)


def test_manifest_fields():
    m = load_skill(SKILL_ID).manifest
    assert m.category == "channel"
    assert m.tier == "A"
    assert m.signed is True
    assert m.output_shape == "stream"
    assert "check_url" in m.watchable_tools
    assert m.allowed_domains == ()


# ---------------------------------------------------------------------------
# run — one-shot pre-flight
# ---------------------------------------------------------------------------


def test_run_emits_verdict_document():
    rich = b"<html><body><p>" + b"word " * 80 + b"</p></body></html>"
    ctx = FakeCtx({"https://example.com/page": (rich, {"ETag": '"a"'})})
    docs = skill_mod.run(ctx, "watch https://example.com/page")
    assert len(docs) == 1
    d = docs[0]
    assert d.metadata["type"] == "scrapability_verdict"
    assert d.metadata["verdict"] in {"good", "limited", "blocked"}
    assert d.metadata["url"] == "https://example.com/page"


def test_run_no_urls_returns_empty():
    ctx = FakeCtx({})
    assert skill_mod.run(ctx, "no url here") == []


# ---------------------------------------------------------------------------
# run_watchable — baseline then change
# ---------------------------------------------------------------------------

URL = "https://example.com/page"


def test_run_watchable_first_tick_is_baseline():
    ctx = FakeCtx({URL: (b"line one\nline two", {})})
    docs = skill_mod.run_watchable(ctx, URL)
    assert len(docs) == 1
    d = docs[0]
    assert d.metadata["type"] == "web_monitor_baseline"
    assert d.metadata["change"] is False
    assert "snapshot" in d.metadata


def test_run_watchable_detects_change_between_two_fetches():
    # Tick 1: baseline.
    ctx1 = FakeCtx({URL: (b"old content here", {})})
    base = skill_mod.run_watchable(ctx1, URL)[0]
    snap = base.metadata["snapshot"]

    # Tick 2: new content, prior snapshot passed back via the ||SNAPSHOTS|| marker.
    ctx2 = FakeCtx({URL: (b"brand new content line", {})})
    query = f"{URL} ||SNAPSHOTS|| {json.dumps({URL: snap})}"
    docs = skill_mod.run_watchable(ctx2, query)

    assert len(docs) == 1
    d = docs[0]
    assert d.metadata["type"] == "web_monitor_change"
    assert d.metadata["change"] is True
    assert "snapshot" in d.metadata
    assert d.metadata["diff"]["changed"] is True


def test_run_watchable_no_change_emits_nothing():
    ctx1 = FakeCtx({URL: (b"stable content", {})})
    base = skill_mod.run_watchable(ctx1, URL)[0]
    snap = base.metadata["snapshot"]

    ctx2 = FakeCtx({URL: (b"stable content", {})})
    query = f"{URL} ||SNAPSHOTS|| {json.dumps({URL: snap})}"
    docs = skill_mod.run_watchable(ctx2, query)
    assert docs == []


def test_run_watchable_keyword_criteria():
    ctx1 = FakeCtx({URL: (b"all clear no issues", {})})
    base = skill_mod.run_watchable(ctx1, URL)[0]
    snap = base.metadata["snapshot"]

    crit = json.dumps({"kind": "keyword", "terms": ["recall"]})
    ctx2 = FakeCtx({URL: (b"safety recall issued today", {})})
    query = f"{URL} ||CRITERIA|| {crit} ||SNAPSHOTS|| {json.dumps({URL: snap})}"
    docs = skill_mod.run_watchable(ctx2, query)

    assert len(docs) == 1
    assert docs[0].metadata["change"] is True
    assert "recall" in docs[0].text.lower()


def test_run_watchable_no_urls_returns_empty():
    ctx = FakeCtx({})
    assert skill_mod.run_watchable(ctx, "nothing here") == []
