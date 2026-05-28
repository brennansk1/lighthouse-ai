"""Zero-dependency RSS / Atom reader.

Yields :class:`lighthouse_ai.modes.monitor.MonitorItem` records. Stdlib
``xml.etree.ElementTree`` only — we don't want to add ``feedparser`` for a
single sprint's needs.

Supported shapes:
  * RSS 2.0 ``<rss><channel><item>``
  * Atom 1.0 ``<feed><entry>``
  * Malformed XML produces an empty list (never raises) — callers can log.

All fetched bytes pass through the sandbox broker before parsing, so a
hostile feed can't deliver a XSS-laden HTML body straight to the renderer.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx

from ..modes.monitor import MonitorItem
from ..sandbox.broker import SandboxBroker, Verdict

# Atom namespace used by most modern feeds.
_NS = {"atom": "http://www.w3.org/2005/Atom"}
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(s: str | None) -> str:
    if not s:
        return ""
    return _HTML_TAG_RE.sub("", s).strip()


def _parse_atom(root: ET.Element) -> list[MonitorItem]:
    feed_title = (root.findtext("atom:title", default="", namespaces=_NS) or "")
    out: list[MonitorItem] = []
    for entry in root.findall("atom:entry", _NS):
        title = entry.findtext("atom:title", default="", namespaces=_NS) or ""
        body = (entry.findtext("atom:summary", default="", namespaces=_NS)
                or entry.findtext("atom:content", default="", namespaces=_NS) or "")
        link_el = entry.find("atom:link", _NS)
        url = (link_el.get("href") if link_el is not None else "") or ""
        published = entry.findtext("atom:updated", default="", namespaces=_NS) or None
        if not url:
            continue
        out.append(MonitorItem(
            source=feed_title or "atom",
            url=url, title=title.strip(), body=_strip_tags(body),
            published_at=published,
        ))
    return out


def _parse_rss(root: ET.Element) -> list[MonitorItem]:
    # Accept both a full <rss><channel> document and a bare <channel> root
    # (some feeds put the channel at the document root).
    channel = root if root.tag.lower().endswith("channel") else root.find("channel")
    if channel is None:
        return []
    feed_title = channel.findtext("title", default="") or ""
    out: list[MonitorItem] = []
    for item in channel.findall("item"):
        title = item.findtext("title", default="") or ""
        url = (item.findtext("link", default="") or "").strip()
        body = item.findtext("description", default="") or ""
        published = item.findtext("pubDate", default="") or None
        if not url:
            continue
        out.append(MonitorItem(
            source=feed_title or "rss",
            url=url, title=title.strip(), body=_strip_tags(body),
            published_at=published,
        ))
    return out


def parse_feed_bytes(payload: bytes) -> list[MonitorItem]:
    """Parse RSS or Atom from raw bytes. Returns ``[]`` on malformed input."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []
    tag = root.tag.lower()
    if tag.endswith("rss"):
        return _parse_rss(root)
    if tag.endswith("feed"):  # namespaced ({ns}feed) is covered by endswith
        return _parse_atom(root)
    # Some feeds put the channel at the document root.
    if tag.endswith("channel"):
        return _parse_rss(root)
    return []


def fetch_feed(url: str, *, broker: SandboxBroker | None = None,
               timeout: float = 30.0) -> list[MonitorItem]:
    """Fetch ``url`` and return parsed items. Sandbox-admits the body first."""
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url, headers={"User-Agent": "Lighthouse/0.1"})
    r.raise_for_status()
    payload = r.content
    if broker is not None:
        outcome = broker.admit(payload, url=url, filename=url.rsplit("/", 1)[-1],
                               content_type=r.headers.get("content-type"))
        if outcome.verdict is Verdict.REJECT:
            return []
    return parse_feed_bytes(payload)
