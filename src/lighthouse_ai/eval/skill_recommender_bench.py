"""Skill-recommender bench — measures top-1 / top-3 accuracy against a set of
(question, mode, expected_best_skill_id) golden triples.

Design notes
------------
* Fully offline-deterministic: uses ``recommend`` with token-overlap similarity
  (no embedder, no gateway).
* Accuracy metrics:
    - top-1 accuracy: gold skill is the #1 recommendation.
    - top-3 accuracy: gold skill appears in the top 3 recommendations.
* Tolerates an empty skill library: when ``recommend`` returns no results or
  the gold skill is absent, both accuracies are 0 for that case and a ``note``
  is attached — no crash.
* The golden triples drive the real production manifests; supply your own
  ``recommend`` callable (same signature) to test a custom catalog.
"""

from __future__ import annotations

from collections.abc import Callable

__all__ = ["RECOMMENDER_CASES", "run_skill_recommender_bench"]

# ---------------------------------------------------------------------------
# Golden (question, mode, gold_skill_id) triples
# ---------------------------------------------------------------------------
# gold_skill_id must be a skill present in the real library for the bench to
# score > 0 against the live catalog; missing skills degrade gracefully.

RECOMMENDER_CASES: tuple[tuple[str, str, str], ...] = (
    # arXiv: peer-reviewed academic research questions
    (
        "What are the most cited papers on attention mechanisms in transformers?",
        "investigate",
        "arxiv",
    ),
    (
        "Survey preprints on reinforcement learning from human feedback",
        "survey",
        "arxiv",
    ),
    (
        "Find peer-reviewed papers explaining the scaling laws of language models",
        "investigate",
        "arxiv",
    ),
    # Wikipedia: encyclopedic / orientation / lookup questions
    (
        "What is a brief encyclopedic overview of quantum computing?",
        "ask",
        "wikipedia",
    ),
    (
        "Explain the historical background and definition of the Cold War",
        "ask",
        "wikipedia",
    ),
    # general_web: broad web / news / current events
    (
        "What are the latest news about generative AI products?",
        "watch",
        "general_web",
    ),
    (
        "Find recent web articles about climate policy announcements",
        "investigate",
        "general_web",
    ),
    # youtube: video / tutorial / talk questions
    (
        "Find tutorial videos explaining how transformers work",
        "ask",
        "youtube",
    ),
)

_TOP_1 = 1
_TOP_3 = 3


def run_skill_recommender_bench(
    *,
    recommend: Callable | None = None,
) -> dict:
    """Run the skill-recommender bench and return a metrics dict.

    Parameters
    ----------
    recommend:
        Callable with the same signature as
        ``lighthouse_ai.skills.recommender.recommend``.  When ``None`` the
        production recommender is imported at call time.

    Returns
    -------
    dict with keys:
        ``top1_accuracy``  — fraction of cases where gold skill is #1 (float in [0, 1])
        ``top3_accuracy``  — fraction of cases where gold skill is in top 3 (float in [0, 1])
        ``n_cases``        — total cases evaluated
        ``n_scored``       — cases where gold skill was found in recommendations at all
        ``per_case``       — list of per-case dicts
        ``note``           — non-empty string if degraded (empty library, etc.)
    """
    if recommend is None:
        from ..skills.recommender import recommend as _default_recommend

        recommend = _default_recommend

    per_case: list[dict] = []
    top1_hits = 0
    top3_hits = 0
    notes: list[str] = []

    for question, mode, gold_id in RECOMMENDER_CASES:
        case_note = ""
        try:
            recs = recommend(question, mode)
        except Exception as exc:
            recs = []
            case_note = f"recommend raised {type(exc).__name__}: {exc}"

        ranked_ids = [r.skill_id for r in recs]

        if not ranked_ids:
            case_note = case_note or "empty recommendation list (library may be empty)"
            hit_top1 = False
            hit_top3 = False
        else:
            hit_top1 = len(ranked_ids) >= 1 and ranked_ids[0] == gold_id
            hit_top3 = gold_id in ranked_ids[:_TOP_3]

        if hit_top1:
            top1_hits += 1
        if hit_top3:
            top3_hits += 1
        if case_note:
            notes.append(case_note)

        per_case.append(
            {
                "question": question[:80],
                "mode": mode,
                "gold_id": gold_id,
                "top1": hit_top1,
                "top3": hit_top3,
                "ranked_ids": ranked_ids[:_TOP_3],
                "note": case_note,
            }
        )

    n_cases = len(per_case)
    n_scored = sum(1 for c in per_case if c["note"] == "")
    top1_acc = top1_hits / n_cases if n_cases > 0 else 0.0
    top3_acc = top3_hits / n_cases if n_cases > 0 else 0.0

    return {
        "top1_accuracy": round(top1_acc, 4),
        "top3_accuracy": round(top3_acc, 4),
        "n_cases": n_cases,
        "n_scored": n_scored,
        "per_case": per_case,
        "note": "; ".join(notes) if notes else "",
    }
