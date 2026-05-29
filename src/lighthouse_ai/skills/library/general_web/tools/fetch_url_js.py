"""fetch_url_js — Tier-B JS-rendering fetch stub.

Tier-B (in-process JS rendering via Crawl4AI / Playwright) is declared in the
manifest as tier = "A" for the current implementation pass.  Full Tier-B
support requires the scheduler gate and the Crawl4AI integration which are
scheduled for a future sprint.

For now this tool falls through to the static Tier-A fetch_url and annotates
the returned Document with a ``fetch_backend_note`` metadata field explaining
that JS rendering was not performed.  A planner consuming the result should
treat it identically to a static fetch — the content may be incomplete for
JavaScript-heavy pages.

TODO (Tier-B): Replace the body with Crawl4AI / Playwright integration once
the scheduler gate and the opt-in trust flow are wired up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .fetch_url import fetch_url

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def fetch_url_js(
    ctx: SkillContext,
    url: str,
    *,
    extra_meta: dict | None = None,
) -> Document | None:
    """Fetch a URL with JS-rendering (Tier-B stub — currently static fetch).

    When the full Tier-B implementation lands this function will trigger the
    scheduler gate, spin up an in-process Playwright browser, and return the
    rendered DOM text.  Until then it delegates to the static fetch_url and
    tags the result so callers can distinguish real JS renders from stubs.

    The WEP downgrade rule for Tier-B (additional −1 band when the sole source
    uses JS rendering) is NOT applied here — the skill runner applies downgrades
    based on the Document's ``fetch_backend`` tag, and since we're performing a
    static fetch the ordinary grade C applies.

    Args:
        ctx: The SkillContext passed to the skill entrypoint.
        url: The URL to fetch.
        extra_meta: Optional metadata merged into the Document.

    Returns:
        Document from static fetch with a note; None if blocked or rejected.
    """
    meta = dict(extra_meta or {})
    meta["fetch_backend_note"] = (
        "Tier-B JS rendering not yet implemented; static fetch used. "
        "Content may be incomplete for JS-heavy pages."
    )
    doc = fetch_url(ctx, url, extra_meta=meta)
    return doc
