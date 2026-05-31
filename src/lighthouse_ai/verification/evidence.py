"""Evidence retriever for the calibration resolver.

The resolver must **never** grade a past prediction from the model's own
parametric memory — that self-grading circularity inflates apparent calibration
(Panickssery et al., NeurIPS 2024). Instead it resolves a position ONLY from
freshly retrieved evidence. This module builds an
:data:`~lighthouse_ai.verification.resolver.EvidenceRetriever` that re-researches
a claim against public sources (the universal ``general_web`` skill, through the
sandbox broker) at resolution time and returns ``(evidence_text, source_id)``.

Local-first / graceful: when there is no gateway, no broker, the fetch fails, or
nothing is found, the retriever returns ``None`` — and the resolver then **defers
to the human-resolution queue** rather than guess. Offline runs never touch the
network (the supervisor's resolver loop is itself a no-op unless
``LIGHTHOUSE_REAL_BACKEND=1``).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from ..paths import Paths
    from .resolver import EvidenceRetriever

_log = structlog.get_logger(__name__)

#: Universal source used to re-research a claim at resolution time.
_RESOLVER_SOURCE = "general_web"
#: How many documents to gather per resolution (bounded — resolution must be cheap).
_MAX_RESULTS = 3
#: Cap on the evidence text handed to the resolver prompt (chars).
_EVIDENCE_CHARS = 6000


def build_evidence_retriever(
    paths: Paths,
    *,
    gateway,
    broker=None,
    source_id: str = _RESOLVER_SOURCE,
    max_results: int = _MAX_RESULTS,
) -> EvidenceRetriever | None:
    """Build a re-fetch evidence retriever, or ``None`` when one can't be made.

    Returns ``None`` (so the caller wires no retriever and every due position
    safely defers) when there is no ``gateway`` or no usable broker. The returned
    callable never raises — any fetch fault degrades to ``None`` for that claim,
    which the resolver treats as "no grounded evidence → defer to a human".
    """
    if gateway is None:
        return None
    if broker is None:
        try:
            from ..sandbox.broker import build_default_broker
            broker = build_default_broker(paths.data_dir)
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("resolver.evidence.broker_failed", error=repr(exc))
            broker = None
    if broker is None:
        return None

    def _retrieve(claim: str, criterion: str | None, cutoff: str) -> tuple[str, str] | None:
        try:
            from ..skills import load_skill, run_skill
            skill = load_skill(source_id)
            # Target the search at the claim (and its criterion when present).
            query = f"{claim} {criterion}".strip() if criterion else claim
            run = run_skill(skill, query, broker=broker, gateway=gateway,
                            max_results=max_results)
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("resolver.evidence.fetch_error", error=repr(exc))
            return None
        if not run.documents:
            return None
        parts: list[str] = []
        src: str | None = None
        for doc in run.documents[:max_results]:
            text = (getattr(doc, "text", "") or "").strip()
            if not text:
                continue
            parts.append(text)
            if src is None:
                meta = getattr(doc, "metadata", {}) or {}
                src = str(meta.get("url") or meta.get("source") or getattr(doc, "id", ""))
        if not parts:
            return None
        evidence = "\n\n".join(parts)[:_EVIDENCE_CHARS]
        return evidence, (src or source_id)

    return _retrieve
