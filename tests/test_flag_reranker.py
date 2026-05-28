"""Tests for the FlagEmbedding reranker adapter.

These tests NEVER import or download the real model: every case either injects
a fake scorer or relies on the dependency being absent. The point of the
adapter is graceful degradation around an optional heavy dependency, so the
suite must validate that contract without paying for it.
"""

from __future__ import annotations

import sys

import pytest

from lighthouse_ai.rag.chunker import Chunk
from lighthouse_ai.rag.flag_reranker import (
    FlagReranker,
    RerankerUnavailable,
    make_reranker,
)
from lighthouse_ai.rag.rerank import ScoreReranker


def _chunk(cid: str, text: str, position: int = 0) -> Chunk:
    return Chunk(id=cid, document_id="doc", text=text, position=position)


# A fake scorer that scores a passage by its length. Deterministic and free.
def _length_scorer(query, texts):
    return [float(len(t)) for t in texts]


# A scorer that returns scores from a lookup keyed on passage text.
def _make_lookup_scorer(mapping):
    def _scorer(query, texts):
        return [mapping[t] for t in texts]

    return _scorer


def test_rerank_orders_by_score_descending():
    rr = FlagReranker(scorer=_make_lookup_scorer({"a": 0.1, "b": 0.9, "c": 0.5}))
    chunks = [_chunk("1", "a"), _chunk("2", "b"), _chunk("3", "c")]
    out = rr.rerank("q", chunks)
    assert [c.text for c, _ in out] == ["b", "c", "a"]


def test_rerank_returns_chunk_score_tuples():
    rr = FlagReranker(scorer=_make_lookup_scorer({"x": 2.0}))
    out = rr.rerank("q", [_chunk("1", "x")])
    assert len(out) == 1
    chunk, score = out[0]
    assert isinstance(chunk, Chunk)
    assert score == 2.0


def test_rerank_scores_are_floats():
    rr = FlagReranker(scorer=_make_lookup_scorer({"x": 1, "y": 2}))
    out = rr.rerank("q", [_chunk("1", "x"), _chunk("2", "y")])
    assert all(isinstance(s, float) for _, s in out)


def test_top_k_slices_results():
    rr = FlagReranker(scorer=_length_scorer)
    chunks = [_chunk(str(i), "x" * i, i) for i in range(1, 6)]
    out = rr.rerank("q", chunks, top_k=2)
    assert len(out) == 2
    # Longest two texts win.
    assert [c.text for c, _ in out] == ["xxxxx", "xxxx"]


def test_top_k_none_returns_all():
    rr = FlagReranker(scorer=_length_scorer)
    chunks = [_chunk(str(i), "x" * i, i) for i in range(1, 4)]
    out = rr.rerank("q", chunks, top_k=None)
    assert len(out) == 3


def test_top_k_larger_than_input_returns_all():
    rr = FlagReranker(scorer=_length_scorer)
    chunks = [_chunk("1", "aa"), _chunk("2", "bbb")]
    out = rr.rerank("q", chunks, top_k=10)
    assert len(out) == 2


def test_rerank_empty_input_returns_empty():
    rr = FlagReranker(scorer=_length_scorer)
    assert rr.rerank("q", []) == []


def test_rerank_empty_input_does_not_call_scorer():
    def _boom(query, texts):  # pragma: no cover - must not be called
        raise AssertionError("scorer should not be called for empty input")

    rr = FlagReranker(scorer=_boom)
    assert rr.rerank("q", []) == []


def test_rerank_preserves_all_chunks():
    rr = FlagReranker(scorer=_length_scorer)
    chunks = [_chunk(str(i), "z" * (i + 1), i) for i in range(4)]
    out = rr.rerank("q", chunks)
    assert {c.id for c, _ in out} == {c.id for c in chunks}


def test_scorer_receives_query_and_texts():
    seen = {}

    def _scorer(query, texts):
        seen["query"] = query
        seen["texts"] = list(texts)
        return [0.0 for _ in texts]

    rr = FlagReranker(scorer=_scorer)
    rr.rerank("my-query", [_chunk("1", "alpha"), _chunk("2", "beta")])
    assert seen["query"] == "my-query"
    assert seen["texts"] == ["alpha", "beta"]


def test_available_true_with_injected_scorer():
    rr = FlagReranker(scorer=_length_scorer)
    assert rr.available() is True


def test_available_reflects_dependency_when_no_scorer():
    rr = FlagReranker()
    expected = FlagReranker._flag_embedding_importable()
    assert rr.available() is expected


def test_available_false_when_dep_missing_and_no_scorer(monkeypatch):
    monkeypatch.setattr(FlagReranker, "_flag_embedding_importable",
                        staticmethod(lambda: False))
    rr = FlagReranker()
    assert rr.available() is False


def test_rerank_raises_when_unavailable(monkeypatch):
    # No scorer + dependency reported missing -> typed error on use.
    monkeypatch.setattr(FlagReranker, "_flag_embedding_importable",
                        staticmethod(lambda: False))
    monkeypatch.setitem(sys.modules, "FlagEmbedding", None)
    rr = FlagReranker()
    with pytest.raises(RerankerUnavailable):
        rr.rerank("q", [_chunk("1", "text")])


def test_rerank_raises_on_scorer_length_mismatch():
    def _short(query, texts):
        return [1.0]  # wrong length

    rr = FlagReranker(scorer=_short)
    with pytest.raises(ValueError):
        rr.rerank("q", [_chunk("1", "a"), _chunk("2", "b")])


def test_default_model_name():
    assert FlagReranker().model == "BAAI/bge-reranker-v2-m3"


def test_custom_model_name():
    assert FlagReranker(model="custom/model").model == "custom/model"


def test_make_reranker_uses_injected_scorer():
    rr = make_reranker(scorer=_length_scorer)
    assert isinstance(rr, FlagReranker)
    assert rr.available() is True


def test_make_reranker_falls_back_to_score_reranker(monkeypatch):
    monkeypatch.setattr(FlagReranker, "_flag_embedding_importable",
                        staticmethod(lambda: False))
    rr = make_reranker(prefer_real=True)
    assert isinstance(rr, ScoreReranker)


def test_make_reranker_prefer_real_false_returns_score_reranker():
    rr = make_reranker(prefer_real=False)
    assert isinstance(rr, ScoreReranker)


def test_make_reranker_returns_flag_when_dep_available(monkeypatch):
    monkeypatch.setattr(FlagReranker, "_flag_embedding_importable",
                        staticmethod(lambda: True))
    rr = make_reranker(prefer_real=True)
    assert isinstance(rr, FlagReranker)


def test_make_reranker_result_implements_protocol():
    rr = make_reranker(scorer=_length_scorer)
    out = rr.rerank("q", [_chunk("1", "aa"), _chunk("2", "bbb")])
    assert [c.text for c, _ in out] == ["bbb", "aa"]


def test_score_reranker_fallback_actually_works(monkeypatch):
    monkeypatch.setattr(FlagReranker, "_flag_embedding_importable",
                        staticmethod(lambda: False))
    rr = make_reranker(prefer_real=True)
    out = rr.rerank("hello", [_chunk("1", "hello world"), _chunk("2", "nope")])
    assert len(out) == 2
