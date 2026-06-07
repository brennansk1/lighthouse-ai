"""Evaluate the legal/compliance starter gold set (Sprint E measurement harness).

Two passes over ``eval/data/legal_gold.json``:

  1. Retrieval — always runs, offline and deterministic. Loads the labelled set
     with ``load_golden_from_json``, indexes it through the real ``HybridSearch``
     pipeline (test-tier HashEmbedder + BM25 + ScoreReranker by default), and
     reports precision@k / recall@k / MRR via ``golden.evaluate``.

  2. Faithfulness — gated behind ``LIGHTHOUSE_REAL_BACKEND=1`` AND a real
     entailment scorer (MiniCheck) being importable. It scores each
     contradiction case's claim against its supporting and contradicting
     passage. The headline: a real entailment scorer rates the *contradicting*
     passage below threshold, catching a refutation that the deleted lexical
     cosine path (high word overlap between claim and contradiction) would have
     waved through. Offline, this pass is SKIPPED with a clear message rather
     than fabricating a result.

Usage:
    uv run python scripts/eval_legal.py                            # retrieval only
    LIGHTHOUSE_REAL_BACKEND=1 uv run python scripts/eval_legal.py  # + faithfulness

No real network calls and no model load happen unless ``LIGHTHOUSE_REAL_BACKEND``
is set and MiniCheck is installed; the retrieval pass is a pure offline harness.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from lighthouse_ai.eval.golden import build_index, evaluate, load_golden_from_json

#: The starter gold set ships inside the package so the script needs no args.
GOLD_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "lighthouse_ai"
    / "eval"
    / "data"
    / "legal_gold.json"
)


def run_retrieval(gold_path: Path = GOLD_PATH, *, k: int = 5) -> dict:
    """Load the gold set and return its aggregate retrieval metrics.

    Deterministic and offline: the default pipeline is the lexical test-tier
    stack, so the same set produces the same numbers on every run. The metrics
    are smoke-grade (the corpus is a starter scaffold), not a production bar.
    """
    golden = load_golden_from_json(gold_path)
    hybrid = build_index(golden)
    metrics = evaluate(hybrid, golden, k=k)
    return {
        "documents": len(golden.documents),
        "queries": len(golden.cases),
        "contradictions": len(golden.contradictions),
        "k": k,
        "metrics": metrics,
    }


def run_faithfulness(gold_path: Path = GOLD_PATH) -> dict:
    """Score the contradiction subset with the real entailment scorer.

    Gated by the caller (see :func:`main`): this only runs when
    ``LIGHTHOUSE_REAL_BACKEND=1`` AND a real scorer is importable. For each case
    it scores the claim against the supporting passage (expected high) and the
    contradicting passage (expected below threshold). A case "passes" when the
    scorer separates the two — i.e. the contradiction is caught, which the
    deleted lexical-overlap shortcut could not do.
    """
    from lighthouse_ai.verification import entailment

    golden = load_golden_from_json(gold_path)
    threshold = entailment.MINICHECK_THRESHOLD
    cases: list[dict] = []
    caught = 0
    for c in golden.contradictions:
        support = entailment.score_claim(c.claim, c.supporting_passage)
        contradict = entailment.score_claim(c.claim, c.contradicting_passage)
        # A real scorer flags the contradiction (below threshold) while keeping
        # the supporting passage above it. None ("unchecked") never counts as a
        # catch — an absent scorer must not fabricate a pass.
        is_caught = (
            support is not None
            and contradict is not None
            and contradict < threshold
            and support >= threshold
        )
        caught += int(is_caught)
        cases.append(
            {
                "id": c.id,
                "support_score": support,
                "contradict_score": contradict,
                "contradiction_caught": is_caught,
            }
        )
    return {
        "threshold": threshold,
        "total": len(golden.contradictions),
        "contradictions_caught": caught,
        "cases": cases,
    }


def main() -> int:
    """Run the retrieval pass always; the faithfulness pass only when gated."""
    report: dict = {"retrieval": run_retrieval()}

    real = os.environ.get("LIGHTHOUSE_REAL_BACKEND") == "1"
    if not real:
        report["faithfulness"] = {
            "skipped": True,
            "reason": "LIGHTHOUSE_REAL_BACKEND != 1 — faithfulness pass needs a "
            "real entailment scorer; running retrieval only (offline).",
        }
        print(json.dumps(report, indent=2))
        return 0

    # Gated path: still refuse to fabricate a result if no real scorer is present.
    from lighthouse_ai.verification import entailment

    if not entailment.available():
        report["faithfulness"] = {
            "skipped": True,
            "reason": "LIGHTHOUSE_REAL_BACKEND=1 but no real entailment scorer "
            "(MiniCheck) is importable — install it to run the faithfulness pass.",
        }
        print(json.dumps(report, indent=2))
        return 0

    report["faithfulness"] = run_faithfulness()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
