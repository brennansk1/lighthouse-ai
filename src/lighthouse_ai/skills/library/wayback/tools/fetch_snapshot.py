"""fetch_snapshot — retrieve the content of a specific Wayback snapshot.

Given a 14-digit timestamp and original URL, constructs the ``id_/`` raw
snapshot URL and fetches it via ``ctx.fetch_and_document`` so the broker
inspects every byte before parsing.

No datetime.now() at module level.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cdx import snapshot_url

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def fetch_snapshot(
    ctx: SkillContext,
    timestamp: str,
    url: str,
    *,
    raw: bool = True,
) -> Document | None:
    """Fetch the Wayback snapshot at ``timestamp`` for ``url``.

    Parameters
    ----------
    ctx:
        Skill context.
    timestamp:
        14-digit CDX timestamp (``YYYYMMDDHHMMSS``).
    url:
        The original URL of the archived page.
    raw:
        When ``True`` (default) use the ``id_/`` modifier to retrieve the
        verbatim archived bytes without Wayback rewrite/toolbar injection.

    Returns
    -------
    Document or None
        Broker-admitted Document with snapshot provenance metadata, or None
        if the fetch fails or the broker rejects the content.
    """
    snap = snapshot_url(timestamp, url, raw=raw)
    doc = ctx.fetch_and_document(
        snap,
        extra_meta={
            "source": "wayback",
            "original_url": url,
            "snapshot_timestamp": timestamp,
            "snapshot_url": snap,
            "type": "snapshot",
        },
    )
    return doc
