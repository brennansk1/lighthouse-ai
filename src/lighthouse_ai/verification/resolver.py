"""Auto-resolver for calibration positions (Sprint 32).

Based on Halawi et al. (NeurIPS 2024, arXiv:2402.18563): retrieval-augmented
LM re-researches positions at their resolve_by deadline and auto-resolves
when confidence is high. Positions flagged human-only are skipped.

Resolution kinds:
  "machine"  — Yes/No outcome derivable from a programmatic source or LLM
  "human"    — subjective or long-horizon; requires human judgment
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..subconscious.overlap import GenerationGuard


@dataclass
class ResolutionResult:
    position_id: int
    claim: str
    outcome: bool | None           # None = deferred to human
    confidence: float              # 0.0-1.0
    rationale: str
    auto_resolved: bool
    brier: float | None = None


def is_past_deadline(resolve_by: str | None) -> bool:
    """True if the position's resolve_by date has passed."""
    if not resolve_by:
        return False
    try:
        due = datetime.fromisoformat(resolve_by)
        return datetime.now() >= due
    except Exception:
        return False


def classify_resolution_kind(claim: str) -> str:
    """Heuristic: is this claim machine-resolvable or human-only?

    Machine-resolvable: Yes/No questions with a named measurable outcome.
    Human-only: comparative, normative, vague, or very long-horizon claims.
    """
    lower = claim.lower()
    # Numeric / Yes-No signals
    machine_signals = ["will ", "does ", "did ", "is there ", "has ", "by 20",
                       "approved", "published", "released", "exceeded", "reached"]
    human_signals = ["should", "better", "worse", "best", "right", "ethical",
                     "eventually", "long run", "ultimately"]
    if any(s in lower for s in human_signals):
        return "human"
    if any(s in lower for s in machine_signals):
        return "machine"
    return "human"  # default conservative


def attempt_auto_resolve(
    position_id: int,
    claim: str,
    probability: float,
    *,
    gateway=None,
    confidence_threshold: float = 0.7,
) -> ResolutionResult:
    """Attempt to auto-resolve a position using the gateway.

    Returns a ResolutionResult with auto_resolved=False when:
    - gateway is None (offline mode)
    - claim is classified as human-only
    - LLM response cannot be parsed as a confident Yes/No
    """
    kind = classify_resolution_kind(claim)
    if kind == "human" or gateway is None:
        return ResolutionResult(
            position_id=position_id, claim=claim, outcome=None,
            confidence=0.0, rationale="human-only or no gateway",
            auto_resolved=False,
        )
    prompt = (
        f"Claim to resolve: {claim}\n\n"
        "Based on current knowledge, has this claim turned out to be TRUE or FALSE?\n"
        "Respond with ONLY one of:\n"
        "TRUE: <confidence 0.0-1.0> — <one-sentence rationale>\n"
        "FALSE: <confidence 0.0-1.0> — <one-sentence rationale>\n"
        "UNCERTAIN: — <one-sentence reason>\n"
    )
    try:
        resp = gateway.complete("aux_context", prompt)
        text = resp.text.strip()
        outcome, confidence, rationale = _parse_resolution(text)
        if outcome is None or confidence < confidence_threshold:
            return ResolutionResult(
                position_id=position_id, claim=claim, outcome=None,
                confidence=confidence or 0.0,
                rationale=rationale or "confidence below threshold",
                auto_resolved=False,
            )
        from .brier import brier_score
        brier = brier_score(probability, outcome)
        return ResolutionResult(
            position_id=position_id, claim=claim, outcome=outcome,
            confidence=confidence, rationale=rationale,
            auto_resolved=True, brier=brier,
        )
    except Exception as exc:
        return ResolutionResult(
            position_id=position_id, claim=claim, outcome=None,
            confidence=0.0, rationale=f"error: {exc!r}",
            auto_resolved=False,
        )


def _parse_resolution(text: str) -> tuple[bool | None, float, str]:
    """Parse LLM resolution response into (outcome, confidence, rationale).

    Accepts ``TRUE: 0.9 — rationale``, ``FALSE: 0.8 - reason`` and also the
    rationale-less ``TRUE: 0.9`` form (the dash and trailing text are optional,
    so a confident but terse answer is not silently dropped). The confidence
    must be a single valid float; a malformed number degrades to 0.5 rather than
    raising.
    """
    import re
    text = text.strip()
    # Number is anchored so "0.5.3" doesn't sneak through as 0.5; rationale opt.
    m = re.match(
        r"(TRUE|FALSE):\s*(\d+(?:\.\d+)?)\s*(?:[—\-]\s*(.+))?$",
        text, re.IGNORECASE | re.DOTALL,
    )
    if m:
        outcome = m.group(1).upper() == "TRUE"
        try:
            confidence = float(m.group(2))
        except ValueError:
            confidence = 0.5
        rationale = (m.group(3) or "").strip() or "(no rationale provided)"
        return outcome, min(max(confidence, 0.0), 1.0), rationale
    return None, 0.0, "could not parse response"


def run_resolver_pass(
    positions_db: Path,
    *,
    gateway=None,
    confidence_threshold: float = 0.7,
    dry_run: bool = False,
    guard: GenerationGuard | None = None,
) -> list[ResolutionResult]:
    """Run auto-resolution on all past-deadline positions.

    When dry_run=True, returns results without writing to the database.

    When a :class:`GenerationGuard` is supplied, this pass claims a generation
    and refuses to commit once a newer pass has started — so a slow resolver run
    colliding with the next scheduled one never double-writes outcomes (§4).
    """
    from ..persistence import open_db
    from .positions import _ensure_extras

    my_gen = guard.begin() if guard is not None else None

    _ensure_extras(positions_db)
    conn = open_db(positions_db)
    try:
        rows = conn.execute(
            "SELECT id, claim, confidence, resolve_by, outcome "
            "FROM positions WHERE outcome IS NULL"
        ).fetchall()
    finally:
        conn.close()

    results: list[ResolutionResult] = []
    for pos_id, claim, prob, resolve_by, outcome in rows:
        if outcome is not None:
            continue  # already resolved
        if not is_past_deadline(resolve_by):
            continue
        result = attempt_auto_resolve(
            pos_id, claim, float(prob or 0.75),
            gateway=gateway, confidence_threshold=confidence_threshold,
        )
        results.append(result)
        if result.auto_resolved and not dry_run:
            # A newer pass started while we were researching → discard our writes.
            if guard is not None and not guard.is_current(my_gen):
                break
            conn = open_db(positions_db)
            try:
                conn.execute(
                    "UPDATE positions SET outcome=?, brier=?, "
                    "resolved_at=datetime('now') WHERE id=?",
                    (1 if result.outcome else 0, result.brier, pos_id),
                )
            finally:
                conn.close()
    return results
