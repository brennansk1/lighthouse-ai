"""Tests for ``src/lighthouse_ai/eval/skill_eval.py`` (SL13 per-skill eval module).

All tests are offline-deterministic: no network, no real LLM.

Coverage:
  - run_skill_eval() returns a dict with the expected shape.
  - per_skill key contains recall_at_k in [0, 1] for each expected skill.
  - macro_recall is in [0, 1].
  - Works gracefully with an empty skill library (empty skills=[]).
  - Works gracefully when recommend raises an exception.
  - per_skill_calibration() handles a missing db (returns {}).
  - per_skill_calibration() handles an empty / no resolved rows (returns {}).
  - per_skill_calibration() computes correct Brier scores for seeded rows.
  - SKILL_EVAL_CASES contains at least the news_orchestrator gold target.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from lighthouse_ai.eval.skill_eval import (
    SKILL_EVAL_CASES,
    per_skill_calibration,
    run_skill_eval,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_recommend_always_empty(question, mode, **kwargs):
    """A recommend stub that always returns an empty list."""
    return []


def _stub_recommend_raises(question, mode, **kwargs):
    """A recommend stub that always raises."""
    raise RuntimeError("stub error")


def _stub_recommend_gold_always_first(question, mode, **kwargs):
    """A recommend stub that always ranks the gold skill first.

    Finds the gold_id for the current case from SKILL_EVAL_CASES by matching
    question text and returns a Recommendation-like object with that id.
    """
    from types import SimpleNamespace

    # Find which gold_id maps to this question.
    for q, m, gold_id in SKILL_EVAL_CASES:
        if q == question and m == mode:
            return [SimpleNamespace(skill_id=gold_id, score=1.0, reason="stub")]
    # Fallback: return general_web.
    return [SimpleNamespace(skill_id="general_web", score=0.5, reason="stub")]


# ---------------------------------------------------------------------------
# run_skill_eval tests
# ---------------------------------------------------------------------------


class TestRunSkillEval:
    def test_returns_dict_with_required_keys(self):
        result = run_skill_eval(recommend=_stub_recommend_always_empty)
        required_keys = {
            "per_skill",
            "macro_recall",
            "k",
            "n_cases",
            "n_scored",
            "per_case",
            "note",
        }
        assert required_keys <= result.keys(), f"Missing keys: {required_keys - result.keys()}"

    def test_macro_recall_in_range(self):
        result = run_skill_eval(recommend=_stub_recommend_always_empty)
        assert 0.0 <= result["macro_recall"] <= 1.0

    def test_per_skill_is_dict(self):
        result = run_skill_eval(recommend=_stub_recommend_always_empty)
        assert isinstance(result["per_skill"], dict)

    def test_per_skill_contains_news_orchestrator(self):
        """news_orchestrator is in SKILL_EVAL_CASES so it must appear in per_skill."""
        result = run_skill_eval(recommend=_stub_recommend_always_empty)
        assert "news_orchestrator" in result["per_skill"], (
            f"per_skill keys: {list(result['per_skill'].keys())}"
        )

    def test_per_skill_values_have_expected_fields(self):
        result = run_skill_eval(recommend=_stub_recommend_always_empty)
        for skill_id, info in result["per_skill"].items():
            assert "recall_at_k" in info, f"Missing recall_at_k for {skill_id}"
            assert "n_cases" in info, f"Missing n_cases for {skill_id}"
            assert "n_hits" in info, f"Missing n_hits for {skill_id}"

    def test_per_skill_recall_in_range(self):
        result = run_skill_eval(recommend=_stub_recommend_always_empty)
        for skill_id, info in result["per_skill"].items():
            r = info["recall_at_k"]
            assert 0.0 <= r <= 1.0, f"recall_at_k out of range for {skill_id}: {r}"

    def test_empty_recommend_returns_zero_recall(self):
        result = run_skill_eval(recommend=_stub_recommend_always_empty)
        assert result["macro_recall"] == 0.0
        for skill_id, info in result["per_skill"].items():
            assert info["recall_at_k"] == 0.0, (
                f"Expected 0.0 for {skill_id}, got {info['recall_at_k']}"
            )

    def test_n_cases_matches_eval_cases_length(self):
        result = run_skill_eval(recommend=_stub_recommend_always_empty)
        assert result["n_cases"] == len(SKILL_EVAL_CASES)

    def test_per_case_length_matches_n_cases(self):
        result = run_skill_eval(recommend=_stub_recommend_always_empty)
        assert len(result["per_case"]) == result["n_cases"]

    def test_per_case_has_required_fields(self):
        result = run_skill_eval(recommend=_stub_recommend_always_empty)
        required = {"question", "mode", "gold_id", "recall_at_k", "ranked_ids", "note"}
        for case in result["per_case"]:
            assert required <= case.keys(), f"Missing case keys: {required - case.keys()}"

    def test_tolerates_recommend_raising(self):
        """run_skill_eval must not raise even if recommend raises."""
        result = run_skill_eval(recommend=_stub_recommend_raises)
        assert isinstance(result, dict)
        assert result["macro_recall"] == 0.0
        # note should mention the error
        assert "RuntimeError" in result["note"] or result["note"] != ""

    def test_perfect_recall_when_gold_always_first(self):
        """When the recommend stub always surfaces the gold skill first, recall@k=1."""
        result = run_skill_eval(recommend=_stub_recommend_gold_always_first)
        assert result["macro_recall"] == 1.0, (
            f"Expected macro_recall=1.0, got {result['macro_recall']}"
        )
        for skill_id, info in result["per_skill"].items():
            assert info["recall_at_k"] == 1.0, (
                f"Expected recall_at_k=1.0 for {skill_id}, got {info['recall_at_k']}"
            )

    def test_custom_k_is_respected(self):
        result = run_skill_eval(recommend=_stub_recommend_always_empty, k=3)
        assert result["k"] == 3

    def test_default_k_is_5(self):
        result = run_skill_eval(recommend=_stub_recommend_always_empty)
        assert result["k"] == 5

    def test_skills_kwarg_passed_to_recommend(self):
        """skills kwarg is forwarded to recommend (used by tests to inject a library)."""
        received_skills = []

        def _capturing_recommend(question, mode, skills=None, **kwargs):
            if skills is not None:
                received_skills.extend(skills)
            return []

        run_skill_eval(recommend=_capturing_recommend, skills=["dummy"])
        assert received_skills, "Expected recommend to be called with skills=..."

    def test_note_empty_when_all_succeed(self):
        """When recommend succeeds for every case, note is empty string."""
        result = run_skill_eval(recommend=_stub_recommend_gold_always_first)
        assert result["note"] == ""

    def test_per_skill_n_hits_matches_n_cases_on_perfect(self):
        """On a perfect recommender, n_hits == n_cases for every skill."""
        result = run_skill_eval(recommend=_stub_recommend_gold_always_first)
        for skill_id, info in result["per_skill"].items():
            assert info["n_hits"] == info["n_cases"], (
                f"For {skill_id}: n_hits={info['n_hits']} != n_cases={info['n_cases']}"
            )

    def test_works_with_production_recommender_offline(self):
        """Smoke: calling with no recommend arg uses the production recommender
        (offline token-overlap path).  Must not raise; result shape is valid."""
        try:
            result = run_skill_eval()  # uses production recommender
        except Exception as exc:
            pytest.skip(f"Production recommender unavailable in test env: {exc}")
        assert isinstance(result, dict)
        assert 0.0 <= result["macro_recall"] <= 1.0


# ---------------------------------------------------------------------------
# per_skill_calibration tests
# ---------------------------------------------------------------------------


class TestPerSkillCalibration:
    def test_missing_db_returns_empty(self, tmp_path):
        result = per_skill_calibration(tmp_path / "no_such.db")
        assert result == {}

    def test_empty_db_returns_empty(self, tmp_path):
        db_path = tmp_path / "positions.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE positions "
            "(id INTEGER PRIMARY KEY, confidence REAL, outcome INTEGER, "
            "metadata_json TEXT)"
        )
        conn.commit()
        conn.close()
        result = per_skill_calibration(db_path)
        assert result == {}

    def test_no_resolved_rows_returns_empty(self, tmp_path):
        db_path = tmp_path / "positions.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE positions "
            "(id INTEGER PRIMARY KEY, confidence REAL, outcome INTEGER, "
            "metadata_json TEXT)"
        )
        # Insert unresolved position (outcome IS NULL).
        conn.execute(
            "INSERT INTO positions (confidence, outcome, metadata_json) VALUES (?, ?, ?)",
            (0.7, None, json.dumps({"skill_id": "reuters"})),
        )
        conn.commit()
        conn.close()
        result = per_skill_calibration(db_path)
        assert result == {}

    def test_single_resolved_position(self, tmp_path):
        db_path = tmp_path / "positions.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE positions "
            "(id INTEGER PRIMARY KEY, confidence REAL, outcome INTEGER, "
            "metadata_json TEXT)"
        )
        # probability=0.7, outcome=True → Brier = (0.7-1)^2 = 0.09
        conn.execute(
            "INSERT INTO positions (confidence, outcome, metadata_json) VALUES (?, ?, ?)",
            (0.7, 1, json.dumps({"skill_id": "reuters"})),
        )
        conn.commit()
        conn.close()

        result = per_skill_calibration(db_path)
        assert "reuters" in result
        entry = result["reuters"]
        assert entry["n_resolved"] == 1
        assert abs(entry["mean_brier"] - 0.09) < 1e-4, (
            f"Expected mean_brier~0.09, got {entry['mean_brier']}"
        )

    def test_multiple_skills_separated(self, tmp_path):
        db_path = tmp_path / "positions.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE positions "
            "(id INTEGER PRIMARY KEY, confidence REAL, outcome INTEGER, "
            "metadata_json TEXT)"
        )
        rows = [
            # reuters: Brier = (0.8-1)^2 = 0.04
            (0.8, 1, json.dumps({"skill_id": "reuters"})),
            # bbc_news: Brier = (0.5-0)^2 = 0.25
            (0.5, 0, json.dumps({"skill_id": "bbc_news"})),
            # bbc_news second row: Brier = (0.9-1)^2 = 0.01
            (0.9, 1, json.dumps({"skill_id": "bbc_news"})),
        ]
        conn.executemany(
            "INSERT INTO positions (confidence, outcome, metadata_json) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()

        result = per_skill_calibration(db_path)
        assert "reuters" in result
        assert "bbc_news" in result
        assert result["reuters"]["n_resolved"] == 1
        assert result["bbc_news"]["n_resolved"] == 2

        # bbc_news mean Brier = (0.25 + 0.01) / 2 = 0.13
        assert abs(result["bbc_news"]["mean_brier"] - 0.13) < 1e-4, (
            f"Expected bbc_news mean_brier~0.13, got {result['bbc_news']['mean_brier']}"
        )

    def test_rows_missing_skill_id_are_skipped(self, tmp_path):
        db_path = tmp_path / "positions.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE positions "
            "(id INTEGER PRIMARY KEY, confidence REAL, outcome INTEGER, "
            "metadata_json TEXT)"
        )
        rows = [
            # Has skill_id.
            (0.6, 1, json.dumps({"skill_id": "arxiv"})),
            # Missing skill_id → should be skipped.
            (0.4, 0, json.dumps({"other": "data"})),
            # Null metadata → should be skipped.
            (0.3, 1, None),
        ]
        conn.executemany(
            "INSERT INTO positions (confidence, outcome, metadata_json) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()

        result = per_skill_calibration(db_path)
        assert "arxiv" in result
        assert result["arxiv"]["n_resolved"] == 1
        assert len(result) == 1  # only arxiv, others skipped

    def test_malformed_metadata_json_is_skipped(self, tmp_path):
        db_path = tmp_path / "positions.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE positions "
            "(id INTEGER PRIMARY KEY, confidence REAL, outcome INTEGER, "
            "metadata_json TEXT)"
        )
        rows = [
            (0.6, 1, json.dumps({"skill_id": "arxiv"})),
            (0.4, 0, "not-valid-json"),
        ]
        conn.executemany(
            "INSERT INTO positions (confidence, outcome, metadata_json) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()

        result = per_skill_calibration(db_path)
        assert "arxiv" in result
        assert result["arxiv"]["n_resolved"] == 1

    def test_mean_brier_in_range(self, tmp_path):
        """mean_brier must always be in [0, 1]."""
        db_path = tmp_path / "positions.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE positions "
            "(id INTEGER PRIMARY KEY, confidence REAL, outcome INTEGER, "
            "metadata_json TEXT)"
        )
        for conf, outcome in [(0.0, 0), (1.0, 1), (0.5, 1), (0.5, 0)]:
            conn.execute(
                "INSERT INTO positions (confidence, outcome, metadata_json) VALUES (?, ?, ?)",
                (conf, int(outcome), json.dumps({"skill_id": "reuters"})),
            )
        conn.commit()
        conn.close()

        result = per_skill_calibration(db_path)
        brier = result["reuters"]["mean_brier"]
        assert 0.0 <= brier <= 1.0

    def test_per_skill_calibration_tolerates_corrupt_db(self, tmp_path):
        """A totally corrupt SQLite file must not raise — returns {}."""
        db_path = tmp_path / "corrupt.db"
        db_path.write_bytes(b"not a sqlite database at all")
        result = per_skill_calibration(db_path)
        assert result == {}


# ---------------------------------------------------------------------------
# SKILL_EVAL_CASES shape tests
# ---------------------------------------------------------------------------


class TestSkillEvalCases:
    def test_cases_is_nonempty_tuple(self):
        assert isinstance(SKILL_EVAL_CASES, tuple)
        assert len(SKILL_EVAL_CASES) > 0

    def test_each_case_is_3_tuple(self):
        for i, case in enumerate(SKILL_EVAL_CASES):
            assert len(case) == 3, f"Case {i} has {len(case)} elements, expected 3"
            question, mode, gold_id = case
            assert isinstance(question, str) and question
            assert isinstance(mode, str) and mode
            assert isinstance(gold_id, str) and gold_id

    def test_news_orchestrator_present_in_cases(self):
        gold_ids = {gold_id for _, _, gold_id in SKILL_EVAL_CASES}
        assert "news_orchestrator" in gold_ids

    def test_valid_modes_used(self):
        valid_modes = {
            "investigate",
            "survey",
            "reconstruct",
            "decide",
            "adjudicate",
            "watch",
            "ask",
        }
        for question, mode, gold_id in SKILL_EVAL_CASES:
            assert mode in valid_modes, (
                f"Unknown mode '{mode}' in case ({question[:40]!r}, {gold_id!r})"
            )
