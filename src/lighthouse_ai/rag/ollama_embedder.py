"""Real embedder backed by Ollama's /api/embed endpoint.

Implements the :class:`lighthouse_ai.rag.embedder.Embedder` Protocol so the
rest of the system doesn't care which backend is plugged in. Default model
is ``nomic-embed-text`` (274 MB, 768-dim) which runs comfortably on CPU.

Use ``bge-m3`` (~1.2 GB, 1024-dim) when the user wants multilingual + sparse
+ multi-vector features called out in design §14.1.

Falls back to raising ``OllamaUnavailable`` if the daemon isn't reachable;
callers can detect and downgrade to :class:`HashEmbedder` for offline use.
"""

from __future__ import annotations

from typing import Iterable

from ..backends.ollama import OllamaBackend, OllamaUnavailable


class OllamaEmbedder:
    """``Embedder`` Protocol implementation backed by Ollama."""

    def __init__(self, backend: OllamaBackend | None = None,
                 model: str = "nomic-embed-text", dim: int = 768):
        self._backend = backend or OllamaBackend()
        self.model = model
        self.dim = dim

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        texts_list = list(texts)
        if not texts_list:
            return []
        resp = self._backend.embed(self.model, texts_list)
        vectors = resp.vectors
        if not vectors:
            return []
        # Validate dim on the first vector — guards against pulling a
        # different model than the user configured.
        if len(vectors[0]) != self.dim:
            raise OllamaUnavailable(
                f"embedder dim mismatch: configured {self.dim}, "
                f"backend returned {len(vectors[0])} (wrong model pulled?)"
            )
        return vectors

    def available(self) -> bool:
        return self._backend.available()
