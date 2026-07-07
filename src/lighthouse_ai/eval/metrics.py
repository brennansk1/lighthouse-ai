"""Pure ranking + faithfulness metrics.

Why these live as free functions on plain ``Sequence``/``set`` inputs: a
metric is only trustworthy if it is trivially unit-testable against numbers
you can compute by hand. Keeping them free of any retrieval objects (no
Chunk, no HybridResult) means the same functions evaluate any ranked list of
ids — embedder, store, and reranker are irrelevant to the math. The caller is
responsible for projecting retrieval output down to ids before measuring.

All functions are deterministic and import nothing beyond stdlib + typing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

__all__ = [
    "faithfulness",
    "mean_metric",
    "mrr",
    "precision_at_k",
    "recall_at_k",
]


def _dedup_preserve_order(ids: Sequence[str]) -> list[str]:
    """Drop duplicate ids while preserving first-seen order.

    Retrieval can surface multiple chunks from the same document; for
    document-level relevance we count each document once, in the rank at which
    it first appears. Keeping order matters because MRR and precision@k are
    rank-sensitive.
    """
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def precision_at_k(retrieved_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    """Fraction of the top-``k`` retrieved ids that are relevant.

    Denominator is ``k`` (not the number actually returned) so that returning
    fewer than ``k`` results is penalised — a system that hedges by returning
    one safe hit should not score a perfect 1.0. With ``k <= 0`` the metric is
    undefined, so we return 0.0 rather than raising; an eval loop should never
    crash on a degenerate config.
    """
    if k <= 0:
        return 0.0
    relevant = set(relevant_ids)
    top = _dedup_preserve_order(retrieved_ids)[:k]
    hits = sum(1 for cid in top if cid in relevant)
    return hits / k


def recall_at_k(retrieved_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    """Fraction of all relevant ids that appear in the top-``k`` retrieved.

    Denominator is the size of the relevant set. If nothing is relevant the
    metric is vacuously perfect (1.0): there was nothing to miss, and treating
    it as a failure would drag down aggregates for queries with no gold answer.
    """
    relevant = set(relevant_ids)
    if not relevant:
        return 1.0
    if k <= 0:
        return 0.0
    top = set(_dedup_preserve_order(retrieved_ids)[:k])
    hits = len(top & relevant)
    return hits / len(relevant)


def mrr(retrieved_ids: Sequence[str], relevant_ids: Iterable[str]) -> float:
    """Reciprocal rank of the first relevant id (1-indexed); 0.0 if none.

    MRR rewards putting *a* correct answer high in the list, which is the
    property that matters most for a RAG context window: the first good chunk
    typically dominates the generation. We scan the de-duplicated ranking so a
    document's rank is where it first appears, not where a later chunk lands.
    """
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    for rank, cid in enumerate(_dedup_preserve_order(retrieved_ids), start=1):
        if cid in relevant:
            return 1.0 / rank
    return 0.0


def mean_metric(values: Iterable[float]) -> float:
    """Arithmetic mean of per-query metric values; 0.0 over an empty set.

    Aggregating across the golden set is just an unweighted mean — every query
    counts the same. Returning 0.0 for an empty input keeps callers branch-free
    when a golden set has no cases.
    """
    vals = list(values)
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


_CLAIM_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# Function words carry no factual claim; counting them would inflate
# faithfulness toward 1.0 for any fluent-but-unsupported answer.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "from",
        "into",
        "about",
        "than",
        "so",
        "such",
        "can",
        "will",
        "would",
        "should",
        "could",
        "may",
        "might",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "not",
        "no",
        "yes",
        "we",
        "you",
        "they",
        "he",
        "she",
        "i",
        "their",
        "our",
        "your",
    }
)


def _claim_tokens(text: str) -> list[str]:
    """Lowercase content tokens, stopwords removed.

    "Claim tokens" approximate the load-bearing words in a sentence — the
    nouns/verbs/numbers that assert something. Stripping stopwords focuses the
    overlap measure on substance rather than grammar.
    """
    return [t for t in (m.lower() for m in _CLAIM_TOKEN_RE.findall(text)) if t not in _STOPWORDS]


def faithfulness(answer: str, evidence_texts: Iterable[str]) -> float:
    """Deterministic overlap proxy for how grounded ``answer`` is in evidence.

    Real faithfulness needs an LLM (or NLI model) to judge entailment; that is
    expensive and non-deterministic, which makes it useless as a unit-test
    oracle. This proxy instead asks a cheap, reproducible question: what
    fraction of the answer's distinct content tokens also appear somewhere in
    the supplied evidence? It returns a value in [0, 1].

    Properties relied on by tests and callers:
      * 1.0 when every answer claim-token is supported (answer drawn from
        evidence), including the case of an empty answer (nothing to support).
      * 0.0 when there is no evidence but the answer makes claims — an
        ungrounded answer cannot be faithful.
      * Measured over the *set* of answer tokens so repeating one supported
        word does not pad the score.

    This is a proxy, not a guarantee: lexical overlap can be fooled by
    paraphrase (false negative) or coincidental word reuse (false positive).
    It is deliberately conservative and only meant to flag gross hallucination
    drift in a regression harness.
    """
    answer_tokens = set(_claim_tokens(answer))
    if not answer_tokens:
        # No claims were made, so the answer is vacuously faithful.
        return 1.0
    evidence_tokens: set[str] = set()
    for text in evidence_texts:
        evidence_tokens.update(_claim_tokens(text))
    if not evidence_tokens:
        return 0.0
    supported = sum(1 for tok in answer_tokens if tok in evidence_tokens)
    return supported / len(answer_tokens)
