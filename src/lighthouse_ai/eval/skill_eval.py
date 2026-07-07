"""Per-skill eval module — recall@k + Brier calibration.

This module provides two entry points:

  ``run_skill_eval(*, recommend=None, skills=None) -> dict``
      Runs a small in-code held-out (question → expected skill) set against
      the recommender and returns per-skill recall@k.  Fully offline-
      deterministic: uses token-overlap similarity (no embedder, no gateway).
      Tolerates an empty skill library — each case scores 0, no crash.

  ``per_skill_calibration(positions_db) -> dict``
      Reads resolved calibration positions from ``positions_db`` (a
      ``pathlib.Path``), groups them by ``skill_id`` metadata, and computes
      per-skill mean Brier score using :func:`verification.brier.mean_brier`.
      Returns an empty ``{}`` when the db is absent or has no resolved rows.

Design constraints:
  * No datetime.now() at import time.
  * No network, no real LLM.
  * Both functions are safe to call when the skill library is empty or the
    positions database does not exist.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from .metrics import mean_metric, recall_at_k

__all__ = [
    "SKILL_EVAL_CASES",
    "per_skill_calibration",
    "run_skill_eval",
]

# ---------------------------------------------------------------------------
# Held-out golden set: (question, mode, expected_skill_id)
# ---------------------------------------------------------------------------
# These are kept small and in-code so the eval runs fully offline in < 1 s.
# Each expected_skill_id must match a key in the production skill library;
# when the library is absent or the skill is missing the case scores 0.

SKILL_EVAL_CASES: tuple[tuple[str, str, str], ...] = (
    # --- news_orchestrator ---
    (
        "What news outlets cover the US election campaign?",
        "investigate",
        "news_orchestrator",
    ),
    (
        "Compare news coverage across Reuters and BBC on climate change",
        "adjudicate",
        "news_orchestrator",
    ),
    (
        "Monitor breaking news from wire services",
        "watch",
        "news_orchestrator",
    ),
    # --- reuters ---
    (
        "Find Reuters wire articles about the Federal Reserve rate decision",
        "investigate",
        "reuters",
    ),
    # --- associated_press ---
    (
        "Get Associated Press articles about the US budget negotiations",
        "investigate",
        "associated_press",
    ),
    # --- bbc_news ---
    (
        "Find BBC news articles about the UK general election",
        "investigate",
        "bbc_news",
    ),
    # --- guardian ---
    (
        "The Guardian investigative reporting on corporate tax avoidance",
        "investigate",
        "guardian",
    ),
    # --- propublica ---
    (
        "ProPublica investigative journalism on healthcare pricing",
        "investigate",
        "propublica",
    ),
    # --- arxiv ---
    (
        "Recent arXiv preprints on large language models",
        "survey",
        "arxiv",
    ),
    # --- wikipedia ---
    (
        "Encyclopedic overview of quantum entanglement",
        "ask",
        "wikipedia",
    ),
    # --- general_web ---
    (
        "Search the web for recent news about semiconductor chip shortages",
        "watch",
        "general_web",
    ),
    # --- clinicaltrials ---
    (
        "Search clinical trials for mRNA vaccine studies",
        "investigate",
        "clinicaltrials",
    ),
    # --- fred ---
    (
        "FRED economic data series for US unemployment rate",
        "investigate",
        "fred",
    ),
    # --- github ---
    (
        "GitHub repository releases for the Rust programming language",
        "watch",
        "github",
    ),
    # --- sec_edgar ---
    (
        "SEC EDGAR 10-K filings for Apple Inc risk factors",
        "investigate",
        "sec_edgar",
    ),
)

_DEFAULT_K = 5


def run_skill_eval(
    *,
    recommend: Callable | None = None,
    skills=None,
    k: int = _DEFAULT_K,
) -> dict:
    """Run the per-skill recall@k evaluation.

    Parameters
    ----------
    recommend:
        Callable with the same signature as
        ``lighthouse_ai.skills.recommender.recommend``.  When ``None``, the
        production recommender is imported at call time — no import at module
        level.
    skills:
        Optional explicit skill manifests to pass to ``recommend`` (useful in
        tests to provide a fake library without touching disk).
    k:
        Top-k cutoff for recall.

    Returns
    -------
    dict with keys:
        ``per_skill``     — ``{skill_id: {"recall_at_k": float, "n_cases": int,
                            "n_hits": int}}`` for every skill that appears as a
                            gold target in :data:`SKILL_EVAL_CASES`.
        ``macro_recall``  — mean recall@k across all cases (float in [0, 1]).
        ``k``             — the cutoff used.
        ``n_cases``       — total cases evaluated.
        ``n_scored``      — cases where recommend returned ≥ 1 result.
        ``per_case``      — list of per-case dicts (matches source_coverage_bench
                            style).
        ``note``          — non-empty string on degraded / empty library.
    """
    if recommend is None:
        from ..skills.recommender import recommend as _default_recommend  # type: ignore[assignment]

        recommend = _default_recommend

    per_case: list[dict] = []
    recalls: list[float] = []
    notes: list[str] = []

    # Accumulate per-skill counts so we can report per-skill recall.
    skill_hits: dict[str, int] = {}
    skill_cases: dict[str, int] = {}

    for question, mode, gold_id in SKILL_EVAL_CASES:
        skill_cases[gold_id] = skill_cases.get(gold_id, 0) + 1
        skill_hits.setdefault(gold_id, 0)

        case_note = ""
        try:
            if skills is not None:
                recs = recommend(question, mode, skills=skills)
            else:
                recs = recommend(question, mode)
        except Exception as exc:
            recs = []
            case_note = f"recommend raised {type(exc).__name__}: {exc}"

        ranked_ids = [r.skill_id for r in recs]

        if not ranked_ids:
            case_note = case_note or "empty recommendation list (library may be empty)"
            r_k = 0.0
        else:
            r_k = recall_at_k(ranked_ids, {gold_id}, k)
            if r_k > 0:
                skill_hits[gold_id] = skill_hits.get(gold_id, 0) + 1

        recalls.append(r_k)
        if case_note:
            notes.append(case_note)

        per_case.append(
            {
                "question": question[:80],
                "mode": mode,
                "gold_id": gold_id,
                "recall_at_k": round(r_k, 4),
                "ranked_ids": ranked_ids[:k],
                "note": case_note,
            }
        )

    # Build per-skill summary.
    per_skill: dict[str, dict] = {}
    for skill_id, n_cases in skill_cases.items():
        hits = skill_hits.get(skill_id, 0)
        per_skill[skill_id] = {
            "recall_at_k": round(hits / n_cases, 4) if n_cases > 0 else 0.0,
            "n_cases": n_cases,
            "n_hits": hits,
        }

    macro_recall = mean_metric(recalls)
    n_scored = sum(1 for c in per_case if c["note"] == "")

    return {
        "per_skill": per_skill,
        "macro_recall": round(macro_recall, 4),
        "k": k,
        "n_cases": len(per_case),
        "n_scored": n_scored,
        "per_case": per_case,
        "note": "; ".join(notes) if notes else "",
    }


def per_skill_calibration(positions_db: Path) -> dict:
    """Compute per-skill mean Brier score from resolved calibration positions.

    Reads the ``positions`` table from ``positions_db``, groups rows by
    ``skill_id`` extracted from the ``metadata_json`` column (or the
    ``metadata`` column — tolerates both schema variants), and computes mean
    Brier using :func:`verification.brier.mean_brier`.

    Parameters
    ----------
    positions_db:
        Path to ``positions.db``.  If absent (or empty), returns ``{}``.

    Returns
    -------
    dict
        ``{skill_id: {"mean_brier": float, "n_resolved": int}}`` for every
        skill_id that appears in at least one resolved position.  Returns
        ``{}`` on any error or when no resolved positions exist.

    Notes
    -----
    * Fully offline — reads SQLite directly, no network.
    * Gracefully returns ``{}`` if the table does not exist, the file is
      absent, or no rows have ``outcome IS NOT NULL``.
    """
    from ..verification.brier import mean_brier

    if not positions_db.exists():
        return {}

    try:
        import sqlite3

        conn = sqlite3.connect(str(positions_db))
        try:
            rows = conn.execute(
                "SELECT confidence, outcome, metadata_json FROM positions WHERE outcome IS NOT NULL"
            ).fetchall()
        except Exception:
            # Try alternate column name used in older schema variants.
            try:
                rows = conn.execute(
                    "SELECT confidence, outcome, metadata FROM positions WHERE outcome IS NOT NULL"
                ).fetchall()
            except Exception:
                return {}
        finally:
            conn.close()
    except Exception:
        return {}

    if not rows:
        return {}

    # Group by skill_id.
    by_skill: dict[str, list[tuple[float, bool]]] = {}
    for confidence, outcome, meta_json in rows:
        skill_id = _extract_skill_id(meta_json)
        if skill_id is None:
            continue
        try:
            prob = float(confidence)
            resolved = bool(outcome)
        except (TypeError, ValueError):
            continue
        by_skill.setdefault(skill_id, []).append((prob, resolved))

    result: dict = {}
    for skill_id, pairs in by_skill.items():
        result[skill_id] = {
            "mean_brier": round(mean_brier(pairs), 4),
            "n_resolved": len(pairs),
        }
    return result


def _extract_skill_id(meta_json: str | bytes | None) -> str | None:
    """Pull ``skill_id`` from a JSON metadata blob; return ``None`` on failure."""
    if not meta_json:
        return None
    try:
        data = json.loads(meta_json)
        sid = data.get("skill_id")
        return str(sid) if sid else None
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None
