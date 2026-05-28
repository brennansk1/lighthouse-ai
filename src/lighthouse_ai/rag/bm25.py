"""Pure-Python BM25 index over an in-memory chunk corpus.

Production uses Qdrant's native BM25 sparse encoder. The math here is
identical (Okapi BM25, k1=1.2, b=0.75 defaults) so swap-in is mechanical.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .chunker import Chunk

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


@dataclass
class _Doc:
    chunk: Chunk
    tokens: list[str]
    length: int
    tf: Counter


class BM25Index:
    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: dict[str, _Doc] = {}
        self._df: Counter = Counter()
        self._avgdl: float = 0.0

    def add(self, chunks: Iterable[Chunk]) -> None:
        for c in chunks:
            tokens = _tokenize(c.text)
            tf = Counter(tokens)
            self._docs[c.id] = _Doc(chunk=c, tokens=tokens, length=len(tokens), tf=tf)
            for term in tf.keys():
                self._df[term] += 1
        self._recompute_avgdl()

    def _recompute_avgdl(self) -> None:
        if not self._docs:
            self._avgdl = 0.0
            return
        total = sum(d.length for d in self._docs.values())
        self._avgdl = total / len(self._docs)

    def __len__(self) -> int:
        return len(self._docs)

    def search(self, query: str, *, k: int = 10) -> list[tuple[str, float]]:
        if not self._docs:
            return []
        q_tokens = _tokenize(query)
        n_docs = len(self._docs)
        scores: dict[str, float] = {}
        for term in q_tokens:
            df = self._df.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            for doc_id, doc in self._docs.items():
                tf = doc.tf.get(term, 0)
                if tf == 0:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * doc.length / (self._avgdl or 1))
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * (tf * (self.k1 + 1)) / denom
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return ranked[:k]
