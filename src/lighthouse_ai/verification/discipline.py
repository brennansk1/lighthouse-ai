"""Quality discipline layer (design §12) — the mechanical enforcement that
makes Lighthouse output *honest*: every claim must be sourced, high-stakes
claims need two independent sources, and unsourced claims get their
confidence (WEP band) downgraded rather than silently asserted.

This is deliberately rule-based and deterministic — the design's principle
is "enforced by linters and gates, not by hoping the LLM behaves."
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .wep import WEPBand, band_for_probability

# A claim is a declarative sentence. We split on sentence boundaries and drop
# fragments / questions. Citation markers look like [1], [2,3], or [n].
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass(frozen=True)
class Claim:
    text: str
    citation_ids: list[int] = field(default_factory=list)

    @property
    def is_sourced(self) -> bool:
        return len(self.citation_ids) >= 1

    @property
    def is_two_sourced(self) -> bool:
        return len(set(self.citation_ids)) >= 2


@dataclass(frozen=True)
class DisciplineReport:
    claims: list[Claim]
    sourced: int
    unsourced: int
    two_sourced: int
    citation_coverage: float          # fraction of claims with >=1 citation
    passed: bool                      # meets the configured floor
    notes: list[str] = field(default_factory=list)
    distinct_sources: int = 0
    entailment_coverage: float = 0.0  # fraction of sourced claims entailed by grounding
    entailment_checked: bool = False   # True iff MiniCheck/HHEM was available
    # Triangulation + integrity (set when evidence_chunks is supplied):
    triangulated: int = 0              # claims with >=2 INDEPENDENT sources (distinct docs)
    fabricated_citations: int = 0      # citation ids that map to no evidence chunk
    contradictions: list[tuple[str, str]] = field(default_factory=list)


# Antonym pairs + negation markers for a conservative, deterministic
# contradiction heuristic. We only flag a pair when the two claims share enough
# subject tokens AND carry opposing polarity — favouring precision over recall so
# we don't cry "contradiction" on unrelated sentences.
_ANTONYM_PAIRS = [
    ("increase", "decrease"), ("increases", "decreases"), ("rose", "fell"),
    ("rise", "fall"), ("higher", "lower"), ("more", "less"), ("grew", "shrank"),
    ("positive", "negative"), ("effective", "ineffective"), ("safe", "unsafe"),
    ("benefit", "harm"), ("benefits", "harms"), ("supports", "refutes"),
    ("confirms", "contradicts"), ("improved", "worsened"),
]
_NEGATIONS = {"not", "no", "never", "n't", "without", "cannot", "fails", "failed"}
_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "and", "or", "is", "are", "was",
    "were", "be", "been", "it", "its", "this", "that", "these", "those", "with",
    "for", "by", "as", "at", "from", "has", "have", "had", "but", "than",
}


def extract_claims(text: str) -> list[Claim]:
    """Pull declarative, citeable claims out of a synthesis block.

    Skips questions and very short fragments. Captures inline [N] citations.
    """
    claims: list[Claim] = []
    # Strip HTML tags if any slipped in.
    plain = re.sub(r"<[^>]+>", " ", text)
    for raw in _SENTENCE_SPLIT.split(plain):
        s = raw.strip()
        if len(s.split()) < 3:          # 1-2 word fragment / heading
            continue
        if s.endswith("?"):             # a question is not a claim
            continue
        ids: list[int] = []
        for m in _CITATION.finditer(s):
            ids.extend(int(x) for x in re.split(r"\s*,\s*", m.group(1)))
        claims.append(Claim(text=s, citation_ids=ids))
    return claims


def _domain_by_id(evidence_chunks: list) -> dict[int, str]:
    """Map 1-based citation id → source domain/document for independence checks."""
    out: dict[int, str] = {}
    for idx, r in enumerate(evidence_chunks, start=1):
        chunk = getattr(r, "chunk", r)
        meta = getattr(chunk, "metadata", {}) or {}
        domain = meta.get("source") or getattr(chunk, "document_id", None) \
            or getattr(chunk, "id", f"chunk{idx}")
        out[idx] = str(domain)
    return out


def _significant_tokens(text: str) -> set[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in toks if t not in _STOPWORDS and len(t) > 2}


def detect_contradictions(claims: list[Claim]) -> list[tuple[str, str]]:
    """Conservatively flag pairs of claims that appear to disagree.

    A pair is flagged only when the claims share >=2 significant subject tokens
    AND carry opposing polarity — either opposite members of an antonym pair, or
    exactly one of them negates a shared key token. Precision over recall: better
    to miss a subtle contradiction than to manufacture a false one.
    """
    out: list[tuple[str, str]] = []
    toks = [(_significant_tokens(c.text), c.text.lower(), c.text) for c in claims]
    for i in range(len(toks)):
        ti, li, raw_i = toks[i]
        for j in range(i + 1, len(toks)):
            tj, lj, raw_j = toks[j]
            shared = ti & tj
            if len(shared) < 2:
                continue
            opposed = False
            for a, b in _ANTONYM_PAIRS:
                if (a in ti and b in tj) or (b in ti and a in tj):
                    opposed = True
                    break
            if not opposed:
                neg_i = bool(_NEGATIONS & ti) or "n't" in li
                neg_j = bool(_NEGATIONS & tj) or "n't" in lj
                # one negates, the other asserts, over a shared subject
                if neg_i != neg_j and len(shared) >= 3:
                    opposed = True
            if opposed:
                out.append((raw_i, raw_j))
    return out


def check(text: str, *, min_coverage: float = 0.6,
          high_stakes: bool = False,
          evidence_chunks: list | None = None) -> DisciplineReport:
    """Run the discipline gate over a synthesis block.

    ``min_coverage`` — required fraction of claims carrying >=1 citation.
    ``high_stakes`` — when True, claims should satisfy the two-source rule.
    ``evidence_chunks`` — optional list of HybridResult or Chunk objects used
        to score entailment faithfulness via MiniCheck / HHEM when available.
    """
    from . import entailment as _entailment

    claims = extract_claims(text)
    if not claims:
        return DisciplineReport(claims=[], sourced=0, unsourced=0, two_sourced=0,
                                citation_coverage=0.0, passed=False,
                                notes=["no extractable claims"])
    sourced = sum(1 for c in claims if c.is_sourced)
    unsourced = len(claims) - sourced
    two = sum(1 for c in claims if c.is_two_sourced)
    coverage = sourced / len(claims)
    notes: list[str] = []
    passed = coverage >= min_coverage
    if not passed:
        notes.append(f"citation coverage {coverage:.0%} below floor {min_coverage:.0%}")
    if high_stakes and two < sourced:
        notes.append(f"two-source rule: only {two}/{sourced} sourced claims "
                     f"have >=2 independent citations")
        passed = passed and (two >= sourced)

    # --- entailment gate (MiniCheck / HHEM when available) ---
    entailment_coverage = 0.0
    entailment_checked = False
    if evidence_chunks is not None and _entailment.available():
        sourced_claims = [c for c in claims if c.is_sourced]
        if sourced_claims:
            # Build a lookup: citation_id → chunk text (best-effort)
            chunk_by_id: dict[int, str] = {}
            for idx, r in enumerate(evidence_chunks, start=1):
                chunk = getattr(r, "chunk", r)
                chunk_text = getattr(chunk, "text", "")
                chunk_by_id[idx] = chunk_text

            entailed = 0
            for claim in sourced_claims:
                # Use the first available citation to find the grounding chunk.
                grounding = ""
                for cid in claim.citation_ids:
                    if cid in chunk_by_id:
                        grounding = chunk_by_id[cid]
                        break
                if not grounding and chunk_by_id:
                    # Fall back to the first chunk if no id matches.
                    grounding = next(iter(chunk_by_id.values()))
                score = _entailment.score_claim(claim.text, grounding)
                if score >= _entailment.MINICHECK_THRESHOLD:
                    entailed += 1
            entailment_coverage = entailed / len(sourced_claims)
            entailment_checked = True

            if high_stakes and entailment_coverage < 0.85:
                notes.append(
                    f"high-stakes entailment floor not met: "
                    f"{entailment_coverage:.0%} < 85%"
                )
                passed = False

    # --- triangulation + citation integrity (when evidence is supplied) ---
    triangulated = 0
    fabricated = 0
    if evidence_chunks is not None:
        dom_by_id = _domain_by_id(evidence_chunks)
        valid_ids = set(dom_by_id)
        for c in claims:
            if not c.citation_ids:
                continue
            if any(cid not in valid_ids for cid in c.citation_ids):
                fabricated += 1
            domains = {dom_by_id[cid] for cid in c.citation_ids if cid in valid_ids}
            if len(domains) >= 2:
                triangulated += 1
        if fabricated:
            notes.append(f"{fabricated} claim(s) cite non-existent sources "
                         f"(fabricated citations)")
            if high_stakes:
                passed = False

    # --- contradiction surfacing (always; cheap and corpus-independent) ---
    contradictions = detect_contradictions(claims)
    if contradictions:
        notes.append(f"{len(contradictions)} potential contradiction(s) surfaced")

    return DisciplineReport(claims=claims, sourced=sourced, unsourced=unsourced,
                            two_sourced=two, citation_coverage=round(coverage, 3),
                            passed=passed, notes=notes,
                            entailment_coverage=round(entailment_coverage, 3),
                            entailment_checked=entailment_checked,
                            triangulated=triangulated,
                            fabricated_citations=fabricated,
                            contradictions=contradictions)


def check_source_diversity(evidence_chunks) -> int:
    """Count distinct source domains from evidence chunk metadata.

    Each element of evidence_chunks should be a HybridResult (has .chunk attribute)
    or a raw Chunk. Uses chunk.metadata.get("source") as the domain key,
    falling back to chunk.document_id if "source" metadata is absent.
    """
    domains: set[str] = set()
    for r in evidence_chunks:
        chunk = getattr(r, "chunk", r)
        meta = getattr(chunk, "metadata", {})
        domain = meta.get("source") or getattr(chunk, "document_id", "unknown")
        domains.add(str(domain))
    return len(domains)


def downgrade_wep(probability: float, report: DisciplineReport) -> WEPBand:
    """Lower the confidence band when sourcing is weak.

    Honest-over-impressive: a well-written but poorly-sourced answer should
    not be presented as 'almost certain'. We scale the stated probability by
    citation coverage before mapping to a band.
    """
    adjusted = probability * max(report.citation_coverage, 0.1)
    return band_for_probability(min(max(adjusted, 0.0), 1.0))
