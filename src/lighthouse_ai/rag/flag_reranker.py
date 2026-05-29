"""FlagEmbedding-backed reranker adapter (Qwen3-Reranker / bge-reranker-v2-m3).

WHY a dedicated adapter with lazy import:
    The production reranker runs a cross-encoder model through ``FlagEmbedding``,
    which transitively pulls in ``torch`` and multi-hundred-MB weights. That is
    far too heavy to import at module load: it would slow every CLI invocation,
    break environments where the dependency is intentionally absent, and make
    the test suite download a model. So we keep this module import-light and only
    touch ``FlagEmbedding`` on first actual use. If it is missing we raise a
    typed :class:`RerankerUnavailable` instead of an opaque ``ImportError``,
    letting callers degrade gracefully (see :func:`make_reranker`).

The ``scorer`` injection point exists so tests — and any caller that already
holds a scoring function — can exercise the full rerank/sort/slice logic without
ever constructing or downloading the real model.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

from .chunker import Chunk
from .rerank import ScoreReranker

# A scorer maps (query, list-of-passage-texts) -> list-of-floats (one per text).
Scorer = Callable[[str, Sequence[str]], Sequence[float]]


class RerankerUnavailable(RuntimeError):
    """Raised when a real reranking backend cannot be loaded.

    Kept as a dedicated type (rather than bubbling ``ImportError``) so callers
    can catch *exactly* the "heavy dependency missing" case and fall back,
    without accidentally swallowing unrelated import errors.
    """


class FlagReranker:
    """Cross-encoder reranker backed by ``FlagEmbedding``.

    Implements the ``Reranker`` Protocol from :mod:`lighthouse_ai.rag.rerank`.

    Parameters
    ----------
    model:
        HuggingFace model id passed to ``FlagEmbedding.FlagReranker``. Defaults
        to ``"BAAI/bge-reranker-v2-m3"``.
    scorer:
        Optional injected scoring callable ``scorer(query, [texts]) -> [float]``.
        When supplied, the real model is never loaded — this is the seam used by
        tests and lightweight deployments.
    """

    def __init__(
        self,
        model: str = "BAAI/bge-reranker-v2-m3",
        scorer: Scorer | None = None,
    ) -> None:
        self.model = model
        self._injected_scorer = scorer
        # Lazily-constructed real model handle; ``None`` until first real use.
        self._model: Any | None = None

    @staticmethod
    def _flag_embedding_importable() -> bool:
        """Return True iff ``FlagEmbedding`` can be imported.

        Uses ``importlib.util.find_spec`` so we probe availability *without*
        actually importing the package (and thus without paying torch's import
        cost or triggering any side effects).
        """
        import importlib.util

        return importlib.util.find_spec("FlagEmbedding") is not None

    def available(self) -> bool:
        """True iff this reranker can score: dep importable OR scorer injected.

        An injected scorer always makes us usable regardless of whether the
        heavy dependency is installed.
        """
        if self._injected_scorer is not None:
            return True
        return self._flag_embedding_importable()

    def _get_scorer(self) -> Scorer:
        """Resolve the active scorer, loading the real model lazily if needed.

        Raises
        ------
        RerankerUnavailable
            If no scorer was injected and ``FlagEmbedding`` is not importable.
        """
        if self._injected_scorer is not None:
            return self._injected_scorer

        if self._model is None:
            try:
                # Imported here (not at module top) precisely so that merely
                # importing this module never pulls in torch / model weights.
                from FlagEmbedding import FlagReranker as _FE
            except ImportError as exc:  # pragma: no cover - env-dependent
                raise RerankerUnavailable(
                    "FlagEmbedding is not installed; install the optional "
                    "reranker extra or inject a `scorer` callable."
                ) from exc
            self._model = _FE(self.model, use_fp16=True)

        # Capture the model in a local (not through self) so mypy can see it is
        # non-None inside the closure; self._model is Any here after assignment.
        _m: Any = self._model

        def _model_scorer(query: str, texts: Sequence[str]) -> Sequence[float]:
            # FlagEmbedding expects a list of [query, passage] pairs and returns
            # one score per pair.
            pairs = [[query, t] for t in texts]
            scores = _m.compute_score(pairs)
            # compute_score returns a float for a single pair; normalise to list.
            if isinstance(scores, (int, float)):
                return [float(scores)]
            return [float(s) for s in scores]

        return _model_scorer

    def rerank(
        self,
        query: str,
        chunks: Iterable[Chunk],
        *,
        top_k: int | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Score each chunk against ``query`` and return them sorted desc.

        Returns a list of ``(chunk, score)`` tuples sorted by score descending,
        sliced to ``top_k`` when provided. Empty input yields an empty list and
        never touches the scorer (so it works even when unavailable).
        """
        chunks_list = list(chunks)
        if not chunks_list:
            return []
        scorer = self._get_scorer()
        scores = list(scorer(query, [c.text for c in chunks_list]))
        if len(scores) != len(chunks_list):
            raise ValueError(
                f"scorer returned {len(scores)} scores for "
                f"{len(chunks_list)} chunks"
            )
        scored = [(c, float(s)) for c, s in zip(chunks_list, scores)]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_k] if top_k else scored


def make_reranker(
    prefer_real: bool = True,
    scorer: Scorer | None = None,
) -> object:
    """Return the best usable reranker, degrading gracefully.

    Returns a :class:`FlagReranker` when it can actually score (a scorer was
    injected, or ``prefer_real`` is set and ``FlagEmbedding`` is importable);
    otherwise falls back to :class:`ScoreReranker` so callers always get a
    working ``Reranker`` rather than an exception.
    """
    if scorer is not None:
        return FlagReranker(scorer=scorer)
    if prefer_real:
        candidate = FlagReranker()
        if candidate.available():
            return candidate
    return ScoreReranker()
