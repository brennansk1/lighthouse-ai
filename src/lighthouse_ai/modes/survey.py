"""Mode — Survey: screen many documents into an evidence table + PRISMA flow.

A Survey run takes a corpus of documents, screens each against inclusion /
exclusion criteria, then extracts a fixed set of attributes from the included
documents into an evidence table. Every extracted cell is grounded in a source
chunk and gated by entailment so unsupported values are flagged rather than
asserted. The run also reports PRISMA-style counts (identified → screened →
included → excluded) so the screening funnel is auditable.

Deterministic when ``gateway=None``: screening decisions and cell values come
from keyword heuristics over the document text, so tests and dry runs reproduce
exactly. With a gateway the same structure is filled by the model. The gateway
path falls back to the heuristic path on any exception, preserving determinism
when the model is unavailable.

PRISMA accounting
-----------------
``identified`` — total unique documents supplied (duplicates by doc_id are
  deduplicated before any screening).
``screened`` — same as ``identified`` (every supplied document is screened;
  there is no abstract/title-only pre-filter in the offline path).
``included`` — documents that passed all criteria.
``excluded`` — ``identified - included``; internally consistent by construction.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..gateway import Gateway
from ..governor.scheduler_gate import SchedulerGate
from ..verification import entailment as _entailment
from ._gate import gate_ctx

# ---------------------------------------------------------------------------
# Public dataclasses — field names are stable; the dispatcher serialises these
# via ``dataclasses.asdict`` and the frontend reads the resulting keys.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Document:
    """A single document to be screened and (if included) mined for attributes.

    Attributes
    ----------
    doc_id:
        Unique identifier.  Duplicate ``doc_id`` values in a corpus are
        deduplicated before screening; only the first occurrence is kept.
    title:
        Human-readable title, prepended to the screening haystack.
    text:
        Full body text used for both screening and attribute extraction.
    """

    doc_id: str
    title: str
    text: str


@dataclass(frozen=True)
class ScreeningCriterion:
    """A single PRISMA-style screening criterion.

    Attributes
    ----------
    label:
        Short name used in reason strings and reports.
    keywords:
        Tokens (case-insensitive substring match) that signal this criterion.
        For inclusion criteria (``exclude=False``): *at least one* keyword must
        appear in the document — an empty tuple means the criterion is vacuously
        satisfied (always passes).
        For exclusion criteria (``exclude=True``): *any* keyword match drops the
        document immediately.
    exclude:
        ``True`` → keyword presence causes rejection; ``False`` (default) →
        keyword presence (or an empty keyword tuple) allows the document through.
    """

    label: str
    keywords: tuple[str, ...] = ()
    exclude: bool = False


@dataclass(frozen=True)
class AttributeSpec:
    """Specification of a single attribute column in the evidence table.

    Attributes
    ----------
    label:
        Column header shown in the evidence table and stored in each cell.
    keywords:
        Hint tokens used by the offline extractor to locate the relevant
        sentence.  Falls back to the label itself when the tuple is empty.
    """

    label: str
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScreenDecision:
    """Per-document screening outcome."""

    doc_id: str
    included: bool
    reason: str


@dataclass(frozen=True)
class EvidenceCell:
    """One attribute value extracted from one document.

    Attributes
    ----------
    attribute:
        The ``AttributeSpec.label`` this cell belongs to.
    value:
        Extracted text, or ``""`` when the attribute is absent / not found.
    citation_chunk_ids:
        Identifiers of the source chunks that ground the value.
    entailment_score:
        Score in ``[0.0, 1.0]`` from the entailment checker; ``1.0`` when no
        scorer is available (graceful degradation).
    entailed:
        ``True`` when ``entailment_score >= MINICHECK_THRESHOLD``.
    """

    attribute: str
    value: str
    citation_chunk_ids: tuple[str, ...]
    entailment_score: float
    entailed: bool


@dataclass(frozen=True)
class EvidenceRow:
    """All extracted attribute cells for one included document.

    Attributes
    ----------
    doc_id, title:
        Mirror of the source document identifiers.
    cells:
        One ``EvidenceCell`` per ``AttributeSpec``, in the same order.
    missing_attrs:
        Additive field — labels of attributes whose extracted ``value`` is
        ``""``.  Handy for downstream quality checks without re-scanning cells.
    """

    doc_id: str
    title: str
    cells: list[EvidenceCell]
    missing_attrs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PrismaFlow:
    """PRISMA-style screening funnel counts.

    All four fields are internally consistent:
    ``excluded == identified - included`` is guaranteed by ``run_survey``.

    Attributes
    ----------
    identified:
        Unique documents supplied (after deduplication by ``doc_id``).
    screened:
        Documents that were evaluated against criteria (equals ``identified``
        because the offline path screens every document).
    included:
        Documents that passed all criteria.
    excluded:
        ``identified - included``.
    excluded_reasons:
        Additive field — mapping of ``doc_id → reason`` for every excluded
        document, supporting downstream audit without re-running screening.
    """

    identified: int
    screened: int
    included: int
    excluded: int
    excluded_reasons: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SurveyReport:
    """Top-level artifact returned by ``run_survey``.

    Attributes
    ----------
    question:
        The research question the survey addresses.
    criteria:
        Screening criteria applied (coerced from dict input if needed).
    attributes:
        Attribute specs extracted (coerced from dict input if needed).
    decisions:
        One ``ScreenDecision`` per document, in corpus order.
    rows:
        Evidence rows for *included* documents only, in corpus order.
    prisma:
        PRISMA-style funnel counts.
    claims:
        Human-readable summary sentences suitable for citation or audit.
    """

    question: str
    criteria: list[ScreeningCriterion]
    attributes: list[AttributeSpec]
    decisions: list[ScreenDecision]
    rows: list[EvidenceRow]
    prisma: PrismaFlow
    claims: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Input coercion helpers
# ---------------------------------------------------------------------------

def _coerce_documents(documents: Sequence[Document | dict]) -> list[Document]:
    """Normalise a mixed sequence of ``Document`` objects and plain dicts.

    Duplicate ``doc_id`` values are silently deduplicated (first occurrence
    wins), which keeps PRISMA counts consistent: every row in ``identified``
    maps to exactly one screening decision.
    """
    seen: set[str] = set()
    out: list[Document] = []
    for i, d in enumerate(documents):
        if isinstance(d, Document):
            doc = d
        else:
            doc = Document(
                doc_id=str(d.get("doc_id") or d.get("id") or f"doc{i}"),
                title=str(d.get("title", "")),
                text=str(d.get("text", "")),
            )
        if doc.doc_id not in seen:
            seen.add(doc.doc_id)
            out.append(doc)
    return out


def _coerce_criteria(criteria: Sequence[ScreeningCriterion | dict]) -> list[ScreeningCriterion]:
    """Normalise a mixed sequence of ``ScreeningCriterion`` objects and dicts."""
    out: list[ScreeningCriterion] = []
    for c in criteria:
        if isinstance(c, ScreeningCriterion):
            out.append(c)
        else:
            out.append(ScreeningCriterion(
                label=str(c["label"]),
                keywords=tuple(str(k) for k in c.get("keywords", ())),
                exclude=bool(c.get("exclude", False)),
            ))
    return out


def _coerce_attributes(attributes: Sequence[AttributeSpec | dict]) -> list[AttributeSpec]:
    """Normalise a mixed sequence of ``AttributeSpec`` objects and dicts."""
    out: list[AttributeSpec] = []
    for a in attributes:
        if isinstance(a, AttributeSpec):
            out.append(a)
        else:
            out.append(AttributeSpec(
                label=str(a["label"]),
                keywords=tuple(str(k) for k in a.get("keywords", ())),
            ))
    return out


# ---------------------------------------------------------------------------
# Offline (stub) screening and extraction
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Collapse runs of whitespace and lowercase for robust keyword matching."""
    return re.sub(r"\s+", " ", text).lower()


def _stub_screen(doc: Document, criteria: list[ScreeningCriterion]) -> ScreenDecision:
    """Keyword-based screening: fast, deterministic, no model required.

    Decision logic
    --------------
    Criteria are evaluated in order.  The first failing criterion short-circuits:

    * **Exclusion criterion** (``exclude=True``): if *any* keyword matches the
      haystack, the document is immediately rejected.
    * **Inclusion criterion** (``exclude=False``): if the criterion has keywords
      and *none* matches, the document is rejected.  A criterion with an empty
      keyword tuple is vacuously satisfied (always passes).

    The haystack is ``"<title> <text>"`` with whitespace normalised and
    lowercased, so matching is case-insensitive and whitespace-agnostic.
    """
    haystack = _normalize(f"{doc.title} {doc.text}")
    for c in criteria:
        if not c.keywords:
            # Vacuous inclusion criterion — nothing to match against.
            continue
        needles = [k.strip().lower() for k in c.keywords if k.strip()]
        hit = any(n in haystack for n in needles)
        if c.exclude and hit:
            return ScreenDecision(
                doc.doc_id, included=False,
                reason=f"excluded by '{c.label}': keyword matched")
        if not c.exclude and not hit:
            return ScreenDecision(
                doc.doc_id, included=False,
                reason=f"missing '{c.label}': no keyword matched")
    return ScreenDecision(doc.doc_id, included=True, reason="meets all criteria")


# Sentence boundary: split on ". ", "! ", "? " or end-of-string, keeping the
# terminating punctuation with the sentence it belongs to.
_SENT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, stripping blank results."""
    return [s.strip() for s in _SENT_RE.split(text.replace("\n", " ")) if s.strip()]


def _stub_extract(doc: Document, attr: AttributeSpec) -> str:
    """Return the shortest sentence mentioning any attribute keyword, else ``""``.

    Falls back to the attribute label as the sole needle when ``attr.keywords``
    is empty, so label-only ``AttributeSpec`` objects still produce useful
    extractions. Prefers shorter sentences (less noise) when multiple sentences
    match, and collapses internal whitespace for a clean output value.
    """
    text = doc.text.strip()
    if not text:
        return ""
    sentences = _split_sentences(text)
    needles = [k.strip().lower() for k in attr.keywords if k.strip()]
    if not needles:
        needles = [attr.label.strip().lower()]

    matches = []
    for s in sentences:
        low = _normalize(s)
        if any(n in low for n in needles):
            # Normalise internal whitespace in the returned value.
            matches.append(re.sub(r"\s+", " ", s))

    if not matches:
        return ""
    # Prefer the most specific (shortest) matching sentence.
    return min(matches, key=len)


# ---------------------------------------------------------------------------
# LLM-backed screening and extraction
# ---------------------------------------------------------------------------

def _llm_screen(gateway: Gateway, question: str, doc: Document,
                criteria: list[ScreeningCriterion], *, job_id: str | None,
                gate: SchedulerGate | None) -> ScreenDecision:
    """Ask the LLM to make an inclusion/exclusion decision.

    Falls back to ``_stub_screen`` on any exception so a transient model
    failure never silently drops a document without a recorded reason.
    """
    crit_lines = "\n".join(
        f"- {c.label}" + (" (EXCLUDE if present)" if c.exclude else "")
        for c in criteria)
    prompt = (
        f"Survey question: {question}\n"
        f"Document title: {doc.title}\n"
        f"Document text:\n{doc.text[:2000]}\n\n"
        f"Screening criteria:\n{crit_lines}\n\n"
        "Should this document be INCLUDED in the survey? "
        "Reply 'INCLUDE' or 'EXCLUDE' followed by a one-line reason."
    )
    try:
        with gate_ctx(gate):
            resp = gateway.complete_structured(prompt, job_id=job_id)
        text = resp.text.strip()
        included = text.upper().lstrip().startswith("INCLUDE")
        reason = text.split("\n", 1)[0][:200]
        return ScreenDecision(doc.doc_id, included=included, reason=reason)
    except Exception:
        return _stub_screen(doc, criteria)


def _llm_extract(gateway: Gateway, doc: Document, attr: AttributeSpec, *,
                 job_id: str | None, gate: SchedulerGate | None) -> str:
    """Ask the LLM to extract a single attribute value.

    Falls back to ``_stub_extract`` on any exception so a transient model
    failure produces an empty-value cell rather than an unhandled error.
    """
    prompt = (
        f"Document:\n{doc.text[:2000]}\n\n"
        f"Extract the value for the attribute: {attr.label}\n"
        "Reply with only the value, grounded in the document. "
        "If absent, reply 'N/A'."
    )
    try:
        with gate_ctx(gate):
            resp = gateway.complete_structured(prompt, job_id=job_id)
        val = resp.text.strip()
        return "" if val.upper() in {"N/A", "NONE", ""} else val
    except Exception:
        return _stub_extract(doc, attr)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def run_survey(
    question: str,
    documents: Sequence[Document | dict],
    criteria: Sequence[ScreeningCriterion | dict],
    attributes: Sequence[AttributeSpec | dict],
    *,
    gateway: Gateway | None = None,
    job_id: str | None = None,
    gate: SchedulerGate | None = None,
    positions_db=None,
) -> SurveyReport:
    """Screen ``documents`` against ``criteria`` and extract ``attributes``.

    Parameters
    ----------
    question:
        The research question driving the survey.  Must be a non-empty string.
    documents:
        Corpus to screen.  Each element may be a ``Document`` dataclass or a
        plain dict with keys ``doc_id`` / ``id``, ``title``, ``text``.
        Duplicate ``doc_id`` values are silently deduplicated (first wins).
        Must contain at least one document.
    criteria:
        PRISMA-style screening criteria.  Each element may be a
        ``ScreeningCriterion`` dataclass or a plain dict with keys ``label``,
        ``keywords`` (list), ``exclude`` (bool).  An empty list means every
        document passes screening.
    attributes:
        Evidence table columns.  Each element may be an ``AttributeSpec``
        dataclass or a plain dict with keys ``label``, ``keywords`` (list).
        Must contain at least one attribute.
    gateway:
        Optional LLM gateway.  When ``None``, keyword heuristics are used and
        the run is fully deterministic and offline.
    job_id:
        Opaque job identifier threaded through to the gateway for logging.
    gate:
        Scheduler gate that throttles LLM calls; ignored when ``gateway=None``.
    positions_db:
        Optional positions database; when provided the summary claim is
        recorded via ``verification.positions.record_position``.

    Returns
    -------
    SurveyReport
        Fully populated report including screening decisions, evidence rows,
        PRISMA flow counts, and a human-readable summary claim.

    Raises
    ------
    ValueError
        If ``question`` is empty, ``documents`` is empty (after deduplication),
        or ``attributes`` is empty.
    """
    question = question.strip() if isinstance(question, str) else str(question)
    if not question:
        raise ValueError(
            "Survey 'question' must be a non-empty string; got an empty value.")

    docs = _coerce_documents(documents)
    crits = _coerce_criteria(criteria)
    attrs = _coerce_attributes(attributes)

    if not docs:
        raise ValueError(
            "Survey needs at least one document; 'documents' was empty.")
    if not attrs:
        raise ValueError(
            "Survey needs at least one attribute to extract; 'attributes' was empty.")

    # ------------------------------------------------------------------
    # Wire screening and extraction functions (offline vs LLM path).
    # ------------------------------------------------------------------
    if gateway is None:
        def screen_fn(d: Document) -> ScreenDecision:
            return _stub_screen(d, crits)

        def extract_fn(d: Document, a: AttributeSpec) -> str:
            return _stub_extract(d, a)
    else:
        def screen_fn(d: Document) -> ScreenDecision:
            return _llm_screen(gateway, question, d, crits, job_id=job_id, gate=gate)

        def extract_fn(d: Document, a: AttributeSpec) -> str:
            return _llm_extract(gateway, d, a, job_id=job_id, gate=gate)

    # ------------------------------------------------------------------
    # Screening pass.
    # ------------------------------------------------------------------
    decisions = [screen_fn(d) for d in docs]
    included_ids = {dec.doc_id for dec in decisions if dec.included}
    excluded_reasons = {
        dec.doc_id: dec.reason for dec in decisions if not dec.included
    }

    # ------------------------------------------------------------------
    # Extraction + entailment pass (included documents only).
    # ------------------------------------------------------------------
    rows: list[EvidenceRow] = []
    for doc in docs:
        if doc.doc_id not in included_ids:
            continue
        cells: list[EvidenceCell] = []
        missing: list[str] = []
        for attr in attrs:
            value = extract_fn(doc, attr)
            if value:
                score = _entailment.score_claim(value, doc.text)
                cells.append(EvidenceCell(
                    attribute=attr.label,
                    value=value,
                    citation_chunk_ids=(doc.doc_id,),
                    entailment_score=round(score, 3),
                    entailed=score >= _entailment.MINICHECK_THRESHOLD,
                ))
            else:
                missing.append(attr.label)
                cells.append(EvidenceCell(
                    attribute=attr.label,
                    value="",
                    citation_chunk_ids=(),
                    entailment_score=0.0,
                    entailed=False,
                ))
        rows.append(EvidenceRow(
            doc_id=doc.doc_id,
            title=doc.title,
            cells=cells,
            missing_attrs=missing,
        ))

    # ------------------------------------------------------------------
    # PRISMA accounting — internally consistent by construction.
    # ------------------------------------------------------------------
    n_identified = len(docs)
    n_included = len(included_ids)
    prisma = PrismaFlow(
        identified=n_identified,
        screened=n_identified,       # offline path screens every document
        included=n_included,
        excluded=n_identified - n_included,
        excluded_reasons=excluded_reasons,
    )

    claims = [
        f"{n_included} of {n_identified} documents met the criteria "
        f"for: {question}"
    ]
    if positions_db is not None:
        try:
            from ..verification.positions import record_position
            record_position(positions_db, claim=claims[0], probability=0.7)
        except Exception:
            pass

    return SurveyReport(
        question=question,
        criteria=crits,
        attributes=attrs,
        decisions=decisions,
        rows=rows,
        prisma=prisma,
        claims=claims,
    )
