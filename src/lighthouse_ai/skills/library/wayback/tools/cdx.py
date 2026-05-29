"""Wayback CDX API helpers — core query and response parsing.

The CDX Search API endpoint:
  https://web.archive.org/cdx/search/cdx?url=<url>&output=json&...

Response format (JSON):
  First row is the field name header; subsequent rows are records:
  [["urlkey","timestamp","original","mimetype","statuscode","digest","length"],
   ["com,example)/", "20230101120000", "http://example.com/", ...], ...]

All fetches go through the ``ctx.fetch`` primitive — no urllib/httpx imports.

No datetime.now() at module level (constraint: deterministic offline).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lighthouse_ai.skills.capabilities import SkillContext

CDX_BASE = "https://web.archive.org/cdx/search/cdx"
SNAPSHOT_BASE = "https://web.archive.org/web/{timestamp}id_/{url}"
REPLAY_BASE = "https://web.archive.org/web/{timestamp}/{url}"


def _pct_encode(s: str) -> str:
    """Percent-encode a string for use as a URL query parameter value (stdlib only)."""
    safe = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789"
        "-_.~"
    )
    out: list[str] = []
    for ch in s.encode("utf-8"):
        c = chr(ch)
        if c in safe:
            out.append(c)
        else:
            out.append(f"%{ch:02X}")
    return "".join(out)


def build_cdx_url(
    url: str,
    *,
    from_ts: str | None = None,
    to_ts: str | None = None,
    output: str = "json",
    limit: int = 10,
    fl: str = "timestamp,original,statuscode,mimetype",
    filter_status: str | None = "200",
    collapse: str | None = "timestamp:8",
) -> str:
    """Build a CDX API query URL.

    Parameters
    ----------
    url:
        The original URL to look up.
    from_ts / to_ts:
        Optional 14-digit timestamp boundaries ``YYYYMMDDHHMMSS``.
    output:
        Response format (``json`` or ``text``).
    limit:
        Maximum rows to return.
    fl:
        Comma-separated field list.
    filter_status:
        If set, add ``filter=statuscode:<value>`` to skip redirects/errors.
    collapse:
        If set, de-duplicate by this field prefix (e.g. ``timestamp:8`` gives
        one snapshot per day).
    """
    parts = [
        f"{CDX_BASE}?url={_pct_encode(url)}",
        f"output={output}",
        f"limit={limit}",
        f"fl={_pct_encode(fl)}",
    ]
    if from_ts:
        parts.append(f"from={_pct_encode(from_ts)}")
    if to_ts:
        parts.append(f"to={_pct_encode(to_ts)}")
    if filter_status:
        parts.append(f"filter=statuscode:{_pct_encode(filter_status)}")
    if collapse:
        parts.append(f"collapse={_pct_encode(collapse)}")
    return "&".join(parts)


def parse_cdx_response(content: bytes) -> list[dict[str, str]]:
    """Parse a CDX JSON response into a list of record dicts.

    The first row (field names header) is used as keys; subsequent rows
    become dicts.  Returns ``[]`` on empty or malformed input.
    """
    try:
        rows = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []
    if not rows or not isinstance(rows, list):
        return []
    # First row is the header.
    header = rows[0]
    if not isinstance(header, list):
        return []
    records: list[dict[str, str]] = []
    for row in rows[1:]:
        if not isinstance(row, list) or len(row) != len(header):
            continue
        records.append({str(k): str(v) for k, v in zip(header, row)})
    return records


def snapshot_url(timestamp: str, original_url: str, *, raw: bool = True) -> str:
    """Return the Wayback replay or raw-content URL for a snapshot.

    ``raw=True`` uses the ``id_`` modifier which returns the verbatim archived
    bytes without Wayback banners — preferred for content extraction.
    ``raw=False`` returns the standard replay URL (with Wayback toolbar).
    """
    tmpl = SNAPSHOT_BASE if raw else REPLAY_BASE
    return tmpl.format(timestamp=_pct_encode(timestamp), url=_pct_encode(original_url))


def query_cdx(ctx: SkillContext, cdx_url: str) -> list[dict[str, str]]:
    """Fetch ``cdx_url`` via ctx.fetch and parse the CDX JSON response."""
    try:
        resp = ctx.fetch(cdx_url)
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    return parse_cdx_response(resp.content)
