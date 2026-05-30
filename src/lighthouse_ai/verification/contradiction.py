"""Contradiction artifact + detection (MODE_SKILL_INTEGRATION §6).

Every detected contradiction is a first-class object in the audit chain. This
module turns the discipline gate's cheap polarity heuristic plus (optional)
entailment scores into structured :class:`Contradiction` records spanning the
three detection layers of §6.1:

1. **chunk** — overlapping subject tokens + opposing polarity (reuses
   ``discipline.detect_contradictions``). Always cheap, precision-biased.
2. **claim** — entailment model flags claims with conflicting scores as
   *contested* rather than asserted true. Degrades gracefully when no
   entailment backend is installed.
3. **cross_skill** — the same claim with opposing evidence drawn from *different*
   ``skill_id`` sources. Independent sources disagreeing is a stronger signal, so
   severity is elevated above an intra-skill disagreement.

Determinism + offline-first: nothing here calls ``datetime.now()`` at import or
at runtime — callers pass ``detected_at`` in. Entailment is optional and lazy;
when unavailable we fall back to the polarity heuristic only.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from . import discipline

DetectionLayer = Literal["chunk", "claim", "cross_skill"]
Severity = Literal["low", "medium", "high"]
ResolutionStatus = Literal["unresolved", "weighted", "adjudicated", "deferred"]

# Entailment scores below this are treated as "opposing" (contradicted /
# unsupported); at/above OPPOSING are treated as supporting. Mirrors the
# entailment module's neutral threshold so the two layers agree.
_OPPOSING_BELOW: float = 0.5
_SUPPORTING_AT_OR_ABOVE: float = 0.5

# A contradiction is "balanced" (→ high severity, the §6.4 condition) when
# neither side dominates the evidence. We measure dominance by chunk count.
_BALANCE_RATIO: float = 0.5  # minority/majority count must be >= this to be balanced


@dataclass(frozen=True)
class ChunkRef:
    """Lightweight, JSON-serializable reference to an evidence chunk.

    Carries just enough provenance to render a contradiction and to feed the
    independence / cross-skill checks: which chunk, which skill produced it, how
    strongly it entails the claim, and a short text snippet for the UI.
    """

    chunk_id: str
    skill_id: str | None
    entailment_score: float
    text: str  # short snippet


@dataclass
class Contradiction:
    """First-class audit object for a detected disagreement (§6.3)."""

    contradiction_id: str
    claim: str
    supporting_chunks: list[ChunkRef]
    opposing_chunks: list[ChunkRef]
    detection_layer: DetectionLayer
    severity: Severity
    detected_at: datetime
    detected_in_job: str
    resolution_status: ResolutionStatus = "unresolved"
    resolution_ref: str | None = None


# --------------------------------------------------------------------------- #
# Chunk introspection helpers (mirror discipline.py's duck-typed access)
# --------------------------------------------------------------------------- #

def _chunk_of(r: object) -> object:
    """Unwrap a HybridResult (.chunk) or return the raw Chunk/dict as-is."""
    if isinstance(r, dict):
        return r.get("chunk", r)
    return getattr(r, "chunk", r)


def _meta_of(chunk: object) -> dict:
    if isinstance(chunk, dict):
        meta = chunk.get("metadata", {})
    else:
        meta = getattr(chunk, "metadata", {})
    return meta or {}


def _attr(chunk: object, name: str, default=None):
    if isinstance(chunk, dict):
        return chunk.get(name, default)
    return getattr(chunk, name, default)


def _skill_id_of(chunk: object) -> str | None:
    """Provenance skill_id from chunk metadata (None if unattributed)."""
    meta = _meta_of(chunk)
    sid = meta.get("skill_id")
    return str(sid) if sid is not None else None


def _entailment_of(chunk: object) -> float | None:
    """Per-chunk entailment score if pre-computed, else None.

    We look in metadata first (``entailment_score``) then on the object/dict
    directly, so both enriched HybridResults and plain dicts work.
    """
    meta = _meta_of(chunk)
    if "entailment_score" in meta and meta["entailment_score"] is not None:
        return float(meta["entailment_score"])
    val = _attr(chunk, "entailment_score", None)
    return float(val) if val is not None else None


def _chunk_id_of(chunk: object, fallback_idx: int) -> str:
    cid = _attr(chunk, "id", None) or _attr(chunk, "chunk_id", None) \
        or _attr(chunk, "document_id", None)
    return str(cid) if cid is not None else f"chunk{fallback_idx}"


def _text_of(chunk: object, *, limit: int = 240) -> str:
    text = _attr(chunk, "text", "") or ""
    text = str(text).strip()
    return text[:limit]


def _to_ref(r: object, idx: int) -> ChunkRef:
    chunk = _chunk_of(r)
    _ent = _entailment_of(chunk)
    return ChunkRef(
        chunk_id=_chunk_id_of(chunk, idx),
        skill_id=_skill_id_of(chunk),
        entailment_score=_ent if _ent is not None else 1.0,
        text=_text_of(chunk),
    )


# --------------------------------------------------------------------------- #
# Severity + id derivation
# --------------------------------------------------------------------------- #

def _contradiction_id(claim: str, layer: str, job_id: str) -> str:
    """Stable, deterministic id (no randomness, no clock)."""
    h = hashlib.sha1(f"{job_id}|{layer}|{claim}".encode()).hexdigest()[:12]
    return f"contradiction-{h}"


def _is_balanced(n_support: int, n_oppose: int) -> bool:
    if n_support == 0 or n_oppose == 0:
        return False
    lo, hi = sorted((n_support, n_oppose))
    return (lo / hi) >= _BALANCE_RATIO


def derive_severity(
    *,
    n_support: int,
    n_oppose: int,
    layer: DetectionLayer,
    load_bearing: bool,
) -> Severity:
    """Severity from evidence balance + load-bearing + detection layer (§6.3).

    - Balanced evidence on a load-bearing claim → ``high`` (the auto-Adjudicate
      precondition). ``high`` is reserved for this case: ``should_auto_adjudicate``
      keys off ``severity == "high"`` to encode "load-bearing", so we must NOT
      assign ``high`` to a non-load-bearing claim — not even a balanced
      cross-skill one (that would auto-adjudicate a claim that isn't load-bearing,
      violating §6.4 condition 2).
    - Cross-skill disagreement *elevates*: independent sources disagreeing is a
      stronger signal, so a cross-skill clash is never below ``medium`` even when
      lopsided / non-load-bearing.
    - Other lopsided / non-load-bearing clashes → ``low``/``medium``.
    """
    balanced = _is_balanced(n_support, n_oppose)

    if balanced and load_bearing:
        return "high"
    if layer == "cross_skill":
        # Elevated floor; ``high`` already handled above (requires load-bearing).
        return "medium"
    if layer == "chunk" and balanced:
        # The polarity heuristic only fires on a genuine opposing pair, so a
        # flagged chunk contradiction is never below 'medium' (even non-LB).
        return "medium"
    if load_bearing:
        return "medium"
    return "low"


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #

def _partition_by_entailment(
    refs: list[ChunkRef],
) -> tuple[list[ChunkRef], list[ChunkRef]]:
    """Split refs into (supporting, opposing) by entailment score."""
    support = [r for r in refs if r.entailment_score >= _SUPPORTING_AT_OR_ABOVE]
    oppose = [r for r in refs if r.entailment_score < _OPPOSING_BELOW]
    return support, oppose


def detect(
    claims,
    evidence_chunks,
    *,
    job_id: str,
    detected_at: datetime,
    layer_hint: DetectionLayer | None = None,
    load_bearing=False,
) -> list[Contradiction]:
    """Detect contradictions across the three §6.1 layers.

    Parameters
    ----------
    claims:
        Iterable of ``discipline.Claim`` (or anything with a ``.text`` attribute
        / dicts with ``text``). Used for the chunk-level polarity heuristic and
        as the unit of the claim/cross-skill layers.
    evidence_chunks:
        Iterable of HybridResult / Chunk / dict carrying ``metadata.skill_id``
        and optionally ``entailment_score``. May be empty.
    job_id:
        Recorded as ``detected_in_job`` on every artifact.
    detected_at:
        Timestamp stamped onto every artifact (passed in — never ``now()``).
    layer_hint:
        Restrict detection to a single layer when set; otherwise run all layers
        applicable to the available evidence.
    load_bearing:
        Either a single bool (applies to all claims) or a mapping/sequence
        keyed/indexed by claim, marking which claims are load-bearing. Feeds
        severity derivation.

    Returns a list of :class:`Contradiction` (possibly empty), deterministic in
    order and id.
    """
    claim_list = list(claims)
    refs = [_to_ref(r, i) for i, r in enumerate(evidence_chunks, start=1)]

    def _claim_text(c) -> str:
        if isinstance(c, dict):
            return str(c.get("text", ""))
        return str(getattr(c, "text", c))

    def _is_load_bearing(idx: int, c) -> bool:
        if isinstance(load_bearing, bool):
            return load_bearing
        if isinstance(load_bearing, dict):
            return bool(load_bearing.get(_claim_text(c),
                                         load_bearing.get(idx, False)))
        try:
            return bool(load_bearing[idx])
        except (IndexError, KeyError, TypeError):
            return False

    out: list[Contradiction] = []
    seen_ids: set[str] = set()

    def _emit(claim_text: str, layer: DetectionLayer,
              support: list[ChunkRef], oppose: list[ChunkRef],
              lb: bool, *, balance: tuple[int, int] | None = None) -> None:
        cid = _contradiction_id(claim_text, layer, job_id)
        if cid in seen_ids:
            return
        seen_ids.add(cid)
        # ``balance`` overrides the count used for severity when the layer has no
        # per-chunk refs of its own (e.g. the chunk-level polarity heuristic).
        n_sup, n_opp = balance if balance is not None else (len(support), len(oppose))
        sev = derive_severity(n_support=n_sup, n_oppose=n_opp,
                              layer=layer, load_bearing=lb)
        out.append(Contradiction(
            contradiction_id=cid,
            claim=claim_text,
            supporting_chunks=support,
            opposing_chunks=oppose,
            detection_layer=layer,
            severity=sev,
            detected_at=detected_at,
            detected_in_job=job_id,
        ))

    want = {layer_hint} if layer_hint else {"chunk", "claim", "cross_skill"}

    # --- Layer 1: chunk-level polarity heuristic (reuse discipline) -------- #
    if "chunk" in want:
        # discipline.detect_contradictions wants Claim objects with .text.
        from .discipline import Claim as _Claim
        polarity_claims = [c if hasattr(c, "text") else _Claim(text=_claim_text(c))
                           for c in claim_list]
        for raw_i, _raw_j in discipline.detect_contradictions(polarity_claims):
            # Match the surfaced claim back to its index for load-bearing.
            idx = next((k for k, c in enumerate(claim_list)
                        if _claim_text(c) == raw_i), 0)
            lb = _is_load_bearing(idx, claim_list[idx] if claim_list else raw_i)
            # No per-chunk balance available at this layer; treat the two sides
            # symmetrically (1 vs 1) so a flagged pair is at least 'medium'.
            _emit(raw_i, "chunk", support=[], oppose=[], lb=lb, balance=(1, 1))

    # --- Layers 2+3: entailment-based, per claim -------------------------- #
    if ("claim" in want or "cross_skill" in want) and refs:
        for idx, c in enumerate(claim_list):
            text = _claim_text(c)
            lb = _is_load_bearing(idx, c)
            support, oppose = _partition_by_entailment(refs)
            if not (support and oppose):
                continue  # no disagreement among the evidence

            opposing_skills = {r.skill_id for r in oppose if r.skill_id}
            supporting_skills = {r.skill_id for r in support if r.skill_id}
            cross_skill = bool(
                opposing_skills and supporting_skills
                and opposing_skills != supporting_skills
            )

            if cross_skill and "cross_skill" in want:
                _emit(text, "cross_skill", support, oppose, lb)
            elif "claim" in want:
                _emit(text, "claim", support, oppose, lb)

    return out


# --------------------------------------------------------------------------- #
# Auto-Adjudicate gate (§6.4 — exactly these five conditions)
# --------------------------------------------------------------------------- #

_AUTO_ADJUDICATE_TIERS = frozenset({"thorough", "deep"})


def should_auto_adjudicate(
    contradiction: Contradiction,
    *,
    depth_tier: str,
    user_disabled: bool = False,
) -> bool:
    """True iff ALL five §6.4 conditions hold.

    1. ``detection_layer == "cross_skill"``
    2. the claim is load-bearing (encoded as ``severity == "high"``, which the
       severity rule only assigns to balanced cross-skill clashes on
       load-bearing claims)
    3. ``severity == "high"`` (balanced evidence)
    4. depth tier is Thorough or Deep
    5. the user has not disabled auto-Adjudicate
    """
    return (
        contradiction.detection_layer == "cross_skill"
        and contradiction.severity == "high"
        and str(depth_tier).strip().lower() in _AUTO_ADJUDICATE_TIERS
        and not user_disabled
    )


# --------------------------------------------------------------------------- #
# Audit hook
# --------------------------------------------------------------------------- #

def to_audit_record(contradiction: Contradiction) -> dict:
    """JSON-serializable record for the HMAC audit chain.

    The ``detected_at`` datetime is rendered via ``isoformat()``; ChunkRefs are
    flattened to plain dicts. The result contains only str/float/list/dict so it
    round-trips through ``json.dumps`` deterministically.
    """
    record = asdict(contradiction)
    record["detected_at"] = contradiction.detected_at.isoformat()
    record["kind"] = "contradiction"
    return record
