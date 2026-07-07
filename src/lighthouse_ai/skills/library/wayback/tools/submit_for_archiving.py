"""submit_for_archiving — request the Wayback Machine to archive a live URL.

Uses the Save Page Now 2 (SPN2) endpoint:
  https://web.archive.org/save/<url>

A successful request returns HTTP 200 with a ``Content-Location`` header
pointing to the newly-created snapshot.  The response body may be an HTML
confirmation page or a JSON status object depending on the accept header.

Note: SPN2 may take seconds to minutes to complete.  This tool fires the
request and returns the job_id / snapshot URL from the response headers; it
does not wait for crawl completion (the caller should poll if needed).

No datetime.now() at module level.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

_SPN_BASE = "https://web.archive.org/save/{url}"


def submit_for_archiving(
    ctx: SkillContext,
    url: str,
) -> Document | None:
    """Submit ``url`` to the Wayback Machine for archiving.

    Parameters
    ----------
    ctx:
        Skill context.
    url:
        The live URL to archive.

    Returns
    -------
    Document or None
        A metadata Document describing the submission result (snapshot URL if
        available, or the SPN response URL).  Returns None if the request fails.
    """
    from .cdx import _pct_encode

    save_url = _SPN_BASE.format(url=_pct_encode(url))
    try:
        resp = ctx.fetch(save_url)
    except Exception:
        return None

    # The Content-Location header often carries the snapshot path.
    location = resp.headers.get("Content-Location", "")
    snapshot_url_result = (
        f"https://web.archive.org{location}" if location.startswith("/web/") else save_url
    )

    return ctx.make_document(
        doc_id=f"wayback:save:{hash(url) & 0xFFFFFFFF:08x}",
        text=(
            f"Submitted {url} for archiving.\n"
            f"Status: {resp.status_code}\n"
            f"Snapshot URL: {snapshot_url_result}"
        ),
        metadata={
            "source": "wayback",
            "original_url": url,
            "snapshot_url": snapshot_url_result,
            "http_status": resp.status_code,
            "type": "save_submission",
        },
    )
