"""Real faithfulness gate — entailment/HHEM on a golden claim–grounding set.

Gated on:
  1. LIGHTHOUSE_REAL_BACKEND=1 (confirms real-backend environment)
  2. MiniCheck (``minicheck``) OR HHEM (``sentence_transformers``) importable.

Threshold (PRODUCTION_CHECKLIST.md §C):
  * Mean faithfulness score ≥ 0.80 on the 20-pair golden set.

The golden pairs are (claim, grounding) where the grounding *entails* the
claim — so a well-calibrated scorer should return ≥ 0.80 on average.
Contradicting pairs are excluded from the mean (the gate measures how well
the scorer agrees with known-good entailments, not how it handles adversarial
cases — that is the adversarial suite's job).

Run locally:
    LIGHTHOUSE_REAL_BACKEND=1 uv run python -m pytest tests/test_real_faithfulness.py -v
"""

from __future__ import annotations

import importlib.util
import os

import httpx
import pytest

# ---------------------------------------------------------------------------
# Shared skip guard
# ---------------------------------------------------------------------------


def _ollama_reachable() -> bool:
    try:
        with httpx.Client(timeout=2.0) as c:
            return c.get("http://127.0.0.1:11434/api/tags").status_code == 200
    except Exception:
        return False


_REAL_BACKEND_OK = (
    os.environ.get("LIGHTHOUSE_REAL_BACKEND") == "1"
    and _ollama_reachable()
)
_SKIP_REASON = (
    "set LIGHTHOUSE_REAL_BACKEND=1 and have ollama running on 127.0.0.1:11434"
)

_MINICHECK_AVAILABLE = importlib.util.find_spec("minicheck") is not None
_HHEM_AVAILABLE = importlib.util.find_spec("sentence_transformers") is not None
_ENTAILMENT_MODEL_AVAILABLE = _MINICHECK_AVAILABLE or _HHEM_AVAILABLE

pytestmark = pytest.mark.skipif(
    not (_REAL_BACKEND_OK and _ENTAILMENT_MODEL_AVAILABLE),
    reason=(
        "requires LIGHTHOUSE_REAL_BACKEND=1 + (minicheck OR sentence_transformers) "
        "installed — see docs/PRODUCTION_CHECKLIST.md §C"
    ),
)

# ---------------------------------------------------------------------------
# Threshold
# ---------------------------------------------------------------------------

_FAITHFULNESS_THRESHOLD = 0.80  # ≥ 0.80 mean score on the 20-pair golden set

# ---------------------------------------------------------------------------
# 20-pair golden set (claim, grounding)
# Each pair: grounding fully entails the claim → scorer should return ≈ 1.0.
# Pairs are drawn from factual, non-ambiguous scientific/historical statements
# so the entailment signal is unambiguous regardless of scorer.
# ---------------------------------------------------------------------------

_GOLDEN_PAIRS: tuple[tuple[str, str], ...] = (
    # --- physics / astronomy ---
    (
        "Water is composed of two hydrogen atoms and one oxygen atom.",
        "H2O is the chemical formula for water, meaning each molecule "
        "contains two hydrogen atoms bonded to one oxygen atom.",
    ),
    (
        "The Earth orbits the Sun.",
        "Earth is the third planet from the Sun and completes one orbit "
        "around it approximately every 365.25 days.",
    ),
    (
        "Light travels at approximately 300,000 kilometres per second in a vacuum.",
        "The speed of light in a vacuum is defined as 299,792,458 metres per "
        "second, often approximated as 300,000 km/s.",
    ),
    (
        "DNA carries genetic information in living organisms.",
        "Deoxyribonucleic acid (DNA) is the molecule that carries the genetic "
        "instructions used in the growth, development, and functioning of all "
        "known living organisms.",
    ),
    (
        "Photosynthesis converts sunlight, water, and carbon dioxide into glucose.",
        "In photosynthesis, plants use energy from sunlight to convert carbon "
        "dioxide and water into glucose and oxygen.",
    ),
    # --- computing / AI ---
    (
        "The transformer architecture uses self-attention mechanisms.",
        "The transformer model, introduced in 'Attention Is All You Need' "
        "(Vaswani et al., 2017), relies on self-attention to process input "
        "sequences without recurrence.",
    ),
    (
        "Python is an interpreted, high-level programming language.",
        "Python is a high-level, general-purpose programming language. "
        "Its design philosophy emphasises code readability. It is interpreted, "
        "meaning code is executed line by line at runtime.",
    ),
    (
        "Backpropagation is used to train neural networks.",
        "Neural networks are trained using backpropagation, an algorithm that "
        "computes the gradient of the loss function with respect to each weight "
        "and uses it to update the weights via gradient descent.",
    ),
    (
        "GPT models are based on the transformer decoder architecture.",
        "Generative Pre-trained Transformers (GPT) are language models built "
        "on the decoder portion of the original transformer architecture.",
    ),
    (
        "Turing proposed the imitation game as a test of machine intelligence.",
        "In 1950, Alan Turing proposed the imitation game — now called the "
        "Turing test — as a way to evaluate whether a machine could exhibit "
        "intelligent behaviour indistinguishable from that of a human.",
    ),
    # --- biology / medicine ---
    (
        "Penicillin was the first widely used antibiotic.",
        "Alexander Fleming discovered penicillin in 1928, and it became the "
        "first widely used antibiotic, revolutionising the treatment of "
        "bacterial infections.",
    ),
    (
        "Vaccines work by training the immune system to recognise pathogens.",
        "Vaccines introduce a weakened or inactivated form of a pathogen, or "
        "its antigen, to the immune system so that it can learn to recognise "
        "and fight the real pathogen if encountered later.",
    ),
    (
        "The human genome contains approximately 3 billion base pairs.",
        "The human genome is composed of approximately 3.2 billion base pairs "
        "of DNA distributed across 23 pairs of chromosomes.",
    ),
    (
        "mRNA vaccines encode instructions for producing a target antigen.",
        "mRNA vaccines deliver messenger RNA into cells, which then use the "
        "instructions to produce a target antigen — for example, the spike "
        "protein of SARS-CoV-2 — triggering an immune response.",
    ),
    (
        "CRISPR-Cas9 allows precise editing of DNA sequences.",
        "CRISPR-Cas9 is a molecular tool that uses a guide RNA to direct the "
        "Cas9 enzyme to a specific location in the genome, where it makes a "
        "precise cut, enabling targeted editing of DNA sequences.",
    ),
    # --- economics / social science ---
    (
        "Inflation measures the rate at which the general price level rises.",
        "Inflation is defined as the rate of increase in the general price "
        "level of goods and services over a period, typically measured by the "
        "Consumer Price Index (CPI).",
    ),
    (
        "GDP measures the total monetary value of goods and services produced in a country.",
        "Gross Domestic Product (GDP) is the total monetary or market value "
        "of all finished goods and services produced within a country's borders "
        "in a specific time period.",
    ),
    (
        "Supply and demand determine market prices.",
        "In a free market, the interaction of supply (the quantity sellers are "
        "willing to offer) and demand (the quantity buyers wish to purchase) "
        "determines the equilibrium price of a good or service.",
    ),
    # --- history ---
    (
        "World War II ended in 1945.",
        "World War II concluded in 1945, with Germany surrendering on "
        "8 May 1945 (V-E Day) and Japan surrendering on 15 August 1945 "
        "(V-J Day) following the atomic bombings of Hiroshima and Nagasaki.",
    ),
    (
        "The internet was developed from the ARPANET project.",
        "The modern internet evolved from ARPANET, a research network funded "
        "by the US Department of Defense's Advanced Research Projects Agency "
        "(ARPA) in the late 1960s.",
    ),
)

assert len(_GOLDEN_PAIRS) == 20, "Golden set must contain exactly 20 pairs"


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_faithfulness_golden_set_mean_score() -> None:
    """Mean entailment score on 20 golden (claim, grounding) pairs ≥ 0.80."""
    from lighthouse_ai.verification.entailment import available, score_claim

    if not available():
        pytest.skip(
            "entailment.available() returned False — "
            "install minicheck or sentence_transformers"
        )

    scores: list[float] = []
    for claim, grounding in _GOLDEN_PAIRS:
        s = score_claim(claim, grounding)
        scores.append(s)

    mean_score = sum(scores) / len(scores)
    min_score = min(scores)
    max_score = max(scores)

    print(
        f"\n[faithfulness] mean={mean_score:.3f}  "
        f"min={min_score:.3f}  max={max_score:.3f}  "
        f"n={len(scores)}  threshold={_FAITHFULNESS_THRESHOLD}"
    )

    # Surface per-pair failures to aid diagnosis.
    low_pairs = [
        (i + 1, s, _GOLDEN_PAIRS[i][0][:60])
        for i, s in enumerate(scores)
        if s < _FAITHFULNESS_THRESHOLD
    ]
    if low_pairs:
        detail = "; ".join(f"pair {n}: score={s:.3f} '{c}...'" for n, s, c in low_pairs)
        print(f"  Low-scoring pairs: {detail}")

    assert mean_score >= _FAITHFULNESS_THRESHOLD, (
        f"Mean faithfulness {mean_score:.3f} < threshold {_FAITHFULNESS_THRESHOLD}. "
        f"min={min_score:.3f}, max={max_score:.3f}. "
        f"Low pairs: {low_pairs}"
    )


@pytest.mark.slow
def test_faithfulness_scorer_available() -> None:
    """Sanity check: at least one faithfulness scorer is importable."""
    from lighthouse_ai.verification.entailment import available

    assert available(), (
        "entailment.available() returned False even though the test was not "
        "skipped — MiniCheck and sentence_transformers both seem unavailable."
    )
