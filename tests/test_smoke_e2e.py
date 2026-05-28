"""End-to-end smoke test — exercises every major subsystem in one flow."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from lighthouse_ai.controlplane import create_app
from lighthouse_ai.gateway import Gateway
from lighthouse_ai.governor import BUDGET_DEFAULTS, Governor
from lighthouse_ai.hardware import HardwareProfile
from lighthouse_ai.intents import outbox_depth, write_intent
from lighthouse_ai.effector import Effector, clear_targets
from lighthouse_ai.modes.deepdive import run_deepdive
from lighthouse_ai.modes.monitor import MonitorItem, run_monitor
from lighthouse_ai.output.html import render_monitor_html
from lighthouse_ai.persistence import open_db
from lighthouse_ai.rag import (
    BM25Index, Document, HashEmbedder, HybridSearch, InMemoryStore,
    ScoreReranker, chunk_document,
)
from lighthouse_ai.sandbox import (
    ArchiveBombScanner, HTMLScriptScanner, PDFJavaScriptScanner,
    Quarantine, SandboxBroker, Verdict,
)
from lighthouse_ai.targets import test_target
from lighthouse_ai.verification import (
    append_event, band_for_probability, record_position, resolve_position,
    score_all, seal_event_chain, verify_audit_chain,
)


def test_full_pipeline_from_ingest_to_dashboard(migrated_paths):
    """One test that touches every subsystem and confirms nothing wedges."""
    paths = migrated_paths

    # 1. Sandbox: admit a clean HTML, reject a script-laden one.
    q = Quarantine(paths.data_dir / "quarantine.db", paths.data_dir / "Q")
    broker = SandboxBroker(q, [
        PDFJavaScriptScanner(), HTMLScriptScanner(), ArchiveBombScanner(),
    ])
    clean = broker.admit(b"<html><p>clean content</p></html>",
                         filename="x.html", content_type="text/html")
    bad = broker.admit(b"<script>e()</script>",
                       filename="y.html", content_type="text/html")
    assert clean.verdict is Verdict.ADMIT
    assert bad.verdict is Verdict.QUARANTINE

    # 2. RAG: chunk + embed + hybrid search.
    e = HashEmbedder(dim=128)
    hs = HybridSearch(InMemoryStore(), e, BM25Index(), reranker=ScoreReranker())
    docs = [
        Document(id="d1", text="Quantum chips rely on qubits and superposition."),
        Document(id="d2", text="Classical chips rely on transistors and voltage."),
        Document(id="d3", text="Decoherence is the chief challenge for quantum systems."),
    ]
    for d in docs:
        hs.add(chunk_document(d))
    hits = hs.search("quantum qubits", top_k=2)
    assert hits

    # 3. Framing + Deep-Dive.
    report = run_deepdive("Compare classical and quantum chips",
                          hybrid=hs, max_rounds=2)
    assert report.sections
    assert report.framing.sub_questions

    # 4. Monitor + HTML.
    items = [
        MonitorItem(source="rss", url="https://x/1",
                    title="Breaking: new qubit fidelity record",
                    body="Researchers report a major breakthrough. " * 20,
                    published_at="2026-05-27T09:00:00Z"),
    ]
    mr = run_monitor("quantum", items)
    html = render_monitor_html(mr)
    assert "quantum" in html

    # 5. Governor + Gateway: a real model call through the mock provider.
    g = Governor(paths.state_db, BUDGET_DEFAULTS)
    profile = HardwareProfile(platform="macos", arch="arm64", apple_silicon=True,
                              total_ram_gb=64.0, free_ram_gb=32.0,
                              cpu_cores_physical=8, cpu_cores_logical=8,
                              gpu=[], unified_memory=True,
                              available_backends=["cpu", "ollama"],
                              suggested_tier="T3")
    gw = Gateway(g, paths.audit_db, profile=profile)
    resp = gw.complete("planner", "Hello, planner.", job_id="smoke-1")
    assert resp.text

    # 6. Outbox + effector: write 5 intents, drain, all applied.
    clear_targets()
    test_target.reset()
    test_target.install()
    for i in range(5):
        write_intent(paths.intents_db, target="test_target", op="upsert",
                     payload={"i": i}, idempotency_key=f"smoke-{i}")
    assert outbox_depth(paths.intents_db) == 5
    counts = Effector(paths.intents_db).run_until_empty()
    assert counts.get("applied") == 5
    assert outbox_depth(paths.intents_db) == 0

    # 7. Verification: record + resolve a position, score the registry.
    pos = record_position(paths.positions_db,
                          claim="Quantum supremacy holds for >1k qubits by 2030",
                          probability=0.6)
    assert band_for_probability(0.6).name == "likely"
    resolve_position(paths.positions_db, pos.id, outcome=True)
    metrics = score_all(paths.positions_db)
    assert metrics["n"] == 1

    # 8. Audit chain: the gateway wrote unsigned `model_call` events earlier;
    # seal the pre-existing chain, then append new signed events and verify.
    secret = b"smoke-secret"
    seal_event_chain(paths.audit_db, secret=secret)
    for i in range(3):
        append_event(paths.audit_db, actor="smoke", event_type="tick",
                     payload={"i": i}, secret=secret)
    bad = verify_audit_chain(paths.audit_db, secret=secret)
    assert bad == []

    # 9. Control plane: /health, /governor, /api/dashboard, /ui/ all work.
    client = TestClient(create_app(paths))
    health = client.get("/health").json()
    assert health["supervisor"]["status"] in {"running", "uninitialized", "unmigrated"}
    assert health["databases"]["audit"]["integrity_check"] == "ok"
    gov = client.get("/governor").json()
    assert gov["kill_switched"] is False
    dash = client.get("/api/dashboard").json()
    assert "calibration" in dash
    assert dash["calibration"]["resolved"] == 1  # the resolved position
    ui = client.get("/ui/")
    assert ui.status_code == 200
    assert "Lighthouse" in ui.text
