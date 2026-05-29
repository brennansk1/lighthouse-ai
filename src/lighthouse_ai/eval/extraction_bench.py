"""Extraction bench — measures token-F1 / ROUGE-L-ish overlap of
``lighthouse_ai.ingest.extract_text`` against a hand-built golden set of
(payload, expected_main_text) cases.

Design notes
------------
* Pure stdlib + ingest path; no network, no LLM.
* The scoring proxy is token-F1 (precision * recall harmonic mean over the
  content-token bags), which is the same spirit as ROUGE-L but without a
  sequence-alignment requirement, making it trivially deterministic.
* ``trafilatura`` is optional: when present it silently improves scores
  (boilerplate removal); when absent the stdlib regex path is measured.
  Either way the bench reports which extractor was active.
* The HTML corpus contains deliberate nav/footer noise so the boilerplate-
  removal path is actually exercised.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

__all__ = ["EXTRACTION_CASES", "run_extraction_bench"]

# ---------------------------------------------------------------------------
# Token utilities (mirroring metrics.py _claim_tokens logic)
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")
_STOP = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on",
        "at", "by", "for", "with", "as", "is", "are", "was", "were", "it",
        "its", "this", "that", "from", "into", "be", "been", "has", "have",
        "had", "not", "so",
    }
)


def _tokens(text: str) -> list[str]:
    return [
        t
        for t in (m.lower() for m in _TOKEN_RE.findall(text))
        if t not in _STOP
    ]


def _token_f1(hypothesis: str, reference: str) -> float:
    """Token-bag F1 between hypothesis and reference; 1.0 when reference empty."""
    ref_toks = _tokens(reference)
    hyp_toks = _tokens(hypothesis)
    if not ref_toks:
        return 1.0
    if not hyp_toks:
        return 0.0
    ref_bag: dict[str, int] = {}
    for t in ref_toks:
        ref_bag[t] = ref_bag.get(t, 0) + 1
    hyp_bag: dict[str, int] = {}
    for t in hyp_toks:
        hyp_bag[t] = hyp_bag.get(t, 0) + 1
    overlap = sum(min(hyp_bag.get(t, 0), cnt) for t, cnt in ref_bag.items())
    precision = overlap / len(hyp_toks) if hyp_toks else 0.0
    recall = overlap / len(ref_toks) if ref_toks else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


# ---------------------------------------------------------------------------
# Golden extraction cases
# ---------------------------------------------------------------------------
# Each case is (payload_bytes, content_type, filename, expected_main_text).
# The expected text is the *core prose* — scoring allows for wrapper noise.
# Payloads are deliberately crafted to have boilerplate (nav/footer) mixed in.
_PLAIN_PAYLOAD = b"Photovoltaic cells convert sunlight into direct current electricity."
_PLAIN_EXPECTED = "Photovoltaic cells convert sunlight into direct current electricity."

_HTML_PAYLOAD = b"""<!DOCTYPE html>
<html>
<head><title>Solar Energy</title></head>
<body>
<nav>Home | About | Contact</nav>
<header>MySite</header>
<main>
<h1>How Solar Panels Work</h1>
<p>Silicon semiconductor cells absorb photons and release electrons,
producing direct current. An inverter converts it to alternating current
for grid distribution.</p>
</main>
<footer>Copyright 2024 MySite. All rights reserved. Privacy Policy.</footer>
<script>console.log("analytics");</script>
</body>
</html>
"""
_HTML_EXPECTED = (
    "Silicon semiconductor cells absorb photons and release electrons "
    "producing direct current An inverter converts it to alternating current "
    "for grid distribution"
)

_HTML_ENTITIES_PAYLOAD = b"""<html><body>
<p>The researcher noted that CO&lt;sub&gt;2&lt;/sub&gt; levels exceed
400 ppm. Results confirm &gt;90% accuracy on the benchmark dataset.</p>
<aside>Advertisement: Buy cheap supplements!</aside>
</body></html>
"""
_HTML_ENTITIES_EXPECTED = "CO2 levels exceed 400 ppm Results confirm accuracy benchmark dataset"

_PLAIN_MULTILINE_PAYLOAD = (
    b"Introduction\n\n"
    b"Neural networks learn hierarchical representations from data.\n"
    b"Deep learning models require large corpora for training.\n\n"
    b"Methods\n\nWe evaluated three architectures on ImageNet."
)
_PLAIN_MULTILINE_EXPECTED = (
    "Neural networks learn hierarchical representations from data "
    "Deep learning models require large corpora for training "
    "evaluated three architectures on ImageNet"
)

# Each tuple: (payload, content_type, filename, expected_text)
EXTRACTION_CASES: tuple[
    tuple[bytes, str | None, str | None, str], ...
] = (
    (_PLAIN_PAYLOAD, "text/plain", "solar.txt", _PLAIN_EXPECTED),
    (_HTML_PAYLOAD, "text/html", "solar.html", _HTML_EXPECTED),
    (_HTML_ENTITIES_PAYLOAD, "text/html", "entities.html", _HTML_ENTITIES_EXPECTED),
    (_PLAIN_MULTILINE_PAYLOAD, "text/plain", "ml.txt", _PLAIN_MULTILINE_EXPECTED),
)


# ---------------------------------------------------------------------------
# Run bench
# ---------------------------------------------------------------------------
def run_extraction_bench(
    cases: Sequence[tuple[bytes, str | None, str | None, str]] | None = None,
) -> dict:
    """Run the extraction bench and return a metrics dict.

    Returns
    -------
    dict with keys:
        ``mean_f1``   — mean token-F1 across all cases (float in [0, 1])
        ``per_case``  — list of per-case dicts (payload_id, f1, extractor)
        ``extractor`` — "trafilatura" or "stdlib" (the active HTML extractor)
        ``n_cases``   — number of cases evaluated
    """
    from ..ingest import extract_text

    try:
        import trafilatura  # type: ignore  # noqa: F401
        active_extractor = "trafilatura"
    except ImportError:
        active_extractor = "stdlib"

    active_cases = list(cases) if cases is not None else list(EXTRACTION_CASES)

    per_case: list[dict] = []
    for i, (payload, content_type, filename, expected) in enumerate(active_cases):
        extracted = extract_text(payload, content_type, filename)
        f1 = _token_f1(extracted, expected)
        per_case.append(
            {
                "case_id": f"case_{i}",
                "filename": filename,
                "f1": round(f1, 4),
                "extractor": active_extractor,
                "hypothesis_len": len(extracted),
                "reference_len": len(expected),
            }
        )

    mean_f1 = sum(c["f1"] for c in per_case) / len(per_case) if per_case else 0.0
    return {
        "mean_f1": round(mean_f1, 4),
        "per_case": per_case,
        "extractor": active_extractor,
        "n_cases": len(per_case),
    }
