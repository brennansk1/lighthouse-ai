"""Sandbox analysis tools (SB2) — the only way an LLM may analyze sandbox data.

The Sandbox lets the user store data and the LLM analyze it. The LLM does **not**
run arbitrary code: it calls a small set of *vetted, named tools* exposed by
:class:`SandboxAnalysisContext`, exactly the same capability-restriction
discipline the skill runner uses for web fetches. The context exposes only:

  * ``list_items`` / ``read_document`` / ``search_text``
  * ``extract_tables`` / ``extract_entities`` / ``basic_stats``
  * ``summarize`` (optional gateway; deterministic extractive fallback)
  * ``write_artifact`` (workspace zone only)

Security guarantees enforced here (and tested):

  * **No raw I/O surface.** This module imports no ``httpx``/``socket``/
    ``subprocess``/``open``-on-arbitrary-paths. Every read goes through
    :meth:`SandboxStore.read` (which is broker-verdict + path-containment gated)
    and is addressed by opaque ``item_id`` — never a caller-supplied path.
  * **Admitted-only reads.** Quarantined items are not readable through this
    surface (``read`` is called without the quarantine opt-in); rejected items
    never exist in the store.
  * **Uploads are read-only.** The only writer is :meth:`write_artifact`, which
    routes to :meth:`SandboxStore.write_artifact` — hard-wired to the
    ``workspace`` zone. There is no parameter with which the LLM could target
    ``uploads``.
  * **Audited.** Every tool call emits an audit line via the optional hook.

Determinism / offline: no ``datetime.now()`` at import; ``write_artifact`` takes
``now=``. ``summarize`` works fully offline (extractive) and only uses the
gateway when one is supplied.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog

from ..ingest import extract_text

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .broker import SandboxBroker
    from .store import SandboxItem, SandboxStore

log = structlog.get_logger(__name__)

AuditHook = Callable[[dict[str, Any]], None]

# --- lightweight deterministic extractors (no models) ----------------------

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")
_DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b"
)
_NUMBER_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s?(?:%|kg|km|m|s|GB|MB|USD|\$)?\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_URL_RE = re.compile(r"\bhttps?://[^\s)]+", re.IGNORECASE)
_CAP_PHRASE_RE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9]+)(?:\s+[A-Z][a-zA-Z0-9]+){0,3}\b")

# Common English stopwords for the top-terms statistic (kept tiny + offline).
_STOPWORDS = frozenset(
    ["the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with", "at", "by", "from", "as", "is", "are", "was", "were", "be", "been", "being", "this", "that", "these", "those", "it", "its", "he", "she", "they", "we", "you", "i", "not", "no", "can", "will", "would", "could", "should", "may", "might", "must", "do", "does", "did", "have", "has", "had", "how", "what", "when", "which", "who", "whom", "whose", "than", "then", "there", "here", "their", "our", "your", "his", "her", "them", "us"]
)


class SandboxAnalysisError(RuntimeError):
    """Raised for analysis-tool misuse (unknown item, etc.)."""


class SandboxAnalysisContext:
    """Capability-restricted analysis surface over a :class:`SandboxStore`.

    Construct one per analysis session. ``gateway`` is optional (only the
    ``summarize`` tool uses it, and it degrades to an extractive summary when
    absent). ``audit`` receives one record per tool call.
    """

    def __init__(
        self,
        store: SandboxStore,
        *,
        gateway: Any | None = None,
        audit: AuditHook | None = None,
        job_id: str | None = None,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.audit = audit
        self.job_id = job_id

    # -- audit ---------------------------------------------------------------

    def _emit(self, tool: str, **fields: Any) -> None:
        record = {"event": "sandbox.analysis", "tool": tool, "job_id": self.job_id, **fields}
        log.info("sandbox.analysis", tool=tool, job_id=self.job_id, **fields)
        if self.audit is not None:
            self.audit(record)

    # -- internal: load an admitted item's text ------------------------------

    def _item(self, item_id: str) -> SandboxItem:
        item = self.store.stat(item_id)
        if item is None:
            raise SandboxAnalysisError(f"unknown sandbox item: {item_id!r}")
        return item

    def _text(self, item_id: str) -> str:
        """Extracted text for an ADMITTED item (quarantined/rejected refused)."""
        item = self._item(item_id)
        payload = self.store.read(item_id)  # admitted-only; raises otherwise
        return extract_text(payload, item.content_type, item.filename)

    # -- tools ---------------------------------------------------------------

    def list_items(self, zone: str | None = None) -> list[dict[str, Any]]:
        """Safe summaries of stored items (optionally one zone)."""
        self._emit("list_items", zone=zone)
        items = self.store.list(zone)  # type: ignore[arg-type]
        return [
            {
                "id": it.id,
                "zone": it.zone,
                "filename": it.filename,
                "content_type": it.content_type,
                "size_bytes": it.size_bytes,
                "source": it.source,
                "scan_verdict": it.scan_verdict,
                "preview_type": it.preview_type,
                "pinned": it.pinned,
            }
            for it in items
            if not it.evicted
        ]

    def read_document(self, item_id: str) -> str:
        """Return the extracted TEXT of an admitted item (never raw bytes)."""
        self._emit("read_document", item_id=item_id)
        return self._text(item_id)

    def search_text(
        self,
        query: str,
        *,
        zone: str | None = None,
        max_hits: int = 20,
        snippet_chars: int = 160,
    ) -> list[dict[str, Any]]:
        """Case-insensitive substring search across admitted items' text.

        Quarantined/binary/unreadable items are skipped silently (they raise on
        read; we never surface their content). Returns up to ``max_hits`` hits,
        each with the item id, filename, char offset, and a snippet.
        """
        self._emit("search_text", query=query, zone=zone)
        needle = query.strip().lower()
        hits: list[dict[str, Any]] = []
        if not needle:
            return hits
        for it in self.store.list(zone):  # type: ignore[arg-type]
            if it.evicted or it.scan_verdict != "admit" or it.preview_type != "text":
                continue
            try:
                text = self._text(it.id)
            except (PermissionError, FileNotFoundError, OSError):
                continue
            hay = text.lower()
            start = 0
            while len(hits) < max_hits:
                idx = hay.find(needle, start)
                if idx < 0:
                    break
                lo = max(0, idx - snippet_chars // 2)
                hi = min(len(text), idx + len(needle) + snippet_chars // 2)
                hits.append(
                    {
                        "item_id": it.id,
                        "filename": it.filename,
                        "offset": idx,
                        "snippet": text[lo:hi].replace("\n", " ").strip(),
                    }
                )
                start = idx + len(needle)
            if len(hits) >= max_hits:
                break
        return hits

    def extract_tables(self, item_id: str) -> list[list[list[str]]]:
        """Deterministic table extraction (Markdown pipe-tables + CSV-ish)."""
        self._emit("extract_tables", item_id=item_id)
        text = self._text(item_id)
        return _extract_tables(text)

    def extract_entities(self, item_id: str) -> list[dict[str, str]]:
        """Lightweight heuristic entity extraction (no model)."""
        self._emit("extract_entities", item_id=item_id)
        text = self._text(item_id)
        return _extract_entities(text)

    def basic_stats(self, item_id: str) -> dict[str, Any]:
        """Char/word/line counts, top terms, table count for an item."""
        self._emit("basic_stats", item_id=item_id)
        text = self._text(item_id)
        words = _WORD_RE.findall(text)
        terms = Counter(
            w.lower() for w in words if w.lower() not in _STOPWORDS and len(w) > 2
        )
        return {
            "chars": len(text),
            "words": len(words),
            "lines": text.count("\n") + 1 if text else 0,
            "tables": len(_extract_tables(text)),
            "top_terms": [{"term": t, "count": c} for t, c in terms.most_common(15)],
        }

    def summarize(self, item_id: str, *, max_sentences: int = 5) -> str:
        """Summarize an item. Uses the gateway when present, else extractive.

        The deterministic fallback returns the first ``max_sentences`` salient
        sentences (longest, earliest), so it works fully offline.
        """
        self._emit("summarize", item_id=item_id, backend="llm" if self.gateway else "extractive")
        text = self._text(item_id)
        gw = self.gateway
        if gw is not None:
            try:
                if not hasattr(gw, "available") or gw.available():
                    out = gw.complete(  # type: ignore[union-attr]
                        "synthesizer",
                        f"Summarize the following document in {max_sentences} sentences:\n\n{text[:6000]}",
                        job_id=self.job_id,
                    )
                    if isinstance(out, str) and out.strip():
                        return out.strip()
            except Exception as exc:
                log.warning("sandbox.summarize_llm_failed", error=repr(exc))
        return _extractive_summary(text, max_sentences)

    def write_artifact(
        self,
        name: str,
        text: str,
        *,
        broker: SandboxBroker,
        now: str,
        source: str = "analysis",
        pinned: bool = False,
    ) -> dict[str, Any]:
        """Write an analysis result into the WORKSPACE zone (never uploads).

        Goes through :meth:`SandboxStore.write_artifact`, which is hard-wired to
        the workspace zone and broker-gated — so an analysis tool can never write
        into the user's uploads.
        """
        self._emit("write_artifact", name=name)
        item = self.store.write_artifact(
            text.encode("utf-8"),
            filename=name,
            content_type="text/plain",
            source=source,
            broker=broker,
            now=now,
            pinned=pinned,
        )
        if item is None:
            raise SandboxAnalysisError(f"artifact {name!r} was rejected by the broker")
        return item.as_dict()


# --------------------------------------------------------------------------- #
# Deterministic extractor helpers (pure functions, model-free)
# --------------------------------------------------------------------------- #


def _extract_tables(text: str) -> list[list[list[str]]]:
    """Parse Markdown pipe-tables and contiguous CSV-ish blocks into grids."""
    tables: list[list[list[str]]] = []
    lines = text.splitlines()

    # 1) Markdown pipe tables: runs of lines containing '|'.
    block: list[str] = []

    def _flush_pipe(rows: list[str]) -> None:
        grid = []
        for row in rows:
            if set(row.strip()) <= set("|-: "):  # separator row
                continue
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            grid.append(cells)
        if len(grid) >= 2:
            tables.append(grid)

    for ln in lines:
        if ln.count("|") >= 2:
            block.append(ln)
        else:
            if len(block) >= 2:
                _flush_pipe(block)
            block = []
    if len(block) >= 2:
        _flush_pipe(block)

    # 2) CSV-ish blocks: runs of lines with a consistent comma count (>=1).
    csv_block: list[str] = []

    def _flush_csv(rows: list[str]) -> None:
        if len(rows) < 2:
            return
        counts = {r.count(",") for r in rows}
        if len(counts) == 1 and 0 not in counts:
            tables.append([[c.strip() for c in r.split(",")] for r in rows])

    for ln in lines:
        if "," in ln and "|" not in ln:
            csv_block.append(ln)
        else:
            _flush_csv(csv_block)
            csv_block = []
    _flush_csv(csv_block)

    return tables


def _extract_entities(text: str) -> list[dict[str, str]]:
    """Heuristic entities: dates, numbers/units, emails, urls, capitalized phrases."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []

    def _add(kind: str, value: str) -> None:
        value = value.strip()
        if not value:
            return
        key = (kind, value)
        if key in seen:
            return
        seen.add(key)
        out.append({"type": kind, "value": value})

    for m in _DATE_RE.findall(text):
        _add("date", m)
    for m in _EMAIL_RE.findall(text):
        _add("email", m)
    for m in _URL_RE.findall(text):
        _add("url", m)
    for m in _CAP_PHRASE_RE.findall(text):
        if " " in m:  # multi-word capitalized phrases are higher-signal
            _add("name", m)
    # Numbers last (noisiest); cap to keep output sane.
    for m in _NUMBER_RE.findall(text)[:50]:
        _add("number", m)
    return out


def _extractive_summary(text: str, max_sentences: int) -> str:
    """First-N salient sentences (earliest, non-trivial) — deterministic."""
    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if len(s.strip()) > 30]
    if not sentences:
        # Fall back to the leading characters when there are no clear sentences.
        return text.strip()[:500]
    return " ".join(sentences[:max_sentences])
