"""Tests for the retrieval eval harness.

Two layers:
  1. Metric math against hand-computed cases — the numbers below are worked
     out by hand so a regression in the metric definitions fails loudly.
  2. The full ``evaluate()`` over the built-in golden set — asserts the
     harness *runs* and reports sane numbers. We do NOT assert the production
     80% bar here: the test-tier HashEmbedder/BM25 are lexical stubs, so the
     contract under test is "the instrument works and emits real metrics".
"""

from __future__ import annotations

import math

import pytest

from lighthouse_ai.eval import (
    build_golden_set,
    build_index,
    evaluate,
    faithfulness,
    mean_metric,
    mrr,
    precision_at_k,
    recall_at_k,
)
from lighthouse_ai.eval.golden import GOLDEN_CASES, GOLDEN_DOCUMENTS

# --- precision_at_k --------------------------------------------------------


def test_precision_perfect_top_k() -> None:
    # All 3 of top-3 relevant -> 3/3.
    assert precision_at_k(["a", "b", "c"], {"a", "b", "c"}, 3) == 1.0


def test_precision_partial() -> None:
    # 1 of top-3 relevant -> 1/3.
    assert precision_at_k(["a", "x", "y"], {"a"}, 3) == pytest.approx(1 / 3)


def test_precision_denominator_is_k_not_returned_count() -> None:
    # Only one result returned but k=5 -> 1/5, not 1/1.
    assert precision_at_k(["a"], {"a"}, 5) == pytest.approx(0.2)


def test_precision_truncates_to_k() -> None:
    # Relevant hit sits at rank 4, outside top-2.
    assert precision_at_k(["x", "y", "z", "a"], {"a"}, 2) == 0.0


def test_precision_dedups_documents() -> None:
    # Two chunks of doc "a" then a distractor; within top-2 only one unique
    # relevant doc -> 1/2.
    assert precision_at_k(["a", "a", "x"], {"a"}, 2) == pytest.approx(0.5)


def test_precision_zero_k_is_zero() -> None:
    assert precision_at_k(["a"], {"a"}, 0) == 0.0


def test_precision_no_hits() -> None:
    assert precision_at_k(["x", "y"], {"a"}, 2) == 0.0


# --- recall_at_k -----------------------------------------------------------


def test_recall_finds_half() -> None:
    # 1 of 2 relevant docs in top-3 -> 1/2.
    assert recall_at_k(["a", "x", "y"], {"a", "b"}, 3) == pytest.approx(0.5)


def test_recall_full() -> None:
    assert recall_at_k(["a", "b", "c"], {"a", "b"}, 3) == 1.0


def test_recall_outside_k_missed() -> None:
    # Relevant doc only at rank 4, k=3 -> 0 found of 1.
    assert recall_at_k(["x", "y", "z", "a"], {"a"}, 3) == 0.0


def test_recall_empty_relevant_is_one() -> None:
    # Nothing to find -> vacuously perfect.
    assert recall_at_k(["x", "y"], set(), 3) == 1.0


def test_recall_zero_k_is_zero() -> None:
    assert recall_at_k(["a"], {"a"}, 0) == 0.0


def test_recall_dedups_documents() -> None:
    # Duplicate chunks of "a" still count one relevant doc found of two.
    assert recall_at_k(["a", "a"], {"a", "b"}, 5) == pytest.approx(0.5)


# --- mrr -------------------------------------------------------------------


def test_mrr_first_rank() -> None:
    assert mrr(["a", "b"], {"a"}) == 1.0


def test_mrr_second_rank() -> None:
    assert mrr(["x", "a", "b"], {"a"}) == pytest.approx(0.5)


def test_mrr_third_rank() -> None:
    assert mrr(["x", "y", "a"], {"a"}) == pytest.approx(1 / 3)


def test_mrr_no_relevant_in_list() -> None:
    assert mrr(["x", "y"], {"a"}) == 0.0


def test_mrr_empty_relevant() -> None:
    assert mrr(["x", "y"], set()) == 0.0


def test_mrr_uses_first_occurrence_of_doc() -> None:
    # Duplicate relevant chunk: first occurrence at rank 2 -> 1/2.
    assert mrr(["x", "a", "a"], {"a"}) == pytest.approx(0.5)


# --- mean_metric -----------------------------------------------------------


def test_mean_metric_basic() -> None:
    assert mean_metric([1.0, 0.0, 0.5]) == pytest.approx(0.5)


def test_mean_metric_empty_is_zero() -> None:
    assert mean_metric([]) == 0.0


def test_mean_metric_consumes_generator() -> None:
    assert mean_metric(x / 4 for x in (1, 3)) == pytest.approx(0.5)


# --- faithfulness ----------------------------------------------------------


def test_faithfulness_fully_supported() -> None:
    answer = "Solar panels convert sunlight into electricity."
    evidence = ["Photovoltaic solar panels convert sunlight into electricity."]
    assert faithfulness(answer, evidence) == 1.0


def test_faithfulness_unsupported_with_evidence() -> None:
    # No content-token overlap -> 0.0 even though evidence exists.
    assert faithfulness("dolphins migrate annually", ["solar battery storage"]) == 0.0


def test_faithfulness_partial() -> None:
    # Content tokens: solar, panels, expensive. solar+panels supported -> 2/3.
    answer = "Solar panels are expensive."
    evidence = ["Rooftop solar panels are common."]
    assert faithfulness(answer, evidence) == pytest.approx(2 / 3)


def test_faithfulness_empty_answer_is_one() -> None:
    assert faithfulness("", ["anything"]) == 1.0


def test_faithfulness_only_stopwords_is_one() -> None:
    # Answer has no claim tokens after stopword removal.
    assert faithfulness("the and of to", ["evidence"]) == 1.0


def test_faithfulness_no_evidence_is_zero() -> None:
    assert faithfulness("real claims here", []) == 0.0


def test_faithfulness_in_unit_interval() -> None:
    val = faithfulness("solar power and bread baking", ["solar power notes"])
    assert 0.0 <= val <= 1.0


def test_faithfulness_repeated_token_not_padded() -> None:
    # "solar" repeated but only one distinct supported token of two distinct.
    answer = "solar solar storage"
    evidence = ["solar arrays"]
    assert faithfulness(answer, evidence) == pytest.approx(0.5)


# --- golden set wiring -----------------------------------------------------


def test_golden_set_shape() -> None:
    golden = build_golden_set()
    assert len(golden.documents) == 8
    assert len(golden.cases) == 6


def test_golden_relevant_ids_exist() -> None:
    # Every labelled relevant id must refer to a real document.
    doc_ids = {d.id for d in GOLDEN_DOCUMENTS}
    for case in GOLDEN_CASES:
        assert case.relevant_doc_ids <= doc_ids


def test_build_index_indexes_all_docs() -> None:
    hybrid = build_index()
    assert hybrid.store.count() >= len(GOLDEN_DOCUMENTS)


# --- end-to-end evaluate ---------------------------------------------------


def test_evaluate_reports_all_metrics() -> None:
    golden = build_golden_set()
    hybrid = build_index(golden)
    report = evaluate(hybrid, golden)
    assert set(report) == {"precision@5", "recall@5", "mrr"}
    for value in report.values():
        assert 0.0 <= value <= 1.0
        assert not math.isnan(value)


def test_evaluate_harness_works_and_reports_numbers() -> None:
    # The core contract: a working harness on the stub pipeline. Not the
    # production 80% bar — just that it retrieves something useful and ranks
    # relevant docs near the top.
    golden = build_golden_set()
    hybrid = build_index(golden)
    report = evaluate(hybrid, golden)
    assert report["mrr"] > 0.5
    assert report["precision@5"] > 0.0


def test_evaluate_recall_nonzero() -> None:
    golden = build_golden_set()
    report = evaluate(build_index(golden), golden)
    assert report["recall@5"] > 0.0


def test_evaluate_custom_k_label() -> None:
    golden = build_golden_set()
    report = evaluate(build_index(golden), golden, k=3)
    assert "precision@3" in report
    assert "recall@3" in report
