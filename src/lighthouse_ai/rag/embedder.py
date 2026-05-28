"""Embedder interface + deterministic fake for tests.

The production backend is BGE-M3 via sentence-transformers; it implements
the same :class:`Embedder` Protocol so the rest of the system doesn't care.
The :class:`HashEmbedder` here is a *deterministic*, dependency-free fake
that gives "similar text → similar vector" enough for unit tests.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from typing import Protocol


class Embedder(Protocol):
    dim: int

    def embed(self, texts: Iterable[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Bag-of-tokens hashed into a fixed-dim L2-normalized vector.

    Produces stable vectors that share dimensions for shared tokens, giving
    cosine similarity that tracks lexical overlap — good enough to validate
    the retrieval framework without pulling in torch.
    """

    def __init__(self, dim: int = 64):
        self.dim = dim

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in t.lower().split():
                h = int(hashlib.blake2b(tok.encode(), digest_size=8).hexdigest(), 16)
                v[h % self.dim] += 1.0
            # L2 normalize.
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("dimension mismatch")
    return sum(x * y for x, y in zip(a, b))
