"""Tests for the self-learning skill library (distil → retrieve → reinforce → prune).

All deterministic and offline: no gateway (rationale falls back to template),
no network. Exercises the verification.skills persistence + scoring and the
learning.distiller/retrieval logic.
"""

from __future__ import annotations

import pytest

from lighthouse_ai.learning import (
    distill_skill,
    format_for_planner,
    keywords_for,
    select_skills,
)
from lighthouse_ai.verification.skills import (
    compute_score,
    complete_application,
    get_skill,
    list_skills,
    prune_skills,
    record_application,
    relevant_skills,
)

Q1 = "What are the comparative effects of GLP-1 agonists versus metformin on cardiovascular outcomes?"
SUBS1 = [
    "What cardiovascular outcomes do GLP-1 agonists improve?",
    "What cardiovascular outcomes does metformin improve?",
    "How do head-to-head trials compare the two?",
]


# --- keyword extraction ---

def test_keywords_strips_stopwords_and_dedupes():
    kws = keywords_for("What is the the effect of X on X outcomes?")
    assert "what" not in kws and "the" not in kws and "is" not in kws
    assert kws.count("outcomes") <= 1


# --- compute_score ---

def test_compute_score_zero_for_untried():
    assert compute_score(0, 0, 0.9) == 0.0


def test_compute_score_rewards_wins_and_coverage():
    low = compute_score(5, 1, 0.4)
    high = compute_score(5, 5, 0.95)
    assert 0.0 < low < high <= 1.0


def test_compute_score_confidence_ramps_with_trials():
    one_trial = compute_score(1, 1, 1.0)
    many = compute_score(10, 10, 1.0)
    assert many > one_trial  # more trials → higher confidence weight


# --- distillation ---

def test_distill_creates_skill(migrated_paths):
    d = distill_skill(
        migrated_paths.state_db, question=Q1, question_type="comparative",
        sub_questions=SUBS1, coverage=0.9, wep_phrase="likely",
        source_count=12, evidence_domains=["arxiv", "pubmed"])
    assert d is not None and not d.merged
    skills = list_skills(migrated_paths.state_db)
    assert len(skills) == 1
    s = skills[0]
    assert s.question_type == "comparative"
    assert s.body["schema"] == 1
    assert s.decomposition == SUBS1[:6]
    assert s.score == pytest.approx(0.9)  # seeded from coverage
    assert "metformin" in s.trigger_keywords


def test_distill_returns_none_without_subquestions(migrated_paths):
    d = distill_skill(
        migrated_paths.state_db, question=Q1, question_type="comparative",
        sub_questions=[], coverage=0.9, wep_phrase="likely", source_count=1)
    assert d is None
    assert list_skills(migrated_paths.state_db) == []


def test_distill_merges_same_type_high_overlap(migrated_paths):
    distill_skill(
        migrated_paths.state_db, question=Q1, question_type="comparative",
        sub_questions=SUBS1, coverage=0.8, wep_phrase="likely", source_count=10)
    # Same comparative question (same keywords) → should merge, not duplicate.
    d2 = distill_skill(
        migrated_paths.state_db, question=Q1, question_type="comparative",
        sub_questions=SUBS1, coverage=0.95, wep_phrase="likely", source_count=20)
    assert d2 is not None and d2.merged
    skills = list_skills(migrated_paths.state_db)
    assert len(skills) == 1  # merged, not a second row
    assert skills[0].body["quality"]["coverage"] == pytest.approx(0.95)


def test_distill_distinct_type_does_not_merge(migrated_paths):
    distill_skill(
        migrated_paths.state_db, question=Q1, question_type="comparative",
        sub_questions=SUBS1, coverage=0.8, wep_phrase="likely", source_count=10)
    distill_skill(
        migrated_paths.state_db,
        question="Why did the Roman Empire collapse economically?",
        question_type="causal_explanation",
        sub_questions=["What fiscal pressures existed?", "What triggered decline?"],
        coverage=0.85, wep_phrase="likely", source_count=8)
    assert len(list_skills(migrated_paths.state_db)) == 2


# --- retrieval ---

def test_relevant_skills_matches_type_and_keywords(migrated_paths):
    distill_skill(
        migrated_paths.state_db, question=Q1, question_type="comparative",
        sub_questions=SUBS1, coverage=0.9, wep_phrase="likely", source_count=12)
    hits = select_skills(
        migrated_paths.state_db,
        "Comparative cardiovascular outcomes: metformin vs GLP-1 agonists",
        question_type="comparative", k=3)
    assert len(hits) == 1
    assert hits[0].question_type == "comparative"


def test_relevant_skills_excludes_unrelated(migrated_paths):
    distill_skill(
        migrated_paths.state_db, question=Q1, question_type="comparative",
        sub_questions=SUBS1, coverage=0.9, wep_phrase="likely", source_count=12)
    hits = select_skills(
        migrated_paths.state_db,
        "How do glaciers form in alpine valleys?", k=3)
    assert hits == []  # no type match, no keyword overlap → nothing injected


def test_format_for_planner_empty_is_blank():
    assert format_for_planner([]) == ""


def test_format_for_planner_includes_decomposition(migrated_paths):
    distill_skill(
        migrated_paths.state_db, question=Q1, question_type="comparative",
        sub_questions=SUBS1, coverage=0.9, wep_phrase="likely", source_count=12)
    block = format_for_planner(list_skills(migrated_paths.state_db))
    assert "Learned strategies" in block
    assert "Decomposition that worked" in block


# --- reinforcement ---

def test_application_lifecycle_updates_score(migrated_paths):
    d = distill_skill(
        migrated_paths.state_db, question=Q1, question_type="comparative",
        sub_questions=SUBS1, coverage=0.9, wep_phrase="likely", source_count=12)
    sid = d.skill_id
    # Apply + complete with a passing, high-coverage outcome.
    record_application(migrated_paths.state_db, skill_id=sid, job_id="job1")
    complete_application(migrated_paths.state_db, skill_id=sid, job_id="job1",
                         coverage=0.92, passed=True)
    s = get_skill(migrated_paths.state_db, sid)
    assert s.applied_count == 1
    assert s.win_count == 1
    assert s.avg_coverage == pytest.approx(0.92)
    assert s.score > 0


def test_failed_applications_lower_winrate(migrated_paths):
    d = distill_skill(
        migrated_paths.state_db, question=Q1, question_type="comparative",
        sub_questions=SUBS1, coverage=0.9, wep_phrase="likely", source_count=12)
    sid = d.skill_id
    for i in range(4):
        record_application(migrated_paths.state_db, skill_id=sid, job_id=f"j{i}")
        complete_application(migrated_paths.state_db, skill_id=sid, job_id=f"j{i}",
                             coverage=0.2, passed=False)
    s = get_skill(migrated_paths.state_db, sid)
    assert s.win_rate == 0.0
    assert s.applied_count == 4


# --- pruning ---

def test_prune_archives_underperformers(migrated_paths):
    d = distill_skill(
        migrated_paths.state_db, question=Q1, question_type="comparative",
        sub_questions=SUBS1, coverage=0.9, wep_phrase="likely", source_count=12)
    sid = d.skill_id
    for i in range(5):
        record_application(migrated_paths.state_db, skill_id=sid, job_id=f"j{i}")
        complete_application(migrated_paths.state_db, skill_id=sid, job_id=f"j{i}",
                             coverage=0.1, passed=False)
    archived = prune_skills(migrated_paths.state_db, min_trials=5, min_winrate=0.3)
    assert sid in archived
    # Archived skills are excluded from active retrieval.
    assert select_skills(migrated_paths.state_db, Q1,
                         question_type="comparative") == []
    # But still present (not hard-deleted) for auditability.
    assert get_skill(migrated_paths.state_db, sid).status == "archived"


def test_prune_keeps_winners_and_untried(migrated_paths):
    d = distill_skill(
        migrated_paths.state_db, question=Q1, question_type="comparative",
        sub_questions=SUBS1, coverage=0.9, wep_phrase="likely", source_count=12)
    sid = d.skill_id
    for i in range(5):
        record_application(migrated_paths.state_db, skill_id=sid, job_id=f"j{i}")
        complete_application(migrated_paths.state_db, skill_id=sid, job_id=f"j{i}",
                             coverage=0.9, passed=True)
    archived = prune_skills(migrated_paths.state_db, min_trials=5, min_winrate=0.3)
    assert sid not in archived
    assert get_skill(migrated_paths.state_db, sid).status == "active"
