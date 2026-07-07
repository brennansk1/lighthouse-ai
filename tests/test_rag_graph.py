"""Unit tests for the deterministic local Graph-RAG primitive (rag/graph.py).

Covers entity extraction, graph construction (nodes/weights/edges), neighbor
and related-chunk retrieval, query graph-expansion, BFS paths, JSON-serializable
subgraphs, edge cases (empty/single chunk, absent entity, self-edges), bounds,
and determinism.
"""

from __future__ import annotations

import json

import pytest

from lighthouse_ai.rag import (
    Edge,
    Node,
    build_corpus_graph,
    extract_entities,
)
from lighthouse_ai.rag.chunker import Chunk

# A small corpus where we know the relationships.
#   c1: Alice + Bob + OpenAI
#   c2: Bob + Carol
#   c3: Alice + OpenAI            (Alice<->OpenAI co-occur twice: c1,c3)
#   c4: Dave (isolated component)
CORPUS = [
    {"id": "c1", "text": "Alice met Bob at OpenAI headquarters."},
    {"id": "c2", "text": "Bob later introduced Carol to the project."},
    {"id": "c3", "text": "Alice presented her findings at OpenAI again."},
    {"id": "c4", "text": "Dave worked alone on a separate effort."},
]


def _build():
    return build_corpus_graph(CORPUS)


# --------------------------------------------------------------------------- #
# extract_entities
# --------------------------------------------------------------------------- #


def test_extract_entities_basic_and_dedupe():
    ents = extract_entities("Alice met Bob. Alice waved at Bob again.")
    low = [e.lower() for e in ents]
    assert "alice" in low
    assert "bob" in low
    # Deduped (case-insensitively).
    assert len(low) == len(set(low))


def test_extract_entities_multiword_and_acronym():
    ents = extract_entities("The World Health Organization (WHO) issued a report.")
    low = [e.lower() for e in ents]
    assert "world health organization" in low
    assert "who" in low


def test_extract_entities_empty_and_stopwords():
    assert extract_entities("") == []
    # A sentence-initial stopword like "The" alone is filtered.
    assert extract_entities("the and of") == []


def test_extract_entities_deterministic():
    text = "Quantum Computing relates to Cryptography and Quantum Computing."
    assert extract_entities(text) == extract_entities(text)


# --------------------------------------------------------------------------- #
# entities() / weights
# --------------------------------------------------------------------------- #


def test_entities_and_weights():
    g = _build()
    ents = dict(g.entities())
    # weight = number of chunks an entity appears in.
    assert ents.get("Alice") == 2  # c1, c3
    assert ents.get("OpenAI") == 2  # c1, c3
    assert ents.get("Bob") == 2  # c1, c2
    assert ents.get("Carol") == 1
    assert ents.get("Dave") == 1


def test_entities_sorted_weight_then_name():
    g = _build()
    ents = g.entities()
    weights = [w for _, w in ents]
    assert weights == sorted(weights, reverse=True)
    # Stable tie-break: among equal weights, names ascend by normalized id.
    # Find the weight-1 block and assert its labels are name-sorted.
    ones = [label for label, w in ents if w == 1]
    assert ones == sorted(ones, key=str.lower)


# --------------------------------------------------------------------------- #
# neighbors
# --------------------------------------------------------------------------- #


def test_neighbors_cooccurrence():
    g = _build()
    neigh = dict(g.neighbors("Alice"))
    # Alice co-occurs with OpenAI (c1,c3 → weight 2) and Bob (c1 → weight 1).
    assert neigh.get("OpenAI") == 2
    assert neigh.get("Bob") == 1
    assert "Carol" not in neigh  # never co-occurs with Alice


def test_neighbors_absent_entity_and_k():
    g = _build()
    assert g.neighbors("Nonexistent") == []
    assert g.neighbors("Alice", k=0) == []
    assert g.neighbors("Alice", k=1) == [("OpenAI", 2)]  # heaviest first


def test_neighbors_case_insensitive_lookup():
    g = _build()
    assert g.neighbors("alice") == g.neighbors("Alice")


# --------------------------------------------------------------------------- #
# related_chunk_ids
# --------------------------------------------------------------------------- #


def test_related_chunk_ids_own_chunks_first():
    g = _build()
    ids = g.related_chunk_ids("Alice")
    # Alice's own chunks first.
    assert ids[0] in {"c1", "c3"}
    assert {"c1", "c3"}.issubset(set(ids))


def test_related_chunk_ids_absent_and_k():
    g = _build()
    assert g.related_chunk_ids("Nope") == []
    assert g.related_chunk_ids("Alice", k=0) == []
    assert len(g.related_chunk_ids("Bob", k=2)) <= 2


# --------------------------------------------------------------------------- #
# query — graph expansion
# --------------------------------------------------------------------------- #


def test_query_surfaces_connected_entities_and_chunks():
    g = _build()
    res = g.query("What did Alice do?")
    assert "entities" in res and "chunk_ids" in res
    labels = res["entities"]
    # The query mentions Alice → her connected entities (OpenAI, Bob) surface.
    assert "Alice" in labels
    assert "OpenAI" in labels
    # Covering chunks include Alice's.
    assert set(res["chunk_ids"]) & {"c1", "c3"}


def test_query_no_match_returns_empty():
    g = _build()
    res = g.query("Zebra Penguin Mango")
    assert res == {"entities": [], "chunk_ids": []}


def test_query_k_zero():
    g = _build()
    assert g.query("Alice", k=0) == {"entities": [], "chunk_ids": []}


# --------------------------------------------------------------------------- #
# path — BFS
# --------------------------------------------------------------------------- #


def test_path_connected():
    g = _build()
    # Alice <-> Bob (c1) <-> Carol (c2): path Alice -> Bob -> Carol.
    p = g.path("Alice", "Carol")
    assert p is not None
    assert p[0] == "Alice" and p[-1] == "Carol"
    assert "Bob" in p


def test_path_self():
    g = _build()
    assert g.path("Alice", "Alice") == ["Alice"]


def test_path_disconnected_is_none():
    g = _build()
    # Dave is in his own component.
    assert g.path("Alice", "Dave") is None


def test_path_respects_max_hops():
    g = _build()
    # Alice -> Bob -> Carol is 2 hops; max_hops=1 must fail.
    assert g.path("Alice", "Carol", max_hops=1) is None
    assert g.path("Alice", "Carol", max_hops=2) is not None


def test_path_absent_endpoint():
    g = _build()
    assert g.path("Alice", "Ghost") is None
    assert g.path("Ghost", "Alice") is None


# --------------------------------------------------------------------------- #
# subgraph — JSON-serializable, no self-edges
# --------------------------------------------------------------------------- #


def test_subgraph_json_serializable_no_self_edges():
    g = _build()
    sg = g.subgraph(["Alice"], hops=1)
    # Round-trips through JSON.
    json.dumps(sg)
    assert set(sg.keys()) == {"nodes", "edges"}
    node_ids = {n["id"] for n in sg["nodes"]}
    assert "alice" in node_ids  # normalized id
    for e in sg["edges"]:
        assert e["source"] != e["target"]  # no self-edges
        assert e["source"] in node_ids and e["target"] in node_ids
        assert e["source"] < e["target"]  # canonical ordering


def test_subgraph_node_shape():
    g = _build()
    sg = g.subgraph(["Alice"], hops=2)
    for n in sg["nodes"]:
        assert set(n.keys()) == {"id", "label", "weight"}
        assert isinstance(n["weight"], int)


def test_subgraph_empty_for_absent_seed():
    g = _build()
    assert g.subgraph(["Ghost"]) == {"nodes": [], "edges": []}
    assert g.subgraph([], hops=1) == {"nodes": [], "edges": []}


def test_subgraph_max_nodes_cap():
    g = _build()
    sg = g.subgraph(["Alice", "Bob"], hops=3, max_nodes=2)
    assert len(sg["nodes"]) <= 2


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #


def test_empty_corpus():
    g = build_corpus_graph([])
    assert len(g) == 0
    assert g.entities() == []
    assert g.neighbors("Anything") == []
    assert g.query("anything") == {"entities": [], "chunk_ids": []}
    assert g.path("a", "b") is None
    assert g.subgraph(["x"]) == {"nodes": [], "edges": []}


def test_single_chunk_corpus():
    g = build_corpus_graph([{"id": "only", "text": "Alice met Bob."}])
    ents = dict(g.entities())
    assert ents.get("Alice") == 1
    assert ents.get("Bob") == 1
    # They co-occur in the one chunk.
    assert dict(g.neighbors("Alice")).get("Bob") == 1


def test_chunk_without_id_gets_positional_id():
    g = build_corpus_graph([{"text": "Alice and Bob."}])
    ids = g.related_chunk_ids("Alice")
    assert ids == ["chunk:0"]


def test_accepts_chunk_objects():
    chunks = [
        Chunk(id="x1", document_id="d", text="Alice met Bob.", position=0),
        Chunk(id="x2", document_id="d", text="Bob met Carol.", position=1),
    ]
    g = build_corpus_graph(chunks)
    assert g.related_chunk_ids("Bob")  # non-empty
    assert "x1" in g.related_chunk_ids("Alice")


def test_accepts_object_with_text_attr_no_id():
    class Obj:
        text = "Quantum Computing and Cryptography."

    g = build_corpus_graph([Obj()])
    assert g.has_entity("Quantum Computing")
    assert g.related_chunk_ids("Quantum Computing") == ["chunk:0"]


def test_no_self_edges_in_adjacency():
    g = build_corpus_graph([{"id": "c", "text": "Alice Alice Alice."}])
    # An entity repeated in one chunk must not self-edge.
    assert g.neighbors("Alice") == []
    assert g.edge_count == 0


# --------------------------------------------------------------------------- #
# Bounds
# --------------------------------------------------------------------------- #


def test_max_nodes_cap():
    text = " ".join(f"Entity{i}" for i in range(50))
    g = build_corpus_graph([{"id": "c", "text": text}], max_nodes=5)
    assert g.node_count == 5


def test_max_entities_per_chunk_caps_pairs():
    text = " ".join(f"Thing{i}" for i in range(20))
    g = build_corpus_graph([{"id": "c", "text": text}], max_entities_per_chunk=3)
    # At most 3 entities considered → at most C(3,2)=3 edges.
    assert g.edge_count <= 3
    assert g.node_count <= 3


def test_max_chunk_ids_per_entity_cap():
    corpus = [{"id": f"c{i}", "text": "Alice spoke."} for i in range(10)]
    g = build_corpus_graph(corpus, max_chunk_ids_per_entity=4)
    assert len(g.related_chunk_ids("Alice", k=100)) <= 4


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_build_is_deterministic():
    g1 = build_corpus_graph(CORPUS)
    g2 = build_corpus_graph(CORPUS)
    assert g1.entities() == g2.entities()
    assert g1.neighbors("Alice") == g2.neighbors("Alice")
    assert g1.related_chunk_ids("Bob") == g2.related_chunk_ids("Bob")
    assert g1.query("Alice and Bob") == g2.query("Alice and Bob")
    assert g1.path("Alice", "Carol") == g2.path("Alice", "Carol")
    assert g1.subgraph(["Alice"], hops=2) == g2.subgraph(["Alice"], hops=2)


def test_node_and_edge_dataclasses():
    n = Node(id="alice", label="Alice", weight=2, chunk_ids=("c1", "c3"))
    assert n.weight == 2
    e = Edge(source="alice", target="bob", weight=1)
    assert e.source == "alice"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
