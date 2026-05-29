"""fetch_url_js — Tier-B JS-rendering fetch (real implementation).

Fetches a URL through a headless Chromium browser (Playwright sync API) and
returns a Document tagged ``fetch_backend="js"``.  Text extraction from the
rendered HTML is handled by ``ctx.document_from_bytes`` (via ingest_bytes).

Degrade path (in order):
  1. Scheduler gate: if ``ctx`` carries a ``gate`` attribute (a
     :class:`~lighthouse_ai.governor.scheduler_gate.SchedulerGate`), wait for
     a permit before spending CPU on the browser launch.  If no gate is present
     (e.g. in tests or direct invocations), proceed immediately.
  2. JS render: call
     :func:`lighthouse_ai.sources.js_render.render_html`.  On success,
     build a Document through ``ctx.document_from_bytes`` tagged
     ``fetch_backend="js"``.
  3. Static fallback: if ``render_html`` returns ``None`` (playwright absent,
     browser binary missing, or any other failure), fall back to the static
     :func:`fetch_url` tool — the Document is tagged
     ``fetch_backend="static-fallback"`` so downstream WEP accounting applies
     the ordinary Tier-A rules rather than the additional Tier-B −1 band.

No playwright/httpx imports appear here — all browser I/O is delegated to the
``sources/js_render`` helper, and all HTTP I/O is delegated to
``ctx.fetch_and_document`` (via the static fallback).

The §5.4 extra WEP downgrade for ``fetch_backend="js"`` single-source is
applied *downstream* by the discipline gate; this tool simply ensures the tag
is set correctly on every returned Document.

Args contract:
    ctx: SkillContext passed to the skill entrypoint.
    url: The URL to fetch.
    extra_meta: Optional metadata merged into the Document.

Returns:
    Document (js-rendered or static-fallback); None if blocked or rejected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import lighthouse_ai.sources.js_render as _js_render

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
    """Fetch a URL with JS-rendering (Tier-B); degrade to static fetch if unavailable.

    Consults the scheduler gate (via ``ctx.gate`` if present) before launching
    the browser.  If JS rendering fails for any reason, delegates to the static
    ``fetch_url`` tool and tags the result ``fetch_backend="static-fallback"``.

    Args:
        ctx: The SkillContext passed to the skill entrypoint.
        url: The URL to fetch.
        extra_meta: Optional metadata merged into the returned Document.

    Returns:
        JS-rendered Document tagged ``fetch_backend="js"`` on success;
        static-fetch Document tagged ``fetch_backend="static-fallback"`` on
        JS-render failure; ``None`` if blocked or broker-rejected.
    """
    # --- scheduler gate (optional) ------------------------------------------
    # SkillContext does not currently expose a .gate attribute in production;
    # we use getattr so tests can inject a fake gate without patching the class.
    gate = getattr(ctx, "gate", None)
    if gate is not None:
        with gate.permit():
            return _do_js_fetch(ctx, url, extra_meta=extra_meta)
    return _do_js_fetch(ctx, url, extra_meta=extra_meta)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _do_js_fetch(
    ctx: SkillContext,
    url: str,
    *,
    extra_meta: dict | None = None,
) -> Document | None:
    """Attempt JS render; degrade to static fetch on failure."""
    html = _js_render.render_html(url)

    if html is not None:
        return _build_js_document(ctx, url, html, extra_meta=extra_meta)

    # JS render unavailable or failed — degrade to static fetch.
    meta = dict(extra_meta or {})
    meta["fetch_backend"] = "static-fallback"
    meta["fetch_backend_note"] = (
        "JS rendering unavailable (playwright not installed or browser binary "
        "missing); degraded to static Tier-A fetch."
    )
    return fetch_url(ctx, url, extra_meta=meta)


def _build_js_document(
    ctx: SkillContext,
    url: str,
    html: str,
    *,
    extra_meta: dict | None = None,
) -> Document | None:
    """Build a broker-admitted Document from rendered HTML.

    Passes the HTML bytes through ``ctx.document_from_bytes`` so the
    SandboxBroker sees every byte before the Document is admitted.
    Text extraction (HTML → plain text via trafilatura/stdlib fallback) happens
    inside ``document_from_bytes`` via ``ingest_bytes``.  We tag the result
    ``fetch_backend="js"`` so downstream WEP accounting can apply the §5.4
    single-source Tier-B −1 band.
    """
    meta = dict(extra_meta or {})
    meta["fetch_backend"] = "js"
    meta["source"] = url

    payload = html.encode("utf-8")
    return ctx.document_from_bytes(
        payload,
        url=url,
        content_type="text/html; charset=utf-8",
        extra_meta=meta,
    )
