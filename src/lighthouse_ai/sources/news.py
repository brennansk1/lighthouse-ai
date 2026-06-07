"""Shared news adapter — generic RSS/web helpers for the per-outlet news skills.

This module lives under ``sources/`` (not inside a skill folder) so the
registry import guard does NOT scan it.  Skills import it as::

    from lighthouse_ai.sources import news as _news

and call it through ``SkillContext`` primitives — **skills must not call
this module's network functions directly**; they pass ``ctx.fetch`` as the
``client`` parameter so all traffic flows through the capability surface.

Public API (stable for SL12 News Orchestrator):
------------------------------------------------
``fetch_outlet_feed(feed_url, *, client=None, max_results=20) -> list[MonitorItem]``
    Fetch an RSS/Atom feed URL and return parsed MonitorItem records.
    ``client`` is a callable with signature ``(url: str) -> httpx.Response``
    — pass ``ctx.fetch`` from inside a skill.  If ``client`` is None a bare
    ``httpx.Client`` is used (allowed from inside ``sources/``).

``search_outlet(base_url, query, *, client=None, max_results=10) -> list[MonitorItem]``
    Minimal web-search stub for outlets that expose a ``?q=`` or ``?query=``
    search endpoint.  Returns MonitorItem records parsed from the HTML/JSON
    response via a best-effort extractor.  Falls back to empty list on any
    error.

``parse_feed_bytes(payload: bytes) -> list[MonitorItem]``
    Re-export of the existing RSS parser so skills can import one module.

``items_to_documents(ctx, items, *, outlet_id, feed_url="") -> list[Document]``
    Convert MonitorItem records to broker-tagged Documents via
    ``ctx.make_document``.  Skills call this after ``fetch_outlet_feed``.

``EgressBlocked``
    Sentinel exception re-exported here; skills import it to degrade gracefully
    when the egress proxy denies a fetch.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from lighthouse_ai.modes.monitor import MonitorItem

# Re-export the existing RSS parser bytes function so callers only need one
# import from this module.
from lighthouse_ai.sources.rss import parse_feed_bytes

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

# ---------------------------------------------------------------------------
# EgressBlocked — imported by skills that want to degrade gracefully
# ---------------------------------------------------------------------------

try:
    from lighthouse_ai.net import EgressBlocked
except ImportError:  # pragma: no cover — net module may not define this yet
    class EgressBlocked(Exception):  # type: ignore[no-redef]
        """Raised when the egress proxy denies a fetch."""


# ---------------------------------------------------------------------------
# Egress allowlist
# ---------------------------------------------------------------------------

# News is the "point at any outlet" channel: the per-outlet skills register the
# feed / search URLs, so this shared adapter has no fixed API host of its own.
# Passing ``allowed_domains`` as ``None`` defers to the platform egress
# allowlist (``DEFAULT_ALLOWED_DOMAINS``) as the ceiling — matching the rss
# skill manifest, which declares ``allowed_domains = []`` for the same reason
# (a registered outlet reaches whatever the platform already permits, never
# wider). The guard still enforces decide-before-fetch, audit logging, and the
# ``LIGHTHOUSE_AIRGAP`` kill before any socket opens.
_ALLOWED_HOSTS: frozenset[str] | None = None


# ---------------------------------------------------------------------------
# HTML stripping helpers
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s{2,}")


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", _HTML_TAG_RE.sub(" ", text)).strip()


# ---------------------------------------------------------------------------
# Core: fetch and parse an RSS/Atom feed
# ---------------------------------------------------------------------------


def fetch_outlet_feed(
    feed_url: str,
    *,
    client=None,
    max_results: int = 20,
) -> list[MonitorItem]:
    """Fetch ``feed_url`` and return up to ``max_results`` parsed MonitorItems.

    Parameters
    ----------
    feed_url:
        Full URL of the RSS or Atom feed to fetch.
    client:
        A callable ``(url: str) -> response`` — pass ``ctx.fetch`` from inside
        a skill so traffic flows through the capability surface.  If ``None``
        a bare ``httpx.Client`` is created here (allowed in ``sources/`` which
        is not scanned by the import guard).
    max_results:
        Maximum items to return.

    Returns
    -------
    list[MonitorItem]
        Parsed feed items; empty list on any error (network, parse, egress block).
    """
    try:
        if client is not None:
            resp = client(feed_url)
            payload = resp.content if hasattr(resp, "content") else b""
            status = resp.status_code if hasattr(resp, "status_code") else 200
        else:
            import httpx  # allowed in sources/ — not inside skill scan

            from lighthouse_ai.net import guarded_get
            with httpx.Client(timeout=30.0, follow_redirects=True) as hx:
                r = guarded_get(
                    feed_url,
                    allowed_domains=_ALLOWED_HOSTS,
                    headers={"User-Agent": "Lighthouse/0.1"},
                    client=hx,
                )
            payload = r.content
            status = r.status_code

        if status != 200:
            return []
        items = parse_feed_bytes(payload)
        return items[:max_results]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# search_outlet — best-effort query against a web search endpoint
# ---------------------------------------------------------------------------


def search_outlet(
    base_url: str,
    query: str,
    *,
    client=None,
    max_results: int = 10,
) -> list[MonitorItem]:
    """Search an outlet's website by appending ``?q=query`` to ``base_url``.

    Many news outlets expose a simple ``?q=`` or ``?query=`` search form.
    This function tries both parameter names, parses the HTML response for
    ``<article>`` / ``<h2>`` / ``<a>`` link patterns, and returns MonitorItem
    records.  Intended as a best-effort supplement to feed fetching; it
    degrades gracefully to an empty list on any error.

    Parameters
    ----------
    base_url:
        The outlet's search endpoint URL (without a query string).
    query:
        Search terms.
    client:
        ``ctx.fetch`` callable or None.
    max_results:
        Maximum results to return.
    """
    import urllib.parse  # stdlib — allowed in sources/

    for param in ("q", "query", "search"):
        url = f"{base_url}?{urllib.parse.urlencode({param: query})}"
        try:
            if client is not None:
                resp = client(url)
                payload = resp.content if hasattr(resp, "content") else b""
                status = resp.status_code if hasattr(resp, "status_code") else 200
            else:
                import httpx

                from lighthouse_ai.net import guarded_get
                with httpx.Client(timeout=30.0, follow_redirects=True) as hx:
                    r = guarded_get(
                        url,
                        allowed_domains=_ALLOWED_HOSTS,
                        headers={"User-Agent": "Lighthouse/0.1"},
                        client=hx,
                    )
                payload = r.content
                status = r.status_code

            if status != 200:
                continue

            items = _extract_links_from_html(payload.decode("utf-8", errors="replace"), base_url)
            if items:
                return items[:max_results]
        except Exception:
            continue

    return []


def _extract_links_from_html(html: str, base_url: str) -> list[MonitorItem]:
    """Heuristic: extract ``<a href>`` links with surrounding context as items."""
    from urllib.parse import urljoin

    # Match <a ...href="...">...</a> patterns with optional title context
    link_re = re.compile(
        r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]{5,200})</a>',
        re.IGNORECASE | re.DOTALL,
    )
    items: list[MonitorItem] = []
    seen: set[str] = set()
    for m in link_re.finditer(html):
        href, text = m.group(1), m.group(2)
        text = _strip_html(text)
        if not text or len(text) < 10:
            continue
        # Filter obvious nav links
        skip_patterns = ("javascript:", "mailto:", "#", "login", "signup",
                         "subscribe", "advertis", "cookie", "privacy", "terms")
        if any(p in href.lower() or p in text.lower() for p in skip_patterns):
            continue
        full_url = urljoin(base_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        items.append(MonitorItem(
            source=base_url,
            url=full_url,
            title=text[:200],
            body="",
            published_at=None,
        ))
    return items


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def parse_iso_timestamp(ts: str) -> datetime | None:
    """Parse an ISO-8601 or RFC-2822 timestamp string.  Returns None on failure."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S+00:00", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts[: len(fmt) + 2].strip(), fmt)
        except ValueError:
            pass
    rfc_re = re.match(r"[A-Za-z]+,\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4}\s+\d{2}:\d{2}:\d{2})", ts)
    if rfc_re:
        try:
            return datetime.strptime(rfc_re.group(1), "%d %b %Y %H:%M:%S")
        except ValueError:
            pass
    return None


def filter_since(
    items: list[MonitorItem],
    since: datetime,
) -> list[MonitorItem]:
    """Return items whose published_at is strictly after ``since``."""
    since_naive = since.replace(tzinfo=None) if since.tzinfo is not None else since
    result = []
    for item in items:
        if not item.published_at:
            continue
        dt = parse_iso_timestamp(item.published_at)
        if dt is not None and dt > since_naive:
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# items_to_documents — convert MonitorItems to Documents via ctx
# ---------------------------------------------------------------------------


def items_to_documents(
    ctx: SkillContext,
    items: list[MonitorItem],
    *,
    outlet_id: str,
    feed_url: str = "",
) -> list[Document]:
    """Convert parsed MonitorItems to broker-tagged Documents.

    Uses ``ctx.make_document`` so every document carries skill provenance tags
    and the broker gate is applied.  Skills must pass their own ``ctx``.

    Parameters
    ----------
    ctx:
        The skill's capability context.
    items:
        Parsed feed items.
    outlet_id:
        Skill id (e.g. ``"reuters"``) used as the ``source`` metadata field
        and as part of the document id.
    feed_url:
        The feed URL that produced these items (recorded in metadata).
    """
    docs: list[Document] = []
    for item in items:
        text = item.title or ""
        if item.body:
            text = f"{text}\n\n{item.body}" if text else item.body
        if not text:
            continue
        doc_id = (
            f"{outlet_id}:{hash(item.url) & 0xFFFFFFFF:08x}"
            if item.url
            else f"{outlet_id}:{hash(text) & 0xFFFFFFFF:08x}"
        )
        doc = ctx.make_document(
            doc_id=doc_id,
            text=text,
            metadata={
                "source": outlet_id,
                "url": item.url or "",
                "title": item.title or "",
                "published_at": item.published_at or "",
                "feed_url": feed_url,
                "type": "news_article",
                "outlet": outlet_id,
            },
        )
        docs.append(doc)
    return docs
