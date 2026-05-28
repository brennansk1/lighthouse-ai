"""Qdrant vector store — production backend for the ``VectorStore`` Protocol.

Per design §14.15:
  * HNSW m=16, ef_construct=100 (defaults).
  * Scalar int8 quantization with ``always_ram=True`` (4× memory reduction,
    99 %+ accuracy).
  * Payload indexes on every filterable field (grade, published_date,
    source, quality_class).
  * ``on_disk=True`` for vectors when collection > 5 M points; not toggled
    here yet — caller can override via ``vector_on_disk``.

The class is constructible without a live Qdrant — ``upsert``/``search``
will only fail when they actually need the server. Callers can test
reachability with ``.available()``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Iterable

from .chunker import Chunk
from .store import SearchResult

log = logging.getLogger(__name__)


DEFAULT_URL = "http://127.0.0.1:6333"
DEFAULT_COLLECTION = "lighthouse_corpus"


class QdrantStore:
    """``VectorStore`` Protocol implementation backed by Qdrant."""

    def __init__(self, *, url: str = DEFAULT_URL,
                 collection: str = DEFAULT_COLLECTION,
                 dim: int,
                 hnsw_m: int = 16,
                 ef_construct: int = 100,
                 scalar_quantization: bool = True,
                 vector_on_disk: bool = False,
                 client: Any | None = None):
        self.url = url
        self.collection = collection
        self.dim = dim
        self.hnsw_m = hnsw_m
        self.ef_construct = ef_construct
        self.scalar_quantization = scalar_quantization
        self.vector_on_disk = vector_on_disk
        self._client = client  # injected client (tests use a fake)
        self._ensured = False

    # --- client lifecycle ---
    def _get_client(self):
        if self._client is not None:
            return self._client
        from qdrant_client import QdrantClient
        # check_compatibility=False avoids a noisy UserWarning when the
        # server is unreachable (the common case in doctor/health probes).
        self._client = QdrantClient(url=self.url, timeout=10.0,
                                    check_compatibility=False)
        return self._client

    def available(self) -> bool:
        try:
            client = self._get_client()
            client.get_collections()
            return True
        except Exception:  # noqa: BLE001 - any connection error → unavailable
            return False

    # --- collection bootstrap ---
    def ensure_collection(self) -> None:
        if self._ensured:
            return
        from qdrant_client.http import models as qm
        client = self._get_client()
        existing = {c.name for c in client.get_collections().collections}
        if self.collection not in existing:
            client.create_collection(
                collection_name=self.collection,
                vectors_config=qm.VectorParams(
                    size=self.dim,
                    distance=qm.Distance.COSINE,
                    on_disk=self.vector_on_disk,
                ),
                hnsw_config=qm.HnswConfigDiff(
                    m=self.hnsw_m,
                    ef_construct=self.ef_construct,
                ),
                quantization_config=(
                    qm.ScalarQuantization(
                        scalar=qm.ScalarQuantizationConfig(
                            type=qm.ScalarType.INT8,
                            quantile=0.99,
                            always_ram=True,
                        ),
                    ) if self.scalar_quantization else None
                ),
            )
            # Payload indexes that match the filter fields we use in retrieval.
            for field in ("source", "grade", "published_date", "quality_class"):
                try:
                    client.create_payload_index(
                        collection_name=self.collection,
                        field_name=field,
                        field_schema=qm.PayloadSchemaType.KEYWORD,
                    )
                except Exception:  # noqa: BLE001 - index may already exist; ignore
                    log.debug("payload index %s already exists", field)
        self._ensured = True

    # --- write ---
    def upsert(self, chunks: Iterable[Chunk], vectors: Iterable[list[float]]) -> None:
        from qdrant_client.http import models as qm
        self.ensure_collection()
        client = self._get_client()
        points: list[qm.PointStruct] = []
        for chunk, vec in zip(chunks, vectors):
            # Qdrant point IDs must be UUIDs or ints; derive UUID5 from chunk id.
            pid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"lighthouse:chunk:{chunk.id}"))
            payload = {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "text": chunk.text,
                "position": chunk.position,
                **chunk.metadata,
            }
            points.append(qm.PointStruct(id=pid, vector=list(vec), payload=payload))
        if points:
            client.upsert(collection_name=self.collection, points=points)

    # --- read ---
    def search(self, query_vector: list[float], *, k: int = 10,
               filter: dict[str, Any] | None = None) -> list[SearchResult]:
        from qdrant_client.http import models as qm
        self.ensure_collection()
        client = self._get_client()
        qfilter = None
        if filter:
            must = [
                qm.FieldCondition(key=k_, match=qm.MatchValue(value=v))
                for k_, v in filter.items()
            ]
            qfilter = qm.Filter(must=must)
        # Use `query_points` (current API) and fall back to `search` for older clients.
        try:
            hits = client.query_points(
                collection_name=self.collection,
                query=query_vector,
                limit=k,
                query_filter=qfilter,
                with_payload=True,
            ).points
        except AttributeError:  # pragma: no cover - older qdrant-client
            hits = client.search(
                collection_name=self.collection,
                query_vector=query_vector,
                limit=k,
                query_filter=qfilter,
                with_payload=True,
            )
        out: list[SearchResult] = []
        for h in hits:
            payload = h.payload or {}
            chunk = Chunk(
                id=str(payload.get("chunk_id", h.id)),
                document_id=str(payload.get("document_id", "")),
                text=str(payload.get("text", "")),
                position=int(payload.get("position", 0)),
                metadata={k_: v for k_, v in payload.items()
                          if k_ not in ("chunk_id", "document_id", "text", "position")},
            )
            out.append(SearchResult(chunk_id=chunk.id, score=float(h.score), chunk=chunk))
        return out

    # --- delete / count ---
    def delete(self, chunk_ids: Iterable[str]) -> int:
        from qdrant_client.http import models as qm
        client = self._get_client()
        ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"lighthouse:chunk:{cid}"))
               for cid in chunk_ids]
        if not ids:
            return 0
        client.delete(
            collection_name=self.collection,
            points_selector=qm.PointIdsList(points=ids),
        )
        return len(ids)

    def count(self) -> int:
        client = self._get_client()
        try:
            return int(client.count(collection_name=self.collection, exact=True).count)
        except Exception:  # noqa: BLE001 - collection may not exist yet
            return 0
