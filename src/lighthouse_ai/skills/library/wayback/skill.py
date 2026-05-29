"""Wayback Machine skill — entrypoint for historical web retrieval.

Security invariants:
  - No httpx / requests / urllib / socket / subprocess imports anywhere in
    this package.  All outbound I/O goes through ctx.fetch() or
    ctx.fetch_and_document().
  - CDX JSON is parsed with stdlib json only; no external parser.
  - All URL encoding is done with the skill's own _pct_encode helper (stdlib).

run() strategy:
  1. Scan ``question`` for http(s) URLs.
  2. For each URL call lookup_url_at_date using today's date hint embedded in
     the question (or use the most-recent snapshot if no date is found).
  3. Return Documents tagged with Wayback provenance.

Callers that want fine-grained control (specific timestamp, list snapshots,
submit for archiving) should import the individual tool functions directly.

No datetime.now() at module level (constraint: deterministic offline).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .tools.fetch_snapshot import fetch_snapshot
from .tools.list_snapshots import list_snapshots
from .tools.lookup_url_at_date import lookup_url_at_date
from .tools.submit_for_archiving import submit_for_archiving

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

# Expose the tool functions as module-level names so the runner can find them.
__all__ = [
    "fetch_snapshot",
    "list_snapshots",
    "lookup_url_at_date",
    "run",
    "submit_for_archiving",
]

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
# Date pattern: YYYY-MM-DD or YYYYMMDD
_DATE_RE = re.compile(r"\b(\d{4}[-/]?\d{2}[-/]?\d{2})\b")


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Retrieve Wayback snapshots for URLs and optional dates found in ``question``.

    Scans ``question`` for http(s) URLs (excluding archive.org URLs) and an
    optional date hint (``YYYY-MM-DD``).  For each URL fetches the closest
    Wayback snapshot to the date hint (or the most-recent snapshot when no
    date is present).  Returns broker-admitted Documents.

    Args:
        ctx: Capability-restricted context.
        question: Research question or query.  Should contain one or more
            original (non-Wayback) http(s) URLs.  May contain a date hint
            in ``YYYY-MM-DD`` format.
        max_results: Maximum number of Documents to return.

    Returns:
        List of Documents tagged ``skill_id="wayback"`` and ``source="wayback"``.
    """
    urls = _extract_target_urls(question)
    if not urls:
        return []

    date_hint = _extract_date(question)
    # Default to a broad "most recent" query when no date is found in question.
    ts_hint = _normalize_date(date_hint) if date_hint else "20991231000000"

    docs: list[Document] = []
    for url in urls[:max_results]:
        doc = lookup_url_at_date(ctx, url, ts_hint, fetch_content=True)
        if doc is not None:
            docs.append(doc)
        if len(docs) >= max_results:
            break

    return docs


# ---- helpers ---------------------------------------------------------------

def _extract_target_urls(question: str) -> list[str]:
    """Return non-Wayback http(s) URLs found in ``question``."""
    matches = _URL_RE.findall(question)
    result: list[str] = []
    for m in matches:
        m = m.rstrip(".,;:!?\"')")
        if not m:
            continue
        # Skip archive.org / web.archive.org URLs (those are already snapshots).
        lower = m.lower()
        if "archive.org" in lower:
            continue
        result.append(m)
    return result


def _extract_date(question: str) -> str | None:
    """Return the first date-like substring found in ``question``, or None."""
    m = _DATE_RE.search(question)
    return m.group(1) if m else None


def _normalize_date(date_str: str) -> str:
    """Convert a date string to a 14-digit CDX timestamp."""
    digits = "".join(c for c in date_str if c.isdigit())
    return digits.ljust(14, "0")[:14]
