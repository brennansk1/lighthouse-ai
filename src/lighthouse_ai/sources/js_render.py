"""js_render — Lazy Playwright-backed JS renderer for Tier-B fetches.

This module provides :func:`render_html`, which launches a headless Chromium
browser via Playwright's sync API, navigates to a URL, waits for network-idle,
and returns the fully-rendered HTML as a string.

**Usage requirement**: the ``playwright`` Python package *and* its Chromium
browser binary must both be installed.  To install::

    pip install 'lighthouse-ai[js-render]'
    playwright install chromium

When either the package or the browser binary is absent, :func:`render_html`
returns ``None`` rather than raising — callers degrade gracefully to static
Tier-A fetch.  This is the *only* valid degradation path; exceptions are always
caught internally.

No stealth/evasion flags are set.  The browser is launched with the default
Playwright fingerprint.  Rate-limiting and politeness are the caller's concern.

RAM safety
----------
A hard ``timeout`` (default: 30 s) prevents the browser from running forever,
and ``max_bytes`` (default: 10 MB rendered HTML) caps the string returned so
large SPAs do not flood the pipeline.  Both limits are enforced even when
Playwright itself succeeds.
"""

from __future__ import annotations

import logging
from typing import Final

log = logging.getLogger(__name__)

# ---- defaults --------------------------------------------------------------

# 30 s matches the static-fetch default; generous enough for most SPAs.
DEFAULT_TIMEOUT: Final[float] = 30.0

# 10 MB of rendered HTML is already extremely large; trafilatura / the ingest
# pipeline has its own 5 MB *text* cap downstream, so this is a belt-and-braces
# HTML cap that protects RAM before we even start extracting.
DEFAULT_MAX_BYTES: Final[int] = 10 * 1024 * 1024  # 10 MB


# ---- public API ------------------------------------------------------------


def render_html(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> str | None:
    """Render ``url`` in a headless Chromium browser and return the full HTML.

    Launches a fresh Playwright browser context per call (no persistent state),
    navigates to ``url``, and waits until the network is idle before returning
    ``page.content()``.

    Returns ``None`` — *never raises* — in any of these situations:

    * ``playwright`` package is not installed (``ImportError``).
    * The Chromium browser binary is missing
      (``playwright._impl._errors.Error`` / ``playwright.sync_api.Error``).
    * Navigation fails (timeout, DNS error, HTTP error, etc.).
    * Any other unexpected exception.

    Args:
        url: The URL to fetch and render.
        timeout: Maximum seconds to wait for the page to load (network-idle).
            Passed directly to Playwright as milliseconds internally.
        max_bytes: Maximum bytes of rendered HTML to return.  Content larger
            than this is truncated at a valid UTF-8 boundary.

    Returns:
        Rendered HTML string on success; ``None`` on any failure.

    Note:
        ``playwright install chromium`` must have been run for this to succeed.
        No stealth or anti-fingerprint options are applied.
    """
    # Lazy import so that importing this module never fails when playwright is
    # absent.  The import guard in skills/registry.py scans *skill* files; this
    # module lives in sources/ which is explicitly excluded from that scan.
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError:
        log.debug("js_render: playwright not installed; returning None")
        return None

    timeout_ms = int(timeout * 1000)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                try:
                    page.goto(
                        url,
                        timeout=timeout_ms,
                        wait_until="networkidle",
                    )
                    html: str = page.content()
                finally:
                    page.close()
            finally:
                browser.close()
    except Exception as exc:
        log.debug("js_render: render failed for %s: %s", url, exc)
        return None

    # Enforce the content size cap.  Encode to UTF-8, truncate on a byte
    # boundary (ignore ensures we never decode a torn multi-byte sequence),
    # then decode back to str.
    raw_bytes = html.encode("utf-8")
    if len(raw_bytes) > max_bytes:
        log.debug(
            "js_render: truncating %d bytes to %d for %s",
            len(raw_bytes),
            max_bytes,
            url,
        )
        html = raw_bytes[:max_bytes].decode("utf-8", errors="ignore")

    return html
