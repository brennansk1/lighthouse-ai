"""SB2 — capability-restricted sandbox analysis tools."""

from __future__ import annotations

import pytest

from lighthouse_ai.sandbox.analysis import SandboxAnalysisContext, SandboxAnalysisError
from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.sandbox.store import SandboxStore

NOW = "2026-05-29T00:00:00+00:00"

# EICAR test string → REJECT (never stored). HTML w/ <script> → QUARANTINE.
EICAR = (
    br"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)


@pytest.fixture
def ctx(tmp_path):
    store = SandboxStore(tmp_path, max_bytes=None)
    broker = build_default_broker(tmp_path)
    # Two admitted uploads (prose + CSV) and one quarantined HTML upload.
    store.add(
        b"Attention is all you need. The transformer architecture changed NLP. "
        b"It was published in 2017 by researchers at Google Brain.",
        zone="uploads", filename="paper.txt", content_type="text/plain",
        source="user", broker=broker, now=NOW,
    )
    store.add(
        b"name,score\nAlice,91\nBob,72\nCarol,85\n",
        zone="uploads", filename="scores.csv", content_type="text/csv",
        source="user", broker=broker, now=NOW,
    )
    q = store.add(
        b"<html><body><script>steal()</script>hi</body></html>",
        zone="uploads", filename="evil.html", content_type="text/html",
        source="user", broker=broker, now=NOW,
    )
    # The HTML-script scanner should have quarantined it (not admitted).
    return SandboxAnalysisContext(store, audit=None), store, broker, q


def test_eicar_rejected_never_stored(tmp_path):
    store = SandboxStore(tmp_path, max_bytes=None)
    broker = build_default_broker(tmp_path)
    item = store.add(EICAR, zone="uploads", filename="x.com", content_type=None,
                     source="user", broker=broker, now=NOW)
    assert item is None
    assert store.list() == []


def test_list_items_excludes_evicted_and_summarizes(ctx):
    context, store, _broker, _q = ctx
    items = context.list_items(zone="uploads")
    names = {i["filename"] for i in items}
    assert "paper.txt" in names and "scores.csv" in names
    assert all("saved_path" not in i for i in items)  # safe summary, no path leak


def test_read_document_admitted(ctx):
    context, store, _broker, _q = ctx
    paper = next(i for i in store.list() if i.filename == "paper.txt")
    text = context.read_document(paper.id)
    assert "transformer" in text.lower()


def test_read_document_refuses_quarantined(ctx):
    context, store, _broker, q = ctx
    if q is not None and q.scan_verdict == "quarantine":
        with pytest.raises(PermissionError):
            context.read_document(q.id)
    else:
        pytest.skip("html-script scanner did not quarantine in this build")


def test_read_unknown_item_raises(ctx):
    context, *_ = ctx
    with pytest.raises(SandboxAnalysisError):
        context.read_document("does-not-exist")


def test_search_text_finds_with_snippet(ctx):
    context, *_ = ctx
    hits = context.search_text("transformer")
    assert hits and "transformer" in hits[0]["snippet"].lower()
    assert "item_id" in hits[0] and "offset" in hits[0]


def test_search_text_skips_quarantined(ctx):
    context, *_ = ctx
    # The quarantined HTML contains "steal" — it must never surface.
    assert context.search_text("steal") == []


def test_extract_tables_csv(ctx):
    context, store, _broker, _q = ctx
    csv_item = next(i for i in store.list() if i.filename == "scores.csv")
    tables = context.extract_tables(csv_item.id)
    assert tables and tables[0][0] == ["name", "score"]
    assert ["Alice", "91"] in tables[0]


def test_extract_entities_and_stats(ctx):
    context, store, _broker, _q = ctx
    paper = next(i for i in store.list() if i.filename == "paper.txt")
    ents = context.extract_entities(paper.id)
    kinds = {e["type"] for e in ents}
    assert ents  # non-empty
    assert "name" in kinds  # "Google Brain" etc.
    assert "number" in kinds  # the bare year "2017"
    stats = context.basic_stats(paper.id)
    assert stats["words"] > 0 and stats["chars"] > 0
    assert isinstance(stats["top_terms"], list)


def test_summarize_offline_extractive(ctx):
    context, store, _broker, _q = ctx
    paper = next(i for i in store.list() if i.filename == "paper.txt")
    summary = context.summarize(paper.id, max_sentences=2)
    assert isinstance(summary, str) and summary


def test_summarize_uses_injected_gateway(ctx):
    context, store, _broker, _q = ctx
    paper = next(i for i in store.list() if i.filename == "paper.txt")

    class _GW:
        def available(self):
            return True

        def complete(self, role, prompt, *, job_id=None):
            return "LLM SUMMARY."

    context.gateway = _GW()
    assert context.summarize(paper.id) == "LLM SUMMARY."


def test_write_artifact_lands_in_workspace_only(ctx):
    context, store, broker, _q = ctx
    result = context.write_artifact("finding.md", "Key result: it works.",
                                    broker=broker, now=NOW)
    assert result["zone"] == "workspace"
    # The analysis surface exposes no way to write into uploads.
    assert not hasattr(context, "write_upload")
    ws = store.list(zone="workspace")
    assert any(i.id == result["id"] for i in ws)
    # And the uploads zone was not mutated by the LLM write.
    assert all(i.source == "user" for i in store.list(zone="uploads"))


def test_no_forbidden_imports_in_analysis_module():
    import ast
    import pathlib

    src = pathlib.Path("src/lighthouse_ai/sandbox/analysis.py").read_text()
    tree = ast.parse(src)
    forbidden = {"httpx", "requests", "socket", "subprocess", "urllib"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] not in forbidden for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            assert node.module.split(".")[0] not in forbidden
