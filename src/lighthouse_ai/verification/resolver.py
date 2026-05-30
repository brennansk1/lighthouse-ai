"""Auto-resolver for calibration positions (Sprint 32).

Based on Halawi et al. (NeurIPS 2024, arXiv:2402.18563): retrieval-augmented
LM re-researches positions at their resolve_by deadline and auto-resolves
when confidence is high. Positions flagged human-only are skipped.

Resolution kinds:
  "machine"  — Yes/No outcome derivable from a programmatic source or LLM
  "human"    — subjective or long-horizon; requires human judgment
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..subconscious.overlap import GenerationGuard

# An evidence retriever re-researches a claim+criterion as of a cutoff date and
# returns ``(evidence_text, source_id)`` — or None when no grounded evidence is
# available (offline, or nothing found). The resolver resolves ONLY from this
# evidence; with no evidence it defers to a human rather than guess from the
# model's own memory (the self-grading circularity the improvement memo flags).
EvidenceRetriever = Callable[[str, "str | None", str], "tuple[str, str] | None"]

# Legacy injected-research seam used by ``resolve_positions`` + its tests: takes
# ``(claim, criterion)`` and returns ``(outcome, confidence, rationale)``. Kept so
# deterministic tests can inject a fake; the LIVE path is ``run_resolver_pass``
# (evidence-grounded-or-defer), which the supervisor now uses.
ResearchFn = Callable[[str, "str | None"], "tuple[bool | None, float, str]"]


@dataclass
class ResolutionResult:
    position_id: int
    claim: str
    outcome: bool | None           # None = deferred to human
    confidence: float              # resolver's confidence in the verdict, 0.0-1.0
    rationale: str
    auto_resolved: bool
    brier: float | None = None
    resolver_kind: str = "deferred"     # machine_retrieval | human | deferred
    evidence_snapshot: str | None = None
    resolution_source: str | None = None
    resolved_via: str | None = None     # 'retrieval' | None
    defer_reason: str | None = None


def is_past_deadline(resolve_by: str | None, *, now: datetime | None = None) -> bool:
    """True if the position's resolve_by date has passed.

    ``now`` is injectable so deadline checks are deterministic in tests;
    ``datetime.now()`` is only ever called inside the function body.
    """
    if not resolve_by:
        return False
    try:
        due = datetime.fromisoformat(resolve_by)
        ref = now if now is not None else datetime.now()
        # tz-robust comparison: a naive and an aware datetime cannot be compared
        # (TypeError). Normalize both sides — treat any naive value as UTC — so
        # an aware ``resolve_by`` (e.g. "...+00:00") resolves instead of being
        # silently swallowed by the except below and NEVER resolving.
        if due.tzinfo is None and ref.tzinfo is not None:
            due = due.replace(tzinfo=UTC)
        elif due.tzinfo is not None and ref.tzinfo is None:
            ref = ref.replace(tzinfo=UTC)
        return ref >= due
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
    criterion: str | None = None,
    retriever: EvidenceRetriever | None = None,
    gateway=None,
    confidence_threshold: float = 0.7,
    resolve_by: str | None = None,
) -> ResolutionResult:
    """Resolve a position **from retrieved evidence**, or defer it to a human.

    The improvement memo's #1 fix: the resolver must NEVER grade a claim from the
    model's own parametric memory (self-preference bias inflates apparent
    calibration). Instead it retrieves fresh evidence (under a causal cutoff =
    ``resolve_by``) and decides only from that evidence; when there is no
    machine-checkable criterion, the claim is subjective/long-horizon, no evidence
    can be gathered (offline / nothing found), or the verdict is uncertain/low
    confidence, it **defers** (``outcome=None``) so a person decides.
    """
    def defer(reason: str, kind: str = "deferred") -> ResolutionResult:
        return ResolutionResult(
            position_id=position_id, claim=claim, outcome=None, confidence=0.0,
            rationale=reason, auto_resolved=False, resolver_kind=kind,
            defer_reason=reason)

    if not criterion:
        return defer("no machine-checkable criterion — needs a human", kind="human")
    if classify_resolution_kind(claim) == "human":
        return defer("subjective or long-horizon claim — needs a human", kind="human")
    # Never resolve from parametric memory: with no way to fetch evidence, defer.
    if gateway is None or retriever is None:
        return defer("no evidence source available (offline)")
    try:
        evidence = retriever(claim, criterion, resolve_by or "")
    except Exception as exc:  # pragma: no cover - defensive
        return defer(f"evidence retrieval failed: {exc!r}")
    if not evidence or not (evidence[0] or "").strip():
        return defer("no grounded evidence found by the deadline")
    evidence_text, source_id = evidence
    prompt = (
        "You are resolving a past prediction using ONLY the evidence provided "
        "below. Do not use any prior knowledge of your own.\n\n"
        f"Claim: {claim}\n"
        f"Resolution criterion (what makes it TRUE or FALSE): {criterion}\n\n"
        f"Evidence (as of {resolve_by or 'the deadline'}):\n{evidence_text[:4000]}\n\n"
        "Per the criterion and ONLY this evidence, did the claim turn out TRUE or "
        "FALSE? If the evidence does not clearly decide it, answer UNCERTAIN.\n"
        "Respond with ONLY one of:\n"
        "TRUE: <confidence 0.0-1.0> — <one-sentence rationale citing the evidence>\n"
        "FALSE: <confidence 0.0-1.0> — <one-sentence rationale citing the evidence>\n"
        "UNCERTAIN: — <one-sentence reason>\n"
    )
    try:
        resp = gateway.complete("aux_context", prompt)
        outcome, confidence, rationale = _parse_resolution(resp.text.strip())
    except Exception as exc:  # pragma: no cover - defensive
        return defer(f"resolver error: {exc!r}")
    if outcome is None or confidence < confidence_threshold:
        return defer(rationale or "evidence inconclusive / low resolver confidence")
    from .brier import brier_score
    brier = brier_score(probability, outcome)
    return ResolutionResult(
        position_id=position_id, claim=claim, outcome=outcome,
        confidence=confidence, rationale=rationale, auto_resolved=True, brier=brier,
        resolver_kind="machine_retrieval", evidence_snapshot=evidence_text[:2000],
        resolution_source=source_id, resolved_via="retrieval")


def _parse_resolution(text: str) -> tuple[bool | None, float, str]:
    """Parse LLM resolution response into (outcome, confidence, rationale)."""
    import re
    text = text.strip()
    m = re.match(r"(TRUE|FALSE):\s*([\d.]+)\s*[—\-]\s*(.+)", text, re.IGNORECASE)
    if m:
        outcome = m.group(1).upper() == "TRUE"
        try:
            confidence = float(m.group(2))
        except ValueError:
            confidence = 0.5
        rationale = m.group(3).strip()
        return outcome, min(max(confidence, 0.0), 1.0), rationale
    return None, 0.0, "could not parse response"


def run_resolver_pass(
    positions_db: Path,
    *,
    gateway=None,
    retriever: EvidenceRetriever | None = None,
    confidence_threshold: float = 0.7,
    dry_run: bool = False,
    guard: GenerationGuard | None = None,
) -> list[ResolutionResult]:
    """Run evidence-grounded resolution on all past-deadline positions.

    Each past-deadline position is resolved from retrieved evidence or **deferred
    to the human-resolution queue** (no criterion / human / no evidence /
    uncertain). When dry_run=True, returns results without writing.

    When a :class:`GenerationGuard` is supplied, this pass claims a generation
    and refuses to commit once a newer pass has started — so a slow resolver run
    colliding with the next scheduled one never double-writes outcomes (§4).
    """
    from ..persistence import open_db
    from .positions import _ensure_extras, enqueue_human_resolution

    my_gen = guard.begin() if guard is not None else None

    _ensure_extras(positions_db)
    conn = open_db(positions_db)
    try:
        rows = conn.execute(
            "SELECT id, claim, confidence, resolve_by, outcome, resolution_criterion "
            "FROM positions WHERE outcome IS NULL"
        ).fetchall()
    finally:
        conn.close()

    results: list[ResolutionResult] = []
    for pos_id, claim, prob, resolve_by, outcome, criterion in rows:
        if outcome is not None:
            continue  # already resolved
        if not is_past_deadline(resolve_by):
            continue
        result = attempt_auto_resolve(
            pos_id, claim, float(prob or 0.5),
            criterion=criterion, retriever=retriever, gateway=gateway,
            confidence_threshold=confidence_threshold, resolve_by=resolve_by,
        )
        results.append(result)
        if dry_run:
            continue
        # A newer pass started while we were researching → discard our writes.
        if guard is not None and my_gen is not None and not guard.is_current(my_gen):
            break
        if result.auto_resolved:
            conn = open_db(positions_db)
            try:
                conn.execute(
                    "UPDATE positions SET outcome=?, brier=?, resolver_kind=?, "
                    "evidence_snapshot=?, resolution_source=?, resolver_confidence=?, "
                    "resolved_via=?, resolved_at=datetime('now') WHERE id=?",
                    (1 if result.outcome else 0, result.brier, result.resolver_kind,
                     result.evidence_snapshot, result.resolution_source,
                     result.confidence, result.resolved_via, pos_id),
                )
            finally:
                conn.close()
        else:
            # Deferred — route to the human queue rather than leave it silent.
            enqueue_human_resolution(positions_db, pos_id,
                                     result.defer_reason or "deferred")
    return results


def _gateway_research_fn(gateway, *, confidence_threshold: float) -> ResearchFn:
    """Adapt a gateway into a :data:`ResearchFn` for :func:`resolve_positions`.

    Reuses the same prompt + parsing as :func:`attempt_auto_resolve` so a live
    run and a unit test share one resolution contract. Sub-threshold or
    unparseable answers map to ``outcome=None`` (deferred).
    """

    def _research(claim: str, criterion: str | None) -> tuple[bool | None, float, str]:
        crit = f"\nResolution criterion: {criterion}\n" if criterion else ""
        prompt = (
            f"Claim to resolve: {claim}\n{crit}\n"
            "Based on current knowledge, has this claim turned out to be TRUE or FALSE?\n"
            "Respond with ONLY one of:\n"
            "TRUE: <confidence 0.0-1.0> — <one-sentence rationale>\n"
            "FALSE: <confidence 0.0-1.0> — <one-sentence rationale>\n"
            "UNCERTAIN: — <one-sentence reason>\n"
        )
        try:
            resp = gateway.complete("aux_context", prompt)
            outcome, confidence, rationale = _parse_resolution(resp.text.strip())
        except Exception as exc:
            return None, 0.0, f"error: {exc!r}"
        if outcome is None or confidence < confidence_threshold:
            return None, confidence or 0.0, rationale or "confidence below threshold"
        return outcome, confidence, rationale

    return _research


def resolve_positions(
    positions_db: Path,
    *,
    research_fn: ResearchFn | None = None,
    gateway=None,
    now: datetime | None = None,
    confidence_threshold: float = 0.7,
    guard: GenerationGuard | None = None,
) -> list[ResolutionResult]:
    """Auto-resolve every past-deadline, unresolved, machine-resolvable position.

    For each candidate the claim is re-researched (via the injected
    ``research_fn`` or, failing that, a gateway-backed default) against its
    ``resolution_criterion``. A confident TRUE/FALSE is committed through
    :func:`positions.resolve_position`, which records the outcome and its Brier
    score. Ambiguous results (``outcome is None`` or below
    ``confidence_threshold``) are *deferred*, not force-resolved. Positions
    classified human-only by :func:`classify_resolution_kind` are skipped.

    Selection is fully deterministic given an injected ``now`` and
    ``research_fn`` — no network, no clock at import. Returns one
    :class:`ResolutionResult` per *attempted* position (deferrals included);
    skipped (future-deadline / human-only / already-resolved) rows are omitted.

    When a :class:`GenerationGuard` is supplied, a newer pass starting mid-run
    causes this pass to stop committing (§4 overlap guard).
    """
    from ..persistence import open_db
    from . import positions as positions_mod

    if research_fn is None:
        if gateway is None:
            return []
        research_fn = _gateway_research_fn(gateway, confidence_threshold=confidence_threshold)

    my_gen = guard.begin() if guard is not None else None

    positions_mod._ensure_extras(positions_db)
    conn = open_db(positions_db)
    try:
        rows = conn.execute(
            "SELECT id, claim, resolve_by, resolution_criterion, outcome "
            "FROM positions WHERE outcome IS NULL"
        ).fetchall()
    finally:
        conn.close()

    results: list[ResolutionResult] = []
    for pos_id, claim, resolve_by, criterion, outcome in rows:
        if outcome is not None:
            continue  # already resolved
        if not is_past_deadline(resolve_by, now=now):
            continue  # future deadline — leave untouched
        if classify_resolution_kind(claim) == "human":
            continue  # human-only — never machine-resolve

        try:
            verdict, confidence, rationale = research_fn(claim, criterion)
        except Exception as exc:
            results.append(ResolutionResult(
                position_id=pos_id, claim=claim, outcome=None,
                confidence=0.0, rationale=f"error: {exc!r}", auto_resolved=False,
            ))
            continue

        if verdict is None or confidence < confidence_threshold:
            # Ambiguous → defer to a human; do NOT write an outcome.
            results.append(ResolutionResult(
                position_id=pos_id, claim=claim, outcome=None,
                confidence=confidence or 0.0,
                rationale=rationale or "ambiguous — deferred",
                auto_resolved=False,
            ))
            continue

        # A newer pass started while we were researching → discard our writes.
        if guard is not None and my_gen is not None and not guard.is_current(my_gen):
            break

        resolved = positions_mod.resolve_position(positions_db, pos_id, verdict)
        results.append(ResolutionResult(
            position_id=pos_id, claim=claim, outcome=verdict,
            confidence=confidence, rationale=rationale,
            auto_resolved=True, brier=resolved.brier,
        ))
    return results
