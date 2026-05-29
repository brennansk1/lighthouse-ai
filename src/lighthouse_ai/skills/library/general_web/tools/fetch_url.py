"""fetch_url — Tier-A static fetch for a single URL.

Fetches the URL through the broker-guarded platform primitives (no raw HTTP).
Returns a Document on success; None if egress-blocked or broker REJECTs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def fetch_url(
    ctx: SkillContext,
    url: str,
    *,
    extra_meta: dict | None = None,
) -> Document | None:
    """Fetch a URL using Tier-A static fetch and return a broker-admitted Document.

    Uses ctx.fetch_and_document so the SandboxBroker sees every byte before
    parsing.  Returns None if the host is not on the platform egress allowlist
    (EgressBlocked) or if the broker REJECTs the content.

    Args:
        ctx: The SkillContext passed to the skill entrypoint.
        url: The URL to fetch.
        extra_meta: Optional metadata merged into the Document.

    Returns:
        Document on success; None if blocked or rejected.
    """
    try:
        return ctx.fetch_and_document(url, extra_meta=extra_meta or {})
    except Exception:
        return None
