"""Tests for OllamaEmbedder and QdrantStore.

All tests run via injected fakes — no real daemons or HTTP. The opt-in
``LIGHTHOUSE_REAL_BACKEND=1`` env var (plus reachable services) enables
the integration suite, which is left empty for this sprint to avoid
loading large models on the user's machine during the harness run.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pytest

from lighthouse_ai.backends.ollama import EmbeddingResponse, OllamaUnavailable
from lighthouse_ai.rag.chunker import Chunk
from lighthouse_ai.rag.ollama_embedder import OllamaEmbedder
from lighthouse_ai.rag.qdrant_store import QdrantStore

# ============================== OllamaEmbedder ==============================

@dataclass
class _FakeOllama:
    """Stub matching the OllamaBackend.embed/available surface."""
    vectors: list[list[float]] | None = None
    available_flag: bool = True
    raise_on_embed: bool = False

    def available(self) -> bool:
        return self.available_flag

    def embed(self, model: str, texts: Iterable[str]) -> EmbeddingResponse:
        if self.raise_on_embed:
            raise OllamaUnavailable("simulated")
        texts_list = list(texts)
        out = self.vectors or [[0.1] * 768 for _ in texts_list]
        return EmbeddingResponse(vectors=out, model=model)


def test_embedder_round_trip():
    e = OllamaEmbedder(backend=_FakeOllama(), dim=768)
    out = e.embed(["a", "b"])
    assert len(out) == 2
    assert len(out[0]) == 768


def test_embedder_empty_input_no_call():
    fake = _FakeOllama(vectors=[[0.0]])  # would fail dim check
    e = OllamaEmbedder(backend=fake, dim=768)
    assert e.embed([]) == []


def test_embedder_dim_mismatch_raises():
    e = OllamaEmbedder(backend=_FakeOllama(vectors=[[0.0] * 512]), dim=768)
    with pytest.raises(OllamaUnavailable):
        e.embed(["x"])


def test_embedder_propagates_backend_errors():
    e = OllamaEmbedder(backend=_FakeOllama(raise_on_embed=True), dim=768)
    with pytest.raises(OllamaUnavailable):
        e.embed(["x"])


def test_embedder_available_proxies_backend():
    assert OllamaEmbedder(backend=_FakeOllama(available_flag=True)).available()
    assert not OllamaEmbedder(backend=_FakeOllama(available_flag=False)).available()


# ============================== QdrantStore =================================

@dataclass
class _Collection:
    name: str


@dataclass
class _CollectionsResponse:
    collections: list[_Collection]


@dataclass
class _Hit:
    id: str
    score: float
    payload: dict | None


@dataclass
class _PointsResponse:
    points: list[_Hit]


@dataclass
class _CountResponse:
    count: int


class _FakeQdrantClient:
    """Just enough surface to exercise QdrantStore without a real server."""

    def __init__(self) -> None:
        self.collections: dict[str, dict[str, Any]] = {}
        self.points: dict[str, dict[str, Any]] = {}
        self.payload_indexes: dict[str, set[str]] = {}
        self.create_calls: list[dict[str, Any]] = []
        self.upsert_calls: int = 0
        self.delete_calls: list[list[str]] = []

    def get_collections(self):
        return _CollectionsResponse([_Collection(n) for n in self.collections])

    def create_collection(self, *, collection_name, vectors_config,
                          hnsw_config=None, quantization_config=None):
        self.create_calls.append({
            "name": collection_name,
            "size": vectors_config.size,
            "distance": str(vectors_config.distance),
            "hnsw_m": getattr(hnsw_config, "m", None),
            "ef_construct": getattr(hnsw_config, "ef_construct", None),
            "quantization": type(quantization_config).__name__
                            if quantization_config else None,
        })
        self.collections[collection_name] = {"size": vectors_config.size}
        self.payload_indexes[collection_name] = set()

    def create_payload_index(self, *, collection_name, field_name, field_schema):
        self.payload_indexes.setdefault(collection_name, set()).add(field_name)

    def upsert(self, *, collection_name, points):
        self.upsert_calls += 1
        for p in points:
            self.points[p.id] = {"vector": p.vector, "payload": p.payload}

    def query_points(self, *, collection_name, query, limit,
                     query_filter=None, with_payload=True):
        hits: list[_Hit] = []
        for pid, body in self.points.items():
            if query_filter is not None:
                # naive must-match-all check on payload
                conds = getattr(query_filter, "must", [])
                ok = True
                for c in conds:
                    if body["payload"].get(c.key) != c.match.value:
                        ok = False
                        break
                if not ok:
                    continue
            hits.append(_Hit(id=pid, score=0.99, payload=body["payload"]))
        return _PointsResponse(points=hits[:limit])

    def delete(self, *, collection_name, points_selector):
        ids = points_selector.points
        self.delete_calls.append(list(ids))
        for i in ids:
            self.points.pop(i, None)

    def count(self, *, collection_name, exact=True):
        return _CountResponse(len(self.points))


@pytest.fixture
def fake_qdrant() -> _FakeQdrantClient:
    return _FakeQdrantClient()


def test_qdrant_ensure_collection_creates_with_hnsw_and_quantization(fake_qdrant):
    store = QdrantStore(dim=128, client=fake_qdrant)
    store.ensure_collection()
    assert fake_qdrant.create_calls[0]["size"] == 128
    assert fake_qdrant.create_calls[0]["hnsw_m"] == 16
    assert fake_qdrant.create_calls[0]["ef_construct"] == 100
    assert fake_qdrant.create_calls[0]["quantization"] == "ScalarQuantization"


def test_qdrant_ensure_creates_payload_indexes(fake_qdrant):
    store = QdrantStore(dim=64, client=fake_qdrant)
    store.ensure_collection()
    idxs = fake_qdrant.payload_indexes[store.collection]
    assert {"source", "grade", "published_date", "quality_class"} <= idxs


def test_qdrant_ensure_is_idempotent(fake_qdrant):
    store = QdrantStore(dim=64, client=fake_qdrant)
    store.ensure_collection()
    store.ensure_collection()
    assert len(fake_qdrant.create_calls) == 1


def test_qdrant_upsert_and_search_round_trip(fake_qdrant):
    store = QdrantStore(dim=4, client=fake_qdrant)
    chunks = [
        Chunk(id="c1", document_id="d1", text="alpha", position=0,
              metadata={"source": "S", "grade": "A"}),
        Chunk(id="c2", document_id="d1", text="beta", position=1,
              metadata={"source": "S", "grade": "B"}),
    ]
    vectors = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]
    store.upsert(chunks, vectors)
    assert store.count() == 2
    hits = store.search([1.0, 0.0, 0.0, 0.0], k=5)
    assert len(hits) == 2
    assert {h.chunk.id for h in hits} == {"c1", "c2"}


def test_qdrant_search_filter_narrows_results(fake_qdrant):
    store = QdrantStore(dim=2, client=fake_qdrant)
    chunks = [
        Chunk(id="a", document_id="d", text="x", position=0, metadata={"grade": "A"}),
        Chunk(id="b", document_id="d", text="y", position=1, metadata={"grade": "B"}),
    ]
    store.upsert(chunks, [[1, 0], [0, 1]])
    hits = store.search([1, 0], k=5, filter={"grade": "A"})
    assert [h.chunk.id for h in hits] == ["a"]


def test_qdrant_delete_uses_deterministic_uuid(fake_qdrant):
    store = QdrantStore(dim=2, client=fake_qdrant)
    chunks = [Chunk(id="c1", document_id="d", text="x", position=0, metadata={})]
    store.upsert(chunks, [[1, 0]])
    n = store.delete(["c1"])
    assert n == 1
    expected_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, "lighthouse:chunk:c1"))
    assert fake_qdrant.delete_calls[0] == [expected_uuid]
    assert store.count() == 0


def test_qdrant_count_returns_zero_when_empty(fake_qdrant):
    store = QdrantStore(dim=2, client=fake_qdrant)
    store.ensure_collection()
    assert store.count() == 0


def test_qdrant_available_false_when_client_raises():
    class Broken:
        def get_collections(self):
            raise RuntimeError("down")
    store = QdrantStore(dim=2, client=Broken())
    assert store.available() is False


def test_qdrant_available_true_when_client_responds(fake_qdrant):
    store = QdrantStore(dim=2, client=fake_qdrant)
    assert store.available() is True
