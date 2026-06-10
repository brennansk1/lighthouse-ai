"""Research pipeline tests — all offline/stub (no model load, no network)."""

from __future__ import annotations

import json

from lighthouse_ai.gateway import resolve_against_installed
from lighthouse_ai.hardware import GPUInfo, HardwareProfile
from lighthouse_ai.persistence import open_db
from lighthouse_ai.pipeline import (
    PipelineConfig,
    ResearchPipeline,
    make_embedder,
    make_vector_store,
)


def _profile(ram=25.77, tier="T2") -> HardwareProfile:
    return HardwareProfile(
        platform="macos", arch="arm64", apple_silicon=True,
        total_ram_gb=ram, free_ram_gb=ram / 2, cpu_cores_physical=10,
        cpu_cores_logical=10, gpu=[GPUInfo("Apple", ram, "apple")],
        unified_memory=True, available_backends=["cpu", "ollama"],
        suggested_tier=tier,
    )


# --- factories (offline) ---

def test_make_embedder_offline_is_hash():
    emb, name, warns = make_embedder(offline=True)
    assert name == "hash-stub"
    assert emb.embed(["hello world"])  # works


def test_make_vector_store_offline_is_inmemory():
    store, name, warns = make_vector_store(64, offline=True)
    assert name == "in-memory"
    assert store.count() == 0


def test_make_embedder_fallback_returns_warning():
    _emb, name, warns = make_embedder(offline=False, installed=[])
    assert name == "hash-stub"
    assert len(warns) >= 1
    assert any("hash-stub" in w or "embedding" in w or "Ollama" in w for w in warns)


def test_make_embedder_offline_returns_no_warning():
    _emb, name, warns = make_embedder(offline=True)
    assert name == "hash-stub"
    assert warns == []


def test_research_result_has_warnings_field(migrated_paths):
    pipe = ResearchPipeline(migrated_paths, config=PipelineConfig(offline=True))
    result = pipe.research("test question")
    assert hasattr(result, "warnings")
    assert isinstance(result.warnings, list)


# --- resolver ---

def test_resolve_picks_installed_reasoning_and_aux():
    installed = ["qwen3:14b-q4_K_M", "llama3.1:8b", "bge-m3:latest", "gemma2:27b"]
    res = resolve_against_installed(_profile(), installed)
    # reasoning roles bound to a real installed tag that fits 24 GB
    assert res["planner"] in installed
    assert res["planner"] == res["researcher"] == res["synthesizer"]
    assert res["aux_context"] in installed
    assert res["embedding"].split(":")[0] == "bge-m3"


def test_resolve_empty_when_nothing_installed():
    assert resolve_against_installed(_profile(), []) == {}


def test_resolve_respects_budget_prefers_fitting():
    # On a 24 GB box, a 70b tag shouldn't be chosen over a 14b that fits.
    installed = ["llama3.3:70b", "qwen3:14b-q4_K_M"]
    res = resolve_against_installed(_profile(ram=25.77), installed)
    assert "14b" in res["planner"]


# --- pipeline end-to-end (offline) ---

def test_pipeline_offline_deepdive_stages_draft(migrated_paths):
    pipe = ResearchPipeline(migrated_paths,
                            config=PipelineConfig(offline=True, mode="deep-dive"))
    assert pipe.backends == {"embedder": "hash-stub", "vector_store": "in-memory",
                             "gateway": "mock"}
    pipe.ingest_text("d1", "Quantum computing uses qubits. Superposition matters.")
    result = pipe.research("What is quantum computing?")
    assert result.draft_id.startswith("d-")
    assert result.sections >= 1
    assert result.chunks_ingested >= 1
    # draft persisted + staged
    conn = open_db(migrated_paths.state_db)
    try:
        row = conn.execute("SELECT status, title FROM drafts WHERE id=?",
                           (result.draft_id,)).fetchone()
        job = conn.execute("SELECT status FROM jobs WHERE id IS NOT NULL "
                           "ORDER BY created_at DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row[0] == "staged"
    assert job[0] == "review"


def test_pipeline_offline_quc_stages_draft(migrated_paths):
    pipe = ResearchPipeline(migrated_paths,
                            config=PipelineConfig(offline=True, mode="quc"))
    pipe.ingest_text("d1", "The Fed sets interest rates via the discount window.")
    result = pipe.research("How does the Fed set rates?")
    assert result.mode == "quc"
    assert result.answer is not None
    conn = open_db(migrated_paths.state_db)
    try:
        n = conn.execute("SELECT COUNT(*) FROM drafts WHERE status='staged'").fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_pipeline_draft_visible_via_api(migrated_paths):
    from fastapi.testclient import TestClient

    from lighthouse_ai.controlplane import create_app
    pipe = ResearchPipeline(migrated_paths, config=PipelineConfig(offline=True))
    pipe.ingest_text("d1", "Some facts about a topic. More facts here.")
    result = pipe.research("Tell me about the topic")
    client = TestClient(create_app(migrated_paths))
    drafts = client.get("/api/drafts?status=staged").json()["drafts"]
    assert any(d["id"] == result.draft_id for d in drafts)
    detail = client.get(f"/api/drafts/{result.draft_id}").json()
    assert "<h2>" in detail["body_html"] or detail["body_html"]


def test_pipeline_audit_event_written(migrated_paths):
    pipe = ResearchPipeline(migrated_paths, config=PipelineConfig(offline=True))
    pipe.research("question with no corpus")
    conn = open_db(migrated_paths.audit_db)
    try:
        rows = conn.execute(
            "SELECT payload_json FROM audit_events WHERE event_type='draft.staged'"
        ).fetchall()
    finally:
        conn.close()
    assert rows
    assert "backends" in json.loads(rows[0][0])


def test_pipeline_runs_without_corpus(migrated_paths):
    """A research run with zero ingested docs still produces a staged draft."""
    pipe = ResearchPipeline(migrated_paths, config=PipelineConfig(offline=True))
    result = pipe.research("Compare X and Y")
    assert result.draft_id
    assert result.chunks_ingested == 0


def test_pipeline_records_positions_and_discipline(migrated_paths):
    """Research now closes the calibration loop: claims → positions + a
    discipline report with citation coverage."""
    pipe = ResearchPipeline(migrated_paths, config=PipelineConfig(offline=True))
    pipe.ingest_text("d1", "Quantum decoherence is the main challenge. "
                           "Error correction mitigates noise. Qubits are fragile.")
    result = pipe.research("What is the main challenge in quantum computing?")
    # discipline summary attached
    assert result.discipline is not None
    assert "coverage" in result.discipline
    # positions recorded
    n = open_db(migrated_paths.positions_db).execute(
        "SELECT COUNT(*) FROM positions").fetchone()[0]
    assert n >= 1
    # draft has a WEP band derived from discipline
    row = open_db(migrated_paths.state_db).execute(
        "SELECT wep_band, confidence FROM drafts WHERE id=?",
        (result.draft_id,)).fetchone()
    assert row[0] is not None       # WEP band set
    assert row[1] is not None       # confidence recorded


def test_pipeline_calibration_has_data_after_research(migrated_paths):
    """The /api/calibration endpoint reports the positions a research run made."""
    from fastapi.testclient import TestClient

    from lighthouse_ai.controlplane import create_app
    pipe = ResearchPipeline(migrated_paths, config=PipelineConfig(offline=True))
    pipe.research("Some question about a topic with claims.")
    client = TestClient(create_app(migrated_paths))
    # positions exist (unresolved → show in overdue/positions list)
    positions = client.get("/api/positions").json()["positions"]
    assert len(positions) >= 1


# --- CLI: lighthouse research --offline ---

def test_cli_research_offline_stages_draft(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from lighthouse_ai.cli import app
    data = tmp_path / "data"
    monkeypatch.setenv("LIGHTHOUSE_DATA_DIR", str(data))
    doc = tmp_path / "facts.txt"
    doc.write_text("Alpha relates to beta. Beta causes gamma. Gamma is observable.")
    runner = CliRunner()
    r = runner.invoke(app, ["research", "How does alpha relate to gamma?",
                            "--doc", str(doc), "--offline"])
    assert r.exit_code == 0, r.stdout
    assert "staged draft" in r.stdout
    # the draft is queryable
    from lighthouse_ai.persistence import open_db
    conn = open_db(data / "state.db")
    try:
        n = conn.execute("SELECT COUNT(*) FROM drafts WHERE status='staged'").fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_cli_research_missing_doc_errors(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from lighthouse_ai.cli import app
    monkeypatch.setenv("LIGHTHOUSE_DATA_DIR", str(tmp_path / "data"))
    runner = CliRunner()
    r = runner.invoke(app, ["research", "q", "--doc", str(tmp_path / "nope.txt"),
                            "--offline"])
    assert r.exit_code != 0


# --- Sprint 28 step 1: reranker selection ---

def test_pipeline_picks_reranker(migrated_paths, monkeypatch):
    """ResearchPipeline(offline=True) must select ScoreReranker (prefer_real=False).

    When offline=False and FlagEmbedding is importable the pipeline should
    select FlagReranker (prefer_real=True). We verify both branches without
    loading any real model.
    """
    from lighthouse_ai.pipeline import PipelineConfig, ResearchPipeline
    from lighthouse_ai.rag.flag_reranker import FlagReranker
    from lighthouse_ai.rag.rerank import ScoreReranker

    # Branch 1 — offline=True → prefer_real=False → ScoreReranker fallback.
    pipe_offline = ResearchPipeline(migrated_paths,
                                    config=PipelineConfig(offline=True))
    assert isinstance(pipe_offline.reranker, ScoreReranker), (
        "offline pipeline should have a ScoreReranker (no real model loading)"
    )

    # Branch 2 — offline=False but FlagEmbedding NOT importable → ScoreReranker.
    # Monkeypatch _flag_embedding_importable to return False so no download occurs.
    monkeypatch.setattr(FlagReranker, "_flag_embedding_importable",
                        staticmethod(lambda: False))
    pipe_online = ResearchPipeline(migrated_paths,
                                   config=PipelineConfig(offline=False))
    assert isinstance(pipe_online.reranker, ScoreReranker), (
        "online pipeline without FlagEmbedding should fall back to ScoreReranker"
    )

    # Branch 3 — offline=False AND FlagEmbedding importable → FlagReranker.
    monkeypatch.setattr(FlagReranker, "_flag_embedding_importable",
                        staticmethod(lambda: True))
    pipe_real = ResearchPipeline(migrated_paths,
                                 config=PipelineConfig(offline=False))
    assert isinstance(pipe_real.reranker, FlagReranker), (
        "online pipeline with FlagEmbedding available should use FlagReranker"
    )


# --- Sprint 29 Step 4: auto web retrieval when corpus is empty ---

import httpx
import respx

ARXIV_XML_ONE = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.auto01</id>
    <title>Auto Fetch Test Paper</title>
    <summary>This is a test abstract for auto-fetching. It contains enough words.</summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Test Author</name></author>
  </entry>
</feed>'''

OPENALEX_EMPTY = {"results": [], "meta": {"count": 0}}


@respx.mock
def test_pipeline_auto_fetches_when_corpus_empty(migrated_paths):
    """Auto-fetch fires when corpus is empty and not offline."""
    respx.get(url__regex=r"export\.arxiv\.org").mock(
        return_value=httpx.Response(200, content=ARXIV_XML_ONE))
    respx.get(url__regex=r"api\.openalex\.org").mock(
        return_value=httpx.Response(200, json=OPENALEX_EMPTY))

    pipe = ResearchPipeline(migrated_paths,
                            config=PipelineConfig(offline=True, auto_fetch_sources=True))
    # Temporarily flip offline so _auto_fetch runs but the gateway stays mock
    pipe.config = PipelineConfig(offline=False, auto_fetch_sources=True)
    pipe._auto_fetch("quantum computing")
    assert pipe._chunks_ingested >= 1


def test_pipeline_no_auto_fetch_when_offline(migrated_paths):
    """offline=True must never trigger auto-fetch."""
    pipe = ResearchPipeline(migrated_paths,
                            config=PipelineConfig(offline=True, auto_fetch_sources=True))
    result = pipe.research("quantum computing")
    assert result.chunks_ingested == 0


def test_pipeline_no_auto_fetch_when_corpus_nonempty(migrated_paths):
    """Auto-fetch skipped when documents were pre-ingested."""
    pipe = ResearchPipeline(migrated_paths, config=PipelineConfig(offline=True))
    pipe.ingest_text("d1", "Quantum computing uses qubits for computation.")
    assert pipe._chunks_ingested > 0
    result = pipe.research("quantum computing")
    assert result.chunks_ingested >= 1


def test_pipeline_auto_fetch_disabled_by_flag(migrated_paths):
    """auto_fetch_sources=False prevents any auto-fetch even with empty corpus."""
    pipe = ResearchPipeline(migrated_paths,
                            config=PipelineConfig(offline=True, auto_fetch_sources=False))
    result = pipe.research("some question")
    assert result.chunks_ingested == 0


def test_pipeline_passes_evidence_to_discipline_gate(migrated_paths, monkeypatch):
    """The discipline gate must receive the run's evidence chunks — without
    them, fabricated-citation detection silently never runs on the main
    research path (regression for the zero-fabricated-citations invariant)."""
    from lighthouse_ai.verification import discipline as disc

    seen: dict = {}
    real_check = disc.check

    def _spy(text, **kwargs):
        seen["evidence_chunks"] = kwargs.get("evidence_chunks")
        return real_check(text, **kwargs)

    monkeypatch.setattr(disc, "check", _spy)
    pipe = ResearchPipeline(migrated_paths,
                            config=PipelineConfig(offline=True, mode="deep-dive"))
    pipe.ingest_text("d1", "Quantum computing uses qubits. Superposition matters.")
    pipe.research("What is quantum computing?")
    assert "evidence_chunks" in seen, "gate was never called"
    ev = seen["evidence_chunks"]
    assert ev is not None and len(ev) >= 1
