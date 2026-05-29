"""lookup_url_at_date — find the closest Wayback snapshot to a target date.

Uses the CDX API with a narrow time window around the target date to return
the single best snapshot.  Falls back to the Availability API
(https://archive.org/wayback/available?url=...&timestamp=...) if CDX returns
nothing.

No datetime.now() at module level.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .cdx import build_cdx_url, query_cdx, snapshot_url

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

_AVAILABILITY_URL = "https://archive.org/wayback/available?url={url}&timestamp={ts}"


def lookup_url_at_date(
    ctx: SkillContext,
    url: str,
    date: str,
    *,
    fetch_content: bool = True,
) -> Document | None:
    """Return a Document for the Wayback snapshot of ``url`` closest to ``date``.

    Parameters
    ----------
    ctx:
        Skill context.
    url:
        The original URL to look up (e.g. ``https://example.com/page``).
    date:
        Target date as ``YYYYMMDD`` or ``YYYYMMDDHHMMSS``.
    fetch_content:
        If ``True`` (default) fetch the snapshot bytes and return them as a
        Document via ``ctx.fetch_and_document``.  If ``False`` return a
        metadata-only Document via ``ctx.make_document``.

    Returns
    -------
    Document or None
        ``None`` if no snapshot was found or the fetch failed.
    """
    # Normalize date to 14 digits.
    ts = _normalize_ts(date)

    # Try CDX first: query a ±30-day window centred on the target date.
    cdx_url = build_cdx_url(
        url,
        from_ts=_offset_ts(ts, -30),
        to_ts=_offset_ts(ts, +30),
        limit=5,
        fl="timestamp,original,statuscode,mimetype",
        filter_status="200",
        collapse=None,
    )
    records = query_cdx(ctx, cdx_url)

    # Pick the closest record by absolute timestamp difference.
    best = _closest(records, ts)

    if best is None:
        # Fallback: Availability API.
        best = _availability_lookup(ctx, url, ts)

    if best is None:
        return None

    snap_ts = best.get("timestamp", ts)
    original = best.get("original", url)
    snap = snapshot_url(snap_ts, original, raw=fetch_content)

    if fetch_content:
        doc = ctx.fetch_and_document(
            snap,
            extra_meta={
                "source": "wayback",
                "original_url": original,
                "snapshot_timestamp": snap_ts,
                "snapshot_url": snap,
                "target_date": date,
                "type": "snapshot",
            },
        )
        return doc

    # Metadata-only document.
    return ctx.make_document(
        doc_id=f"wayback:{snap_ts}:{hash(original) & 0xFFFFFFFF:08x}",
        text=f"Wayback snapshot of {original} at {snap_ts}",
        metadata={
            "source": "wayback",
            "original_url": original,
            "snapshot_timestamp": snap_ts,
            "snapshot_url": snap,
            "target_date": date,
            "type": "snapshot_meta",
        },
    )


# ---- helpers ---------------------------------------------------------------

def _normalize_ts(date: str) -> str:
    """Pad a date string to a 14-digit timestamp (append zeros if shorter)."""
    digits = "".join(c for c in date if c.isdigit())
    return digits.ljust(14, "0")[:14]


def _offset_ts(ts14: str, days: int) -> str:
    """Return a 14-digit timestamp offset by ``days`` days (simple arithmetic)."""
    # We only need the date part for the ±30-day window.
    year = int(ts14[0:4])
    month = int(ts14[4:6])
    day = int(ts14[6:8])
    # Shift day by ``days``.
    day += days
    # Clamp to valid range (month boundaries approximated; CDX is tolerant).
    if day < 1:
        month -= 1
        if month < 1:
            month = 12
            year -= 1
        day = 28  # safe lower bound
    elif day > 28:
        month += 1
        if month > 12:
            month = 1
            year += 1
        day = 1
    return f"{year:04d}{month:02d}{day:02d}000000"


def _ts_diff(a: str, b: str) -> int:
    """Absolute numeric difference between two 14-digit timestamps."""
    try:
        return abs(int(a) - int(b))
    except (ValueError, TypeError):
        return 10 ** 15


def _closest(records: list[dict[str, str]], target_ts: str) -> dict[str, str] | None:
    """Return the record with the timestamp closest to ``target_ts``."""
    if not records:
        return None
    return min(records, key=lambda r: _ts_diff(r.get("timestamp", "0"), target_ts))


def _availability_lookup(
    ctx: SkillContext, url: str, ts: str
) -> dict[str, str] | None:
    """Query the Wayback Availability API as a CDX fallback."""
    from .cdx import _pct_encode
    avail_url = _AVAILABILITY_URL.format(url=_pct_encode(url), ts=_pct_encode(ts))
    try:
        resp = ctx.fetch(avail_url)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = json.loads(resp.content)
    except (json.JSONDecodeError, ValueError):
        return None
    closest = data.get("archived_snapshots", {}).get("closest", {})
    if not closest or not closest.get("available"):
        return None
    return {
        "timestamp": closest.get("timestamp", ts),
        "original": closest.get("url", url),
        "statuscode": str(closest.get("status", "200")),
    }
