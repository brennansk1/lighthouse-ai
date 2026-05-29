"""list_snapshots — enumerate all available Wayback snapshots for a URL.

Returns a list of snapshot records (dicts with timestamp, original,
statuscode, mimetype) via the CDX API.  Useful for building a chronology
of how a page changed over time.

No datetime.now() at module level.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cdx import build_cdx_url, query_cdx

if TYPE_CHECKING:
    from lighthouse_ai.skills.capabilities import SkillContext


def list_snapshots(
    ctx: SkillContext,
    url: str,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 50,
    collapse_daily: bool = True,
) -> list[dict[str, str]]:
    """Return a list of CDX snapshot records for ``url``.

    Parameters
    ----------
    ctx:
        Skill context.
    url:
        The original URL to enumerate snapshots for.
    from_date / to_date:
        Optional date boundaries as ``YYYYMMDD`` or ``YYYYMMDDHHMMSS``.
    limit:
        Maximum number of records to return.
    collapse_daily:
        When ``True`` (default) collapse to one snapshot per day, reducing
        the list for frequently-crawled pages.

    Returns
    -------
    list[dict[str, str]]
        Each record has keys ``timestamp``, ``original``, ``statuscode``,
        ``mimetype`` (as returned by CDX).  Empty list if CDX returns nothing
        or the request fails.
    """
    from_ts = _normalize_ts(from_date) if from_date else None
    to_ts = _normalize_ts(to_date) if to_date else None

    cdx_url = build_cdx_url(
        url,
        from_ts=from_ts,
        to_ts=to_ts,
        limit=limit,
        fl="timestamp,original,statuscode,mimetype",
        filter_status="200",
        collapse="timestamp:8" if collapse_daily else None,
    )
    return query_cdx(ctx, cdx_url)


def _normalize_ts(date: str) -> str:
    digits = "".join(c for c in date if c.isdigit())
    return digits.ljust(14, "0")[:14]
