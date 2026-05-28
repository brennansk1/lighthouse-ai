"""Vector store interface + in-memory implementation.

Production: Qdrant via ``qdrant-client`` with HNSW m=16, ef_construct=100,
scalar quantization int8, payload indexes per §14.15.

Test/embedded: :class:`InMemoryStore` keeps everything in a Python dict and
brute-force scans on query. The same :class:`VectorStore` Protocol covers
both.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from .chunker import Chunk
from .embedder import cosine


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    score: float
    chunk: Chunk


class VectorStore(Protocol):
    def upsert(self, chunks: Iterable[Chunk], vectors: Iterable[list[float]]) -> None: ...

    def search(self, query_vector: list[float], *, k: int = 10,
               filter: dict[str, Any] | None = None) -> list[SearchResult]: ...

    def delete(self, chunk_ids: Iterable[str]) -> int: ...

    def count(self) -> int: ...


@dataclass
class _Entry:
    chunk: Chunk
    vector: list[float]


class InMemoryStore:
    """Brute-force vector store. Fine for tests + tiers ≤10k chunks."""

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def upsert(self, chunks: Iterable[Chunk], vectors: Iterable[list[float]]) -> None:
        for chunk, vec in zip(chunks, vectors):
            self._entries[chunk.id] = _Entry(chunk=chunk, vector=list(vec))

    def _match(self, entry: _Entry, filter: dict[str, Any] | None) -> bool:
        if not filter:
            return True
        for k, v in filter.items():
            if entry.chunk.metadata.get(k) != v:
                return False
        return True

    def search(self, query_vector: list[float], *, k: int = 10,
               filter: dict[str, Any] | None = None) -> list[SearchResult]:
        scored: list[tuple[float, _Entry]] = []
        for entry in self._entries.values():
            if not self._match(entry, filter):
                continue
            try:
                s = cosine(query_vector, entry.vector)
            except ValueError:
                continue
            scored.append((s, entry))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [SearchResult(chunk_id=e.chunk.id, score=s, chunk=e.chunk)
                for s, e in scored[:k]]

    def delete(self, chunk_ids: Iterable[str]) -> int:
        n = 0
        for cid in chunk_ids:
            if self._entries.pop(cid, None) is not None:
                n += 1
        return n

    def count(self) -> int:
        return len(self._entries)
