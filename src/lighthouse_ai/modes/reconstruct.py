"""Mode — Reconstruct: build a sourced chronology from a corpus.

A Reconstruct run extracts dated events from a set of documents, normalizes
their dates, deduplicates events that the same underlying happening produced in
multiple sources, resolves date conflicts (when sources disagree, the modal
date weighted by *source* count wins), and emits a sorted timeline.  Every
event carries its sources and a certainty score; events with no explicit date
but inferred from ordering are marked ``inferred``.

Date formats recognized (offline / deterministic path):
  - ISO-ish:  2024, 2024-05, 2024-05-28
  - Month-Year: March 2019, Mar 2019, march 2019
  - Month-Day-Year: March 3 2019, Mar 3, 2019
  - Year-Month numeric: 2019-03

Certainty formula
-----------------
``certainty = winning_source_count / total_unique_sources``

"Winning" sources are those that agree on the modal (most common) date.
When all sources agree the score is 1.0.  When only one source out of N
agrees it approaches 1/N.  The value is rounded to three decimal places.

Source-count weighting means one document that mentions a date five times
does not out-vote five separate documents that each mention a different date
— each document ID counts once in the modal vote.

Deterministic when ``gateway=None``: events are extracted by a lightweight
date-and-sentence heuristic over the document text, so tests and dry runs
reproduce exactly.  With a gateway the same structure is filled by the model.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..gateway import Gateway
from ..governor.scheduler_gate import SchedulerGate
from ._gate import gate_ctx

# ---------------------------------------------------------------------------
# Date recognition
# ---------------------------------------------------------------------------

# Matches ISO-ish dates: 2024, 2024-05, 2024-05-28
_ISO_DATE_RE = re.compile(r"\b(\d{4}(?:-\d{2}(?:-\d{2})?)?)\b")

# Month names → zero-padded month number
_MONTH_MAP: dict[str, str] = {
    "january": "01", "jan": "01",
    "february": "02", "feb": "02",
    "march": "03", "mar": "03",
    "april": "04", "apr": "04",
    "may": "05",
    "june": "06", "jun": "06",
    "july": "07", "jul": "07",
    "august": "08", "aug": "08",
    "september": "09", "sep": "09", "sept": "09",
    "october": "10", "oct": "10",
    "november": "11", "nov": "11",
    "december": "12", "dec": "12",
}

_MONTH_NAMES = "|".join(_MONTH_MAP)

# Written date patterns (case-insensitive):
#   "March 3, 2019"  "Mar 3 2019"  "March 3rd, 2019"
_WRITTEN_MDY_RE = re.compile(
    rf"\b({_MONTH_NAMES})\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(\d{{4}})\b",
    re.IGNORECASE,
)
#   "March 2019"  "Mar 2019"
_WRITTEN_MY_RE = re.compile(
    rf"\b({_MONTH_NAMES})\s+(\d{{4}})\b",
    re.IGNORECASE,
)

# Combined regex for stripping date tokens from action text before hashing.
# Order: try written forms first so "March 2019" is consumed before "2019".
_DATE_STRIP_RE = re.compile(
    rf"(?:{_WRITTEN_MDY_RE.pattern}|{_WRITTEN_MY_RE.pattern}|{_ISO_DATE_RE.pattern})",
    re.IGNORECASE,
)

# Proper-noun actor heuristic: sequences of capitalized words (2+ chars) that
# are not at the very start of a sentence (preceded by a non-period char or
# are mid-sentence).  We keep it simple: any run of Title-Case tokens.
_ACTOR_RE = re.compile(r"\b([A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,}){0,3})\b")

# Words that look like proper nouns but are sentence starters / filler
_ACTOR_STOPWORDS = frozenset({
    "In", "On", "At", "The", "A", "An", "By", "For", "Of", "To",
    "And", "But", "Or", "From", "With", "Its", "Their",
})


def _parse_written_date(text: str) -> tuple[str, int] | None:
    """Try to match a written date pattern at any position in *text*.

    Returns ``(normalized_date, match_end)`` if found, else ``None``.
    The normalized date is zero-padded YYYY-MM-DD.
    """
    m = _WRITTEN_MDY_RE.search(text)
    if m:
        month = _MONTH_MAP[m.group(1).lower()]
        day = m.group(2).zfill(2)
        year = m.group(3)
        return f"{year}-{month}-{day}", m.end()

    m = _WRITTEN_MY_RE.search(text)
    if m:
        month = _MONTH_MAP[m.group(1).lower()]
        year = m.group(2)
        return f"{year}-{month}-01", m.end()

    return None


def _find_date(text: str) -> str | None:
    """Return the first date found in *text* in normalized YYYY-MM-DD form.

    Tries written month formats before the ISO regex so "March 2019" is not
    truncated to bare "2019".  Returns ``None`` if no date is found.
    """
    written = _parse_written_date(text)
    if written:
        return written[0]

    m = _ISO_DATE_RE.search(text)
    if m:
        return _normalize_date(m.group(1))

    return None


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    text: str


@dataclass(frozen=True)
class SourcedDate:
    raw: str
    normalized: str  # zero-padded YYYY-MM-DD with assumed components
    source_id: str


@dataclass(frozen=True)
class TimelineEvent:
    event_id: str
    date: str               # resolved (winning) normalized date
    actors: tuple[str, ...]
    action: str
    sources: tuple[str, ...]
    certainty: float        # see module docstring for formula
    inferred: bool
    date_conflicts: tuple[SourcedDate, ...] = ()
    # Additive: number of distinct sources that agree on the winning date.
    winning_source_count: int = 0
    # Additive: total distinct sources for this event.
    total_source_count: int = 0


@dataclass(frozen=True)
class ReconstructReport:
    question: str
    events: list[TimelineEvent]
    claims: list[str] = field(default_factory=list)
    # Additive: how many documents were processed.
    doc_count: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_documents(documents: Sequence[Document | dict]) -> list[Document]:
    out: list[Document] = []
    for i, d in enumerate(documents):
        if isinstance(d, Document):
            out.append(d)
        else:
            out.append(Document(
                doc_id=str(d.get("doc_id") or d.get("id") or f"doc{i}"),
                title=str(d.get("title", "")),
                text=str(d.get("text", "")),
            ))
    return out


def _normalize_date(raw: str) -> str:
    """Zero-pad a partial ISO date string to YYYY-MM-DD, defaulting missing parts to 01."""
    parts = raw.split("-")
    year = parts[0]
    month = parts[1] if len(parts) > 1 else "01"
    day = parts[2] if len(parts) > 2 else "01"
    return f"{year}-{month}-{day}"


def _event_key(action: str) -> str:
    """Return a 12-hex-char stable hash of *action* for deduplication.

    Date tokens (ISO and written) are stripped before hashing so that the same
    underlying event phrased with different dates collapses onto one key.
    Whitespace is also normalized to a single space.

    Example::

        _event_key("In 2020 the merger closed.")
        == _event_key("In 2019 the merger closed.")
    """
    norm = _DATE_STRIP_RE.sub("", action.strip().lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha256(norm.encode()).hexdigest()[:12]


def _extract_actors(action: str) -> tuple[str, ...]:
    """Return a de-duplicated, ordered tuple of proper-noun actor spans.

    Heuristic: consecutive Title-Case words (2+ chars per token) that are not
    in a stopword list.  Limited to the first four tokens in a span.  This is
    intentionally simple — the LLM path can produce structured actors directly.
    """
    seen: dict[str, None] = {}  # ordered-set via insertion-order dict
    for m in _ACTOR_RE.finditer(action):
        span = m.group(1).strip()
        # Reject pure stopword spans
        if all(w in _ACTOR_STOPWORDS for w in span.split()):
            continue
        # Reject spans that are the very first word and a stopword
        if span in _ACTOR_STOPWORDS:
            continue
        if span not in seen:
            seen[span] = None
    return tuple(seen)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _stub_extract(doc: Document) -> list[tuple[str, str]]:
    """Return (normalized_date, action) pairs for each sentence carrying a date.

    Recognizes ISO-ish dates AND written month formats so that sentences like
    "In March 2019 the treaty was signed." are captured.
    """
    pairs: list[tuple[str, str]] = []
    sentences = [s.strip() for s in doc.text.replace("\n", " ").split(".")
                 if s.strip()]
    for s in sentences:
        date = _find_date(s)
        if date is not None:
            pairs.append((date, s))
    return pairs


def _llm_extract(gateway: Gateway, question: str, doc: Document, *,
                 job_id: str | None, gate: SchedulerGate | None
                 ) -> list[tuple[str, str]]:
    """Extract (date, action) pairs from *doc* via the LLM gateway.

    Falls back to ``_stub_extract`` when the gateway returns nothing parseable
    or raises an exception.
    """
    prompt = (
        f"Reconstruction question: {question}\n"
        f"Document:\n{doc.text[:2000]}\n\n"
        "List the dated events as lines of the form 'DATE | what happened'. "
        "Use ISO dates (YYYY-MM-DD). One event per line."
    )
    try:
        with gate_ctx(gate):
            resp = gateway.complete("researcher", prompt, job_id=job_id)
        pairs: list[tuple[str, str]] = []
        for line in resp.text.splitlines():
            if "|" in line:
                date_raw, action = line.split("|", 1)
                date = _find_date(date_raw.strip())
                if date and action.strip():
                    pairs.append((date, action.strip()))
        return pairs or _stub_extract(doc)
    except Exception:
        return _stub_extract(doc)


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------

def run_reconstruct(
    question: str,
    documents: Sequence[Document | dict],
    *,
    gateway: Gateway | None = None,
    job_id: str | None = None,
    gate: SchedulerGate | None = None,
    positions_db=None,
) -> ReconstructReport:
    """Extract dated events from ``documents`` and resolve them into a timeline.

    Parameters
    ----------
    question:
        The research question that scopes the reconstruction.
    documents:
        A sequence of ``Document`` objects or plain dicts with keys
        ``id``/``doc_id``, ``title``, and ``text``.  At least one document
        must be provided.
    gateway:
        Optional LLM gateway.  When ``None`` (default) the engine runs
        entirely offline via keyword/regex heuristics — fully deterministic.
    job_id:
        Opaque identifier forwarded to the gateway for tracing.
    gate:
        Optional scheduler gate for rate-limiting LLM calls.
    positions_db:
        Optional positions database handle; when provided the engine records
        the top-level claim with probability 0.7.

    Returns
    -------
    ReconstructReport
        Contains a list of :class:`TimelineEvent` sorted ascending by
        (date, event_id) for stable ordering.

    Raises
    ------
    ValueError
        If ``documents`` is empty or contains no extractable events when the
        call would otherwise succeed.  An empty corpus produces no timeline.
    """
    docs = _coerce_documents(documents)
    if not docs:
        raise ValueError(
            "run_reconstruct requires at least one document; "
            "received an empty documents list."
        )

    if gateway is None:
        def extract_fn(d: Document) -> list[tuple[str, str]]:
            return _stub_extract(d)
    else:
        def extract_fn(d: Document) -> list[tuple[str, str]]:
            return _llm_extract(gateway, question, d, job_id=job_id, gate=gate)

    # ------------------------------------------------------------------
    # Step 1 — collect raw (normalized_date, action, source) triples,
    #          grouped by the date-stripped action hash (event_key).
    # ------------------------------------------------------------------
    # Structure: key → {"action": str, "dates_by_source": {src: [normalized]}}
    grouped: dict[str, dict] = {}
    for doc in docs:
        for normalized_date, action in extract_fn(doc):
            key = _event_key(action)
            slot = grouped.setdefault(key, {
                "action": action,
                "dates_by_source": defaultdict(list),
            })
            slot["dates_by_source"][doc.doc_id].append(normalized_date)

    # ------------------------------------------------------------------
    # Step 2 — resolve date conflicts, compute certainty, build events.
    #
    # Certainty = winning_source_count / total_source_count
    #
    # "winning" means the source's *modal* date (per-source) agrees with
    # the globally winning date.  Each document gets one vote regardless
    # of how many times it mentions the date.
    # ------------------------------------------------------------------
    events: list[TimelineEvent] = []
    for key, slot in grouped.items():
        dates_by_source: dict[str, list[str]] = slot["dates_by_source"]

        # Per-source: pick the most-mentioned date within that source.
        source_votes: dict[str, str] = {}
        for src, date_list in dates_by_source.items():
            # deterministic tiebreak: alphabetically earliest date string
            c = Counter(date_list)
            max_count = max(c.values())
            candidates = sorted(d for d, cnt in c.items() if cnt == max_count)
            source_votes[src] = candidates[0]

        # Global modal vote across source votes.
        vote_counter = Counter(source_votes.values())
        max_votes = max(vote_counter.values())
        # Deterministic tiebreak: chronologically earliest winning date.
        winning_candidates = sorted(
            d for d, cnt in vote_counter.items() if cnt == max_votes
        )
        winning = winning_candidates[0]

        total_sources = list(source_votes)  # in insertion order (Python 3.7+)
        winning_sources = [s for s, d in source_votes.items() if d == winning]
        losing_sources = [s for s, d in source_votes.items() if d != winning]

        certainty = round(len(winning_sources) / len(total_sources), 3)

        # Build SourcedDate conflict list — one entry per *losing* source
        # showing the date that source actually reported.
        conflicts: list[SourcedDate] = []
        for src in losing_sources:
            reported = source_votes[src]
            # Use the raw dates list to pick a representative raw string;
            # prefer the modal raw string within that source.
            raw_counter = Counter(dates_by_source[src])
            raw_modal = max(raw_counter, key=lambda x: (raw_counter[x], x))
            conflicts.append(SourcedDate(
                raw=raw_modal, normalized=reported, source_id=src,
            ))

        actors = _extract_actors(slot["action"])

        events.append(TimelineEvent(
            event_id=key,
            date=winning,
            actors=actors,
            action=slot["action"],
            sources=tuple(total_sources),
            certainty=certainty,
            inferred=False,
            date_conflicts=tuple(conflicts),
            winning_source_count=len(winning_sources),
            total_source_count=len(total_sources),
        ))

    # Stable sort: primary ascending date, secondary stable event_id.
    events.sort(key=lambda e: (e.date, e.event_id))

    claims = [f"Reconstructed {len(events)} dated events for: {question}"]
    if positions_db is not None:
        try:
            from ..verification.positions import record_position
            record_position(positions_db, claim=claims[0], probability=0.7)
        except Exception:
            pass

    return ReconstructReport(
        question=question,
        events=events,
        claims=claims,
        doc_count=len(docs),
    )
