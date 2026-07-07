"""Reranker interface + simple lexical-overlap reranker for tests.

Production uses Qwen3-Reranker-0.6B via FlagEmbedding. It returns a single
score per (query, chunk) pair; we re-sort the top-N candidates by score.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from typing import Protocol

from .chunker import Chunk


class Reranker(Protocol):
    def rerank(
        self, query: str, chunks: Iterable[Chunk], *, top_k: int | None = None
    ) -> list[tuple[Chunk, float]]: ...


_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class ScoreReranker:
    """Re-rank by token-overlap-weighted-by-rarity (poor-man's BM25 reranker).

    Good enough to validate the fold-in of reranker scores; production swaps
    this out for the actual Qwen3-Reranker call.

    Stateless: IDF is computed from the candidate pool of each call, so the
    same (query, candidates) always yields the same ranking. (Holding df/n_docs
    as instance state would make rankings drift across calls — a real
    non-determinism bug, since the cross-encoder this stands in for is itself
    stateless.)
    """

    @staticmethod
    def _idf(term: str, df: Counter, n_docs: int) -> float:
        d = df.get(term, 0)
        return math.log(1 + (n_docs - d + 0.5) / (d + 0.5)) if d else 1.0

    def rerank(
        self, query: str, chunks: Iterable[Chunk], *, top_k: int | None = None
    ) -> list[tuple[Chunk, float]]:
        chunks_list = list(chunks)
        if not chunks_list:
            return []
        n_docs = len(chunks_list)
        df: Counter = Counter()
        for c in chunks_list:
            for tok in set(_TOKEN_RE.findall(c.text.lower())):
                df[tok] += 1
        q_tokens = [t.lower() for t in _TOKEN_RE.findall(query)]
        scored: list[tuple[Chunk, float]] = []
        for c in chunks_list:
            doc_tokens = Counter(_TOKEN_RE.findall(c.text.lower()))
            score = 0.0
            for q in q_tokens:
                score += doc_tokens.get(q, 0) * self._idf(q, df, n_docs)
            scored.append((c, score))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_k] if top_k else scored
