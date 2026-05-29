"""Source-coverage bench — measures whether the recommender surfaces the
expected source for a curated set of (question, gold_source_id) pairs.

Design notes
------------
* Fully offline-deterministic: uses ``recommend`` with token-overlap similarity
  (no embedder, no gateway).
* Metric: recall@k — does the gold source appear in the top-k recommendations?
  We also report MRR so callers can see how far down the gold source sits.
* Tolerates an empty skill library: when ``recommend`` returns no results or
  the gold source is not in the library, the case scores 0 and a ``note`` is
  attached to the result dict — no crash.
* The golden pairs are written so they exercise the real manifests shipped
  with Lighthouse. Tests that supply their own ``recommend`` stub may pass any
  callable with the same signature.
"""

from __future__ import annotations

from collections.abc import Callable

from .metrics import mean_metric, mrr, recall_at_k

__all__ = ["COVERAGE_CASES", "run_source_coverage_bench"]

# ---------------------------------------------------------------------------
# Golden (question, gold_source_id) pairs
# ---------------------------------------------------------------------------
# Each entry: (question_text, gold_source_id, mode)
# The gold_source_id must be a skill id present in the real library for the
# bench to score > 0 against the live catalog; when the library is empty or
# missing the skill, the bench degrades gracefully to 0.

COVERAGE_CASES: tuple[tuple[str, str, str], ...] = (
    # arXiv: academic preprint questions that exercise peer-reviewed authority
    (
        "What are the latest transformer architectures for natural language processing?",
        "arxiv",
        "investigate",
    ),
    (
        "Survey recent preprints on diffusion models for image synthesis",
        "arxiv",
        "survey",
    ),
    (
        "What causal mechanisms explain gradient vanishing in deep networks?",
        "arxiv",
        "investigate",
    ),
    # Wikipedia: orientation / lookup / definition questions
    (
        "Give me an encyclopedic overview of the French Revolution",
        "wikipedia",
        "ask",
    ),
    (
        "What is the definition and history of the Turing test?",
        "wikipedia",
        "ask",
    ),
    # general_web: current events / news / broad web questions
    (
        "What is happening with the latest AI regulation news?",
        "general_web",
        "watch",
    ),
    (
        "Find recent news articles about large language model deployments",
        "general_web",
        "investigate",
    ),
)

# Default top-k cutoff for recall and MRR computation.
_DEFAULT_K = 5


def run_source_coverage_bench(
    *,
    recommend: Callable | None = None,
    k: int = _DEFAULT_K,
) -> dict:
    """Run the source-coverage bench and return a metrics dict.

    Parameters
    ----------
    recommend:
        Callable with the same signature as
        ``lighthouse_ai.skills.recommender.recommend``.  When ``None`` the
        production recommender is imported at call time so callers never have
        a top-level import-time dependency.
    k:
        Top-k cutoff for recall and MRR.

    Returns
    -------
    dict with keys:
        ``recall_at_k``   — mean recall@k across all cases (float in [0, 1])
        ``mrr``           — mean reciprocal rank of gold source (float in [0, 1])
        ``k``             — the cutoff used
        ``n_cases``       — total cases evaluated
        ``n_scored``      — cases where gold source was in the library
        ``per_case``      — list of per-case dicts
        ``note``          — non-empty string if degraded (empty library, etc.)
    """
    if recommend is None:
        from ..skills.recommender import recommend as _default_recommend

        recommend = _default_recommend

    per_case: list[dict] = []
    recalls: list[float] = []
    rrs: list[float] = []
    notes: list[str] = []

    for question, gold_id, mode in COVERAGE_CASES:
        case_note = ""
        try:
            recs = recommend(question, mode)
        except Exception as exc:
            recs = []
            case_note = f"recommend raised {type(exc).__name__}: {exc}"

        ranked_ids = [r.skill_id for r in recs]

        if not ranked_ids:
            case_note = case_note or "empty recommendation list (library may be empty)"
            r_k = 0.0
            rr = 0.0
        elif gold_id not in ranked_ids and not any(
            gold_id == r.skill_id for r in recs
        ):
            case_note = case_note or f"gold skill '{gold_id}' not in recommendations"
            r_k = recall_at_k(ranked_ids, {gold_id}, k)
            rr = mrr(ranked_ids, {gold_id})
        else:
            r_k = recall_at_k(ranked_ids, {gold_id}, k)
            rr = mrr(ranked_ids, {gold_id})

        recalls.append(r_k)
        rrs.append(rr)
        if case_note:
            notes.append(case_note)

        per_case.append(
            {
                "question": question[:80],
                "gold_id": gold_id,
                "mode": mode,
                "recall_at_k": round(r_k, 4),
                "mrr": round(rr, 4),
                "ranked_ids": ranked_ids[:k],
                "note": case_note,
            }
        )

    mean_recall = mean_metric(recalls)
    mean_mrr = mean_metric(rrs)
    n_scored = sum(1 for c in per_case if c["note"] == "")

    return {
        "recall_at_k": round(mean_recall, 4),
        "mrr": round(mean_mrr, 4),
        "k": k,
        "n_cases": len(per_case),
        "n_scored": n_scored,
        "per_case": per_case,
        "note": "; ".join(notes) if notes else "",
    }
