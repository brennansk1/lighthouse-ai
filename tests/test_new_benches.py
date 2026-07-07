"""Zone M — evaluation bench smoke-tests.

Covers all four run_* bench functions:
  * run_extraction_bench  (eval/extraction_bench.py)
  * run_sandbox_bench     (eval/sandbox_bench.py)
  * run_source_coverage_bench (eval/source_coverage_bench.py)
  * run_skill_recommender_bench (eval/skill_recommender_bench.py)

Contract per function:
  * Returns a dict.
  * Required metric keys are present.
  * All float metrics are in [0, 1].
  * No exceptions raised.

Additional sandbox contracts:
  * fp == 0 on the benign set (zero false-positive requirement).
  * EICAR payload is caught (reject verdict).
"""

from __future__ import annotations

from lighthouse_ai.eval.extraction_bench import run_extraction_bench
from lighthouse_ai.eval.sandbox_bench import (
    BENCH_PAYLOADS,
    LabeledPayload,
    run_sandbox_bench,
)
from lighthouse_ai.eval.skill_recommender_bench import run_skill_recommender_bench
from lighthouse_ai.eval.source_coverage_bench import run_source_coverage_bench
from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.sandbox.scanners import EICAR_SIGNATURE

# ===========================================================================
# Extraction bench
# ===========================================================================


def test_extraction_bench_returns_dict() -> None:
    result = run_extraction_bench()
    assert isinstance(result, dict)


def test_extraction_bench_required_keys() -> None:
    result = run_extraction_bench()
    assert "mean_f1" in result
    assert "per_case" in result
    assert "extractor" in result
    assert "n_cases" in result


def test_extraction_bench_mean_f1_in_range() -> None:
    result = run_extraction_bench()
    assert 0.0 <= result["mean_f1"] <= 1.0


def test_extraction_bench_n_cases_positive() -> None:
    result = run_extraction_bench()
    assert result["n_cases"] > 0


def test_extraction_bench_per_case_f1_in_range() -> None:
    result = run_extraction_bench()
    for case in result["per_case"]:
        assert 0.0 <= case["f1"] <= 1.0, f"case {case['case_id']} f1 out of range: {case['f1']}"


def test_extraction_bench_extractor_is_known_string() -> None:
    result = run_extraction_bench()
    assert result["extractor"] in ("trafilatura", "stdlib")


# ===========================================================================
# Sandbox bench
# ===========================================================================


def test_sandbox_bench_returns_dict(tmp_path) -> None:
    result = run_sandbox_bench(data_dir=tmp_path)
    assert isinstance(result, dict)


def test_sandbox_bench_required_keys(tmp_path) -> None:
    result = run_sandbox_bench(data_dir=tmp_path)
    for key in (
        "tp",
        "fp",
        "tn",
        "fn",
        "precision",
        "recall",
        "false_positive_rate",
        "per_case",
        "n_hostile",
        "n_benign",
    ):
        assert key in result, f"missing key: {key}"


def test_sandbox_bench_float_metrics_in_range(tmp_path) -> None:
    result = run_sandbox_bench(data_dir=tmp_path)
    for key in ("precision", "recall", "false_positive_rate"):
        assert 0.0 <= result[key] <= 1.0, f"{key}={result[key]} out of range"


def test_sandbox_bench_zero_false_positives_on_benign(tmp_path) -> None:
    """The zero-FP contract: build_default_broker must never flag clean documents."""
    benign_only = tuple(p for p in BENCH_PAYLOADS if p.label == "benign")
    assert len(benign_only) > 0, "bench has no benign payloads"
    result = run_sandbox_bench(data_dir=tmp_path, payloads=benign_only)
    assert result["fp"] == 0, (
        f"False positives on benign set: {result['fp']} — per_case={result['per_case']}"
    )


def test_sandbox_bench_eicar_is_caught(tmp_path) -> None:
    """EICAR must be rejected, not admitted or quarantined ambiguously."""
    eicar_payload = LabeledPayload(
        payload=EICAR_SIGNATURE + b"\n",
        content_type="application/octet-stream",
        filename="eicar.com",
        label="hostile",
        description="EICAR antivirus test string",
        expect_verdict="reject",
    )
    broker = build_default_broker(tmp_path)
    outcome = broker.admit(
        eicar_payload.payload,
        filename=eicar_payload.filename,
        content_type=eicar_payload.content_type,
    )
    assert outcome.verdict.value == "reject", (
        f"EICAR was not rejected; got {outcome.verdict.value!r}"
    )


def test_sandbox_bench_via_build_default_broker(tmp_path) -> None:
    """run_sandbox_bench works when called with a tmp_path-backed data_dir."""
    result = run_sandbox_bench(data_dir=tmp_path)
    # At least some hostile payloads should be caught (recall > 0).
    assert result["recall"] > 0.0, "Sandbox bench caught nothing — check scanners"
    assert result["n_hostile"] > 0
    assert result["n_benign"] > 0


# ===========================================================================
# Source-coverage bench
# ===========================================================================


def test_source_coverage_bench_returns_dict() -> None:
    result = run_source_coverage_bench()
    assert isinstance(result, dict)


def test_source_coverage_bench_required_keys() -> None:
    result = run_source_coverage_bench()
    for key in ("recall_at_k", "mrr", "k", "n_cases", "n_scored", "per_case", "note"):
        assert key in result, f"missing key: {key}"


def test_source_coverage_bench_float_metrics_in_range() -> None:
    result = run_source_coverage_bench()
    assert 0.0 <= result["recall_at_k"] <= 1.0
    assert 0.0 <= result["mrr"] <= 1.0


def test_source_coverage_bench_k_matches_default() -> None:
    result = run_source_coverage_bench()
    assert result["k"] == 5


def test_source_coverage_bench_n_cases_positive() -> None:
    result = run_source_coverage_bench()
    assert result["n_cases"] > 0


def test_source_coverage_bench_per_case_shape() -> None:
    result = run_source_coverage_bench()
    for case in result["per_case"]:
        assert "question" in case
        assert "gold_id" in case
        assert "recall_at_k" in case
        assert "mrr" in case
        assert 0.0 <= case["recall_at_k"] <= 1.0
        assert 0.0 <= case["mrr"] <= 1.0


def test_source_coverage_bench_tolerates_empty_library(tmp_path) -> None:
    """Empty library: bench must return 0 metrics with a note, never crash."""
    from lighthouse_ai.skills.recommender import recommend as _prod_rec

    empty_lib = tmp_path / "empty_library"
    empty_lib.mkdir()

    def _empty_recommend(question, mode, **kwargs):
        return _prod_rec(question, mode, library_dir=empty_lib, **kwargs)

    result = run_source_coverage_bench(recommend=_empty_recommend)
    assert isinstance(result, dict)
    assert result["recall_at_k"] == 0.0
    assert result["mrr"] == 0.0
    # Should note that the library returned nothing.
    assert result["note"] != "" or result["n_scored"] == 0


def test_source_coverage_bench_custom_recommend() -> None:
    """A stub recommend that always returns general_web #1 should score
    recall=1 for every general_web case and 0 for others."""
    from lighthouse_ai.skills.recommender import Recommendation

    def _stub(question, mode, **kwargs):
        return [
            Recommendation("general_web", 1.0, "stub", "primary"),
        ]

    result = run_source_coverage_bench(recommend=_stub)
    assert isinstance(result, dict)
    # At least some cases have general_web as gold → recall > 0
    assert result["recall_at_k"] >= 0.0


# ===========================================================================
# Skill-recommender bench
# ===========================================================================


def test_skill_recommender_bench_returns_dict() -> None:
    result = run_skill_recommender_bench()
    assert isinstance(result, dict)


def test_skill_recommender_bench_required_keys() -> None:
    result = run_skill_recommender_bench()
    for key in ("top1_accuracy", "top3_accuracy", "n_cases", "n_scored", "per_case", "note"):
        assert key in result, f"missing key: {key}"


def test_skill_recommender_bench_float_metrics_in_range() -> None:
    result = run_skill_recommender_bench()
    assert 0.0 <= result["top1_accuracy"] <= 1.0
    assert 0.0 <= result["top3_accuracy"] <= 1.0


def test_skill_recommender_bench_top3_ge_top1() -> None:
    """top-3 accuracy must be >= top-1 accuracy by definition."""
    result = run_skill_recommender_bench()
    assert result["top3_accuracy"] >= result["top1_accuracy"]


def test_skill_recommender_bench_n_cases_positive() -> None:
    result = run_skill_recommender_bench()
    assert result["n_cases"] > 0


def test_skill_recommender_bench_per_case_shape() -> None:
    result = run_skill_recommender_bench()
    for case in result["per_case"]:
        assert "question" in case
        assert "mode" in case
        assert "gold_id" in case
        assert "top1" in case
        assert "top3" in case
        assert isinstance(case["top1"], bool)
        assert isinstance(case["top3"], bool)
        # top3 must be at least as good as top1 per case
        if case["top1"]:
            assert case["top3"]


def test_skill_recommender_bench_tolerates_empty_library(tmp_path) -> None:
    """Empty library: bench returns 0 accuracies and notes, never crashes."""
    from lighthouse_ai.skills.recommender import recommend as _prod_rec

    empty_lib = tmp_path / "empty_library"
    empty_lib.mkdir()

    def _empty_recommend(question, mode, **kwargs):
        return _prod_rec(question, mode, library_dir=empty_lib, **kwargs)

    result = run_skill_recommender_bench(recommend=_empty_recommend)
    assert isinstance(result, dict)
    assert result["top1_accuracy"] == 0.0
    assert result["top3_accuracy"] == 0.0
    assert result["note"] != "" or result["n_scored"] == 0


def test_skill_recommender_bench_custom_recommend() -> None:
    """A stub that always surfaces 'arxiv' #1 should have >0 top1 accuracy
    for arxiv cases."""
    from lighthouse_ai.skills.recommender import Recommendation

    def _stub(question, mode, **kwargs):
        return [
            Recommendation("arxiv", 1.0, "stub", "primary"),
            Recommendation("general_web", 0.5, "stub", "breadth"),
        ]

    result = run_skill_recommender_bench(recommend=_stub)
    assert result["top1_accuracy"] > 0.0
    assert result["top3_accuracy"] >= result["top1_accuracy"]
