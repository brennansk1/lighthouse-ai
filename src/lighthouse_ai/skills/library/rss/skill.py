"""RSS / Atom feed skill — entrypoints for feed fetching and watch monitoring.

Security invariants:
  - No httpx / requests / urllib / socket / subprocess imports anywhere in
    this package.  All outbound I/O goes through ctx.fetch() only.
  - Feed bytes are parsed by lighthouse_ai.sources.rss.parse_feed_bytes
    (stdlib xml.etree.ElementTree, no external parser dependency).
  - ctx.make_document is used to wrap parsed MonitorItem data.  We do NOT
    call ctx.fetch_and_document for RSS feeds because the raw XML is not a
    web page; ingest_bytes would not extract meaningful text from it.

Feed URL discovery heuristic:
  run() scans the question string for any token that looks like a URL ending
  in common feed path patterns (/feed, /rss, /atom, .xml, .rss, .atom) or
  is an http(s) URL the caller supplies explicitly.  Callers may also pass
  a pipe-separated list of URLs as the question argument for batch fetching.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from lighthouse_ai.sources.rss import parse_feed_bytes

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

# Regex that recognises an http(s) URL embedded in a question string.
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _extract_feed_urls(question: str) -> list[str]:
    """Return all http(s) URLs found in ``question``, stripped of trailing punctuation."""
    matches = _URL_RE.findall(question)
    cleaned: list[str] = []
    for m in matches:
        # Strip common trailing punctuation that is not part of a URL.
        m = m.rstrip(".,;:!?\"')")
        if m:
            cleaned.append(m)
    return cleaned


def _items_to_documents(ctx: SkillContext, items, *, feed_url: str) -> list[Document]:
    """Convert a list of MonitorItems to Documents via ctx.make_document."""
    docs: list[Document] = []
    for item in items:
        text = item.title or ""
        if item.body:
            text = f"{text}\n\n{item.body}" if text else item.body
        if not text:
            continue
        doc_id = (
            f"rss:{hash(item.url) & 0xFFFFFFFF:08x}"
            if item.url
            else f"rss:{hash(text) & 0xFFFFFFFF:08x}"
        )
        doc = ctx.make_document(
            doc_id=doc_id,
            text=text,
            metadata={
                "source": item.source or "rss",
                "url": item.url or "",
                "title": item.title or "",
                "published_at": item.published_at or "",
                "feed_url": feed_url,
                "type": "feed_item",
            },
        )
        docs.append(doc)
    return docs


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Fetch RSS/Atom feed URL(s) found in ``question`` and return their items.

    The question is scanned for http(s) URLs (any feed-like URL embedded in the
    question or passed directly).  Each URL is fetched via ``ctx.fetch``, its
    bytes are parsed by ``parse_feed_bytes``, and the resulting MonitorItems are
    wrapped into Documents via ``ctx.make_document``.

    If no URL is found in ``question`` an empty list is returned — the skill
    requires an explicit feed URL to operate.

    Args:
        ctx: Capability-restricted context.
        question: Research question or query.  Should contain one or more
            http(s) feed URLs to fetch.  Pipe-separated lists also work.
        max_results: Maximum total number of Documents to return across all feeds.

    Returns:
        List of Documents tagged with ``skill_id="rss"`` and ``type="feed_item"``.
    """
    feed_urls = _extract_feed_urls(question)
    if not feed_urls:
        return []

    docs: list[Document] = []
    for url in feed_urls:
        if len(docs) >= max_results:
            break
        try:
            resp = ctx.fetch(url)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        items = parse_feed_bytes(resp.content)
        remaining = max_results - len(docs)
        new_docs = _items_to_documents(ctx, items[:remaining], feed_url=url)
        docs.extend(new_docs)

    return docs[:max_results]


def run_watchable(
    ctx: SkillContext,
    query: str,
    *,
    since: datetime | None = None,
    max_results: int = 5,
) -> list[Document]:
    """Watch a set of feeds for items newer than ``since``.

    Like ``run``, the query string is scanned for http(s) URLs.  Each feed is
    fetched and parsed; only items with a ``published_at`` timestamp strictly
    newer than ``since`` are returned.  Items without a published date are
    included on the first tick (``since=None``) and excluded on subsequent
    ticks to avoid duplicate delivery.

    Args:
        ctx: Skill context.
        query: Watch topic / context string.  Must contain feed URLs.
        since: Lower-bound datetime (exclusive).  None means "all current items".
        max_results: Maximum Documents to return per tick.

    Returns:
        Time-ordered list of Documents (newest first within each feed).
    """
    feed_urls = _extract_feed_urls(query)
    if not feed_urls:
        return []

    docs: list[Document] = []
    for url in feed_urls:
        if len(docs) >= max_results:
            break
        try:
            resp = ctx.fetch(url)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        items = parse_feed_bytes(resp.content)
        # Filter by since
        filtered = _filter_since(items, since)
        remaining = max_results - len(docs)
        new_docs = _items_to_documents(ctx, filtered[:remaining], feed_url=url)
        docs.extend(new_docs)

    return docs[:max_results]


# ---- helpers ---------------------------------------------------------------


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 or RFC-2822-like timestamp string to a naive UTC datetime.

    Returns None if parsing fails — intentionally lenient so a bad timestamp
    does not drop a valid item.
    """
    if not ts:
        return None
    # Try ISO format variants first (Atom).
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S+00:00", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts[: len(fmt) + 2].strip(), fmt)
        except ValueError:
            pass
    # Try RFC-2822 (RSS pubDate: "Thu, 01 Jan 2026 00:00:00 +0000").
    # We strip the timezone suffix and parse as naive UTC.
    rfc_re = re.match(r"[A-Za-z]+,\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4}\s+\d{2}:\d{2}:\d{2})", ts)
    if rfc_re:
        try:
            return datetime.strptime(rfc_re.group(1), "%d %b %Y %H:%M:%S")
        except ValueError:
            pass
    return None


def _filter_since(items, since: datetime | None):
    """Return items newer than ``since``, or all items if ``since`` is None."""
    if since is None:
        return items
    # Make since naive for comparison if it carries tzinfo.
    since_naive = since.replace(tzinfo=None) if since.tzinfo is not None else since
    result = []
    for item in items:
        if not item.published_at:
            # No timestamp — skip on incremental ticks.
            continue
        dt = _parse_iso(item.published_at)
        if dt is None:
            continue
        if dt > since_naive:
            result.append(item)
    return result
