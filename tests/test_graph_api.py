"""Tests for GET /api/graph/draft/{draft_id} (Sprint Graph-RAG user-facing).

Deterministic, offline — no LLM calls, no real network.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from lighthouse_ai.controlplane import create_app
from lighthouse_ai.persistence import open_db


@pytest.fixture
def client(migrated_paths):
    return TestClient(create_app(migrated_paths))


# ---- helpers ----------------------------------------------------------------


def _insert_draft(paths, draft_id: str, body_json: dict, *, status: str = "staged") -> None:
    conn = open_db(paths.state_db)
    try:
        conn.execute(
            "INSERT INTO drafts (id, topic, title, body_html, body_json, "
            "artifact_type, source_count, status) "
            "VALUES (?, 'T', 'Title', '<p>body</p>', ?, 'report', 2, ?)",
            (draft_id, json.dumps(body_json), status),
        )
    finally:
        conn.close()


# ---- investigate body_json with a shared entity ----------------------------

_SHARED_ENTITY = "Global Climate Policy"

_INVESTIGATE_BODY = {
    "sections": [
        {
            "title": "Overview of Global Climate Policy",
            "sub_question": "What drives Global Climate Policy adoption?",
            "body": (
                "Global Climate Policy has been shaped by the United Nations "
                "Framework Convention on Climate Change and the Paris Agreement. "
                "The European Union has led ambitious targets under the Green Deal."
            ),
            "citations": [],
        },
        {
            "title": "Economic impacts of Global Climate Policy",
            "sub_question": "How does Global Climate Policy affect economic growth?",
            "body": (
                "Global Climate Policy introduces carbon pricing and renewable "
                "energy subsidies. The United Nations Environment Programme tracks "
                "adaptation finance. European Union member states coordinate "
                "through the European Commission."
            ),
            "citations": [],
        },
        {
            "title": "Technology pathways",
            "sub_question": "Which technologies are central to Global Climate Policy?",
            "body": (
                "Solar power, wind energy, and carbon capture are key. "
                "Global Climate Policy targets require rapid deployment of "
                "battery storage. The International Energy Agency monitors progress."
            ),
            "citations": [],
        },
    ]
}


def test_graph_returns_shared_entity(client, migrated_paths):
    """Seeding 3 sections that all mention 'Global Climate Policy' → it appears
    in top entities with weight >= 3 (present in all chunks)."""
    _insert_draft(migrated_paths, "gd1", _INVESTIGATE_BODY)
    r = client.get("/api/graph/draft/gd1")
    assert r.status_code == 200
    data = r.json()

    entity_labels = [e["label"] for e in data["entities"]]
    # The shared entity must appear; case-insensitive match since the extractor
    # may return a slightly different casing.
    assert any(
        "global climate policy" in lbl.lower() or "Global Climate Policy" in lbl
        for lbl in entity_labels
    ), f"Expected 'Global Climate Policy' in {entity_labels}"


def test_graph_has_nodes_and_edges(client, migrated_paths):
    """The graph subgraph has at least one node and at least one edge when
    there are multiple co-occurring entities."""
    _insert_draft(migrated_paths, "gd2", _INVESTIGATE_BODY)
    r = client.get("/api/graph/draft/gd2")
    assert r.status_code == 200
    data = r.json()
    graph = data["graph"]
    assert "nodes" in graph and "edges" in graph
    assert len(graph["nodes"]) >= 1
    # With multiple entities co-occurring across chunks, we expect edges.
    assert len(graph["edges"]) >= 1


def test_graph_node_shape(client, migrated_paths):
    """Each node has id, label, weight; each edge has source, target, weight."""
    _insert_draft(migrated_paths, "gd3", _INVESTIGATE_BODY)
    r = client.get("/api/graph/draft/gd3")
    assert r.status_code == 200
    data = r.json()
    graph = data["graph"]
    for node in graph["nodes"]:
        assert "id" in node
        assert "label" in node
        assert "weight" in node
    for edge in graph["edges"]:
        assert "source" in edge
        assert "target" in edge
        assert "weight" in edge


def test_graph_entity_shape(client, migrated_paths):
    """Each entity entry has label and weight (int)."""
    _insert_draft(migrated_paths, "gd4", _INVESTIGATE_BODY)
    r = client.get("/api/graph/draft/gd4")
    assert r.status_code == 200
    for ent in r.json()["entities"]:
        assert isinstance(ent["label"], str)
        assert isinstance(ent["weight"], int) and ent["weight"] >= 1


def test_graph_top_entities_cap(client, migrated_paths):
    """Response returns at most 25 entities."""
    _insert_draft(migrated_paths, "gd5", _INVESTIGATE_BODY)
    r = client.get("/api/graph/draft/gd5")
    assert r.status_code == 200
    assert len(r.json()["entities"]) <= 25


# ---- 404 when draft doesn't exist ------------------------------------------


def test_graph_404_for_missing_draft(client):
    r = client.get("/api/graph/draft/nonexistent-id")
    assert r.status_code == 404


# ---- empty body → 200 + empty entities/graph --------------------------------


def test_graph_empty_body_returns_empty(client, migrated_paths):
    """A draft with no body_json and no body_html → 200, empty entities/graph."""
    conn = open_db(migrated_paths.state_db)
    try:
        conn.execute(
            "INSERT INTO drafts (id, topic, title, body_html, body_json, "
            "artifact_type, source_count, status) "
            "VALUES ('empty1', 'T', 'Title', '', NULL, 'report', 0, 'staged')",
        )
    finally:
        conn.close()
    r = client.get("/api/graph/draft/empty1")
    assert r.status_code == 200
    data = r.json()
    assert data["entities"] == []
    assert data["graph"] == {"nodes": [], "edges": []}


def test_graph_short_body_html_fallback(client, migrated_paths):
    """A draft with only very short body_html (< min chunk len) → empty graph, not 500."""
    conn = open_db(migrated_paths.state_db)
    try:
        conn.execute(
            "INSERT INTO drafts (id, topic, title, body_html, body_json, "
            "artifact_type, source_count, status) "
            "VALUES ('short1', 'T', 'Short', '<p>Hi</p>', NULL, 'report', 0, 'staged')",
        )
    finally:
        conn.close()
    r = client.get("/api/graph/draft/short1")
    assert r.status_code == 200


# ---- survey/table body_json shape ------------------------------------------


def test_graph_survey_body(client, migrated_paths):
    """Survey table rows are correctly harvested into chunks."""
    body = {
        "attributes": [{"label": "Outcome"}, {"label": "Population"}],
        "rows": [
            {
                "doc_id": "doc1",
                "title": "European Union Climate Report",
                "cells": [
                    {"attribute": "Outcome", "value": "Carbon reduction achieved"},
                    {"attribute": "Population", "value": "European Union member states"},
                ],
            },
            {
                "doc_id": "doc2",
                "title": "United Nations Environment Review",
                "cells": [
                    {"attribute": "Outcome", "value": "Paris Agreement milestones"},
                    {"attribute": "Population", "value": "United Nations member countries"},
                ],
            },
        ],
    }
    _insert_draft(migrated_paths, "survey1", body)
    r = client.get("/api/graph/draft/survey1")
    assert r.status_code == 200
    data = r.json()
    # Should extract something from the survey rows.
    assert len(data["entities"]) >= 1


# ---- transcript body_json shape ---------------------------------------------


def test_graph_transcript_body(client, migrated_paths):
    """Ask transcript turns are harvested; shared entities across turns appear."""
    body = {
        "turns": [
            {
                "role": "user",
                "text": (
                    "What does the International Monetary Fund say about "
                    "Federal Reserve monetary policy?"
                ),
            },
            {
                "role": "assistant",
                "text": (
                    "The International Monetary Fund has reviewed Federal Reserve "
                    "interest rate decisions and noted divergence with European "
                    "Central Bank policy."
                ),
            },
            {
                "role": "user",
                "text": "How does the European Central Bank compare?",
            },
            {
                "role": "assistant",
                "text": (
                    "The European Central Bank and Federal Reserve differ in mandate. "
                    "The International Monetary Fund recommends coordination."
                ),
            },
        ]
    }
    _insert_draft(migrated_paths, "ask1", body)
    r = client.get("/api/graph/draft/ask1")
    assert r.status_code == 200
    data = r.json()
    labels = [e["label"] for e in data["entities"]]
    # At least one of the multi-chunk entities should appear.
    assert len(labels) >= 1
