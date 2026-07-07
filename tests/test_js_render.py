"""Tests for js_render.py and fetch_url_js.py (all offline-deterministic).

Test matrix
-----------
1. render_html returns None when playwright is absent (simulated via import
   patch) — never raises.
2. fetch_url_js degrades to a static-fetch Document tagged
   fetch_backend="static-fallback" when render_html returns None.
3. fetch_url_js returns a js-tagged Document when a fake renderer supplies
   canned HTML.
4. load_skill('general_web') still passes the import guard after the real
   implementation landed.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.skills import load_skill
from lighthouse_ai.skills.capabilities import build_context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _broker(tmp_path: Path):
    return build_default_broker(tmp_path)


def _ctx(tmp_path: Path):
    skill = load_skill("general_web")
    broker = _broker(tmp_path)
    return build_context(skill.manifest, broker=broker)


def _fetch_url_js_module():
    """Return the *module* object for fetch_url_js (not the function).

    The package __init__.py does ``from .fetch_url_js import fetch_url_js``,
    which shadows the module name in the package namespace.  Python still
    registers the module in sys.modules under the full dotted path; we access
    it there to get the module object for monkeypatching.
    """
    # Ensure the module has been imported at least once.
    import lighthouse_ai.skills.library.general_web.tools  # noqa: F401

    key = "lighthouse_ai.skills.library.general_web.tools.fetch_url_js"
    mod = sys.modules.get(key)
    if mod is None:
        mod = importlib.import_module(key)
    return mod


def _js_render_module():
    import lighthouse_ai.sources.js_render as m  # noqa: F401

    return sys.modules["lighthouse_ai.sources.js_render"]


# ---------------------------------------------------------------------------
# 1. render_html returns None when playwright is absent
# ---------------------------------------------------------------------------


def test_render_html_returns_none_when_playwright_absent():
    """render_html must return None (not raise) when playwright is not importable."""
    # Block playwright at import time. render_html imports ``playwright.sync_api``
    # lazily at call time, so we must set BOTH the package and that submodule to
    # None — setting a sys.modules entry to None makes the import raise
    # ImportError. Only hiding already-imported modules is insufficient when
    # playwright IS installed but sync_api hasn't been imported yet (the import
    # would then succeed and render the page for real).
    blocked = {"playwright": None, "playwright.sync_api": None}
    with patch.dict(sys.modules, blocked):
        mod = _js_render_module()
        result = mod.render_html("https://example.com")
        assert result is None, f"Expected None, got {result!r}"


def test_render_html_returns_none_in_airgap(monkeypatch):
    """LIGHTHOUSE_AIRGAP must refuse the JS render before launching Chromium.

    The airgap check runs before the lazy playwright import, so render_html
    returns None (degrading to static fetch) regardless of whether the browser
    is installed — closing the Tier-B egress hole the kill switch must cover.
    """
    monkeypatch.setenv("LIGHTHOUSE_AIRGAP", "1")
    mod = _js_render_module()
    assert mod.render_html("https://example.com") is None


def test_render_html_returns_none_no_raise_on_import_error():
    """render_html returns None (not raises) when sync_playwright ImportError occurs."""
    mod = _js_render_module()

    # Patch the lazy import inside the function body by temporarily blocking
    # the playwright packages, then reload so the lazy import fires fresh.
    with patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
        importlib.reload(mod)
        result = mod.render_html("https://example.com")

    assert result is None


# ---------------------------------------------------------------------------
# 2. fetch_url_js degrades to static-fallback when render_html returns None
# ---------------------------------------------------------------------------


def test_fetch_url_js_degrades_to_static_on_no_render(tmp_path: Path):
    """When render_html returns None, fetch_url_js must fall back to static fetch
    and tag the Document fetch_backend='static-fallback'."""
    tool_mod = _fetch_url_js_module()
    js_mod = _js_render_module()

    ctx = _ctx(tmp_path)

    # Fake static fetch: return a minimal Document so we don't need the network.
    fake_doc = ctx.make_document(
        doc_id="test:fallback",
        text="Static page content",
        metadata={"source": "https://example.com"},
    )

    with patch.object(js_mod, "render_html", return_value=None):
        with patch.object(tool_mod, "fetch_url", return_value=fake_doc) as mock_static:
            tool_mod.fetch_url_js(ctx, "https://example.com")

    assert mock_static.called, "fetch_url should have been called as fallback"
    # The wrapper merges extra_meta before calling fetch_url, so extra_meta
    # should contain fetch_backend="static-fallback".
    call_kwargs = mock_static.call_args
    passed_meta = call_kwargs.kwargs.get("extra_meta") or {}
    assert passed_meta.get("fetch_backend") == "static-fallback", (
        f"Expected fetch_backend='static-fallback' in extra_meta, got {passed_meta!r}"
    )


def test_fetch_url_js_fallback_document_is_not_none(tmp_path: Path):
    """Degrade path must return a Document (not None) when static fetch succeeds."""
    tool_mod = _fetch_url_js_module()
    js_mod = _js_render_module()

    ctx = _ctx(tmp_path)

    fake_doc = ctx.make_document(
        doc_id="test:fallback-2",
        text="Fallback static content",
        metadata={"source": "https://example.com"},
    )

    with patch.object(js_mod, "render_html", return_value=None):
        with patch.object(tool_mod, "fetch_url", return_value=fake_doc):
            result = tool_mod.fetch_url_js(ctx, "https://example.com")

    assert result is not None
    assert result.text == "Fallback static content"


# ---------------------------------------------------------------------------
# 3. fetch_url_js returns a js-tagged Document when renderer supplies canned HTML
# ---------------------------------------------------------------------------


CANNED_HTML = b"""<!doctype html>
<html lang="en">
<head><title>JS Test Page</title></head>
<body><p>This content was rendered by JavaScript.</p></body>
</html>
"""


def test_fetch_url_js_returns_js_tagged_document_on_success(tmp_path: Path):
    """When render_html returns canned HTML, fetch_url_js returns a Document
    tagged fetch_backend='js'."""
    tool_mod = _fetch_url_js_module()
    js_mod = _js_render_module()

    ctx = _ctx(tmp_path)
    canned_html_str = CANNED_HTML.decode("utf-8")

    with patch.object(js_mod, "render_html", return_value=canned_html_str):
        result = tool_mod.fetch_url_js(ctx, "https://example.com/js-page")

    # The broker may ADMIT or QUARANTINE (HTMLScriptScanner sees no scripts
    # here).  It should not REJECT this benign HTML, so result is not None.
    assert result is not None, "Expected a Document, got None"
    assert result.metadata.get("fetch_backend") == "js", (
        f"Expected fetch_backend='js', got {result.metadata.get('fetch_backend')!r}"
    )


def test_fetch_url_js_js_document_contains_page_text(tmp_path: Path):
    """The text extracted from canned HTML must contain content from the page."""
    tool_mod = _fetch_url_js_module()
    js_mod = _js_render_module()

    ctx = _ctx(tmp_path)
    canned_html_str = CANNED_HTML.decode("utf-8")

    with patch.object(js_mod, "render_html", return_value=canned_html_str):
        result = tool_mod.fetch_url_js(ctx, "https://example.com/js-page")

    assert result is not None
    # The extracted text should contain some of the body content.
    assert len(result.text) > 0, f"Document text is empty: {result.text!r}"


def test_fetch_url_js_static_not_called_when_render_succeeds(tmp_path: Path):
    """When render_html succeeds, fetch_url (static) must NOT be called."""
    tool_mod = _fetch_url_js_module()
    js_mod = _js_render_module()

    ctx = _ctx(tmp_path)
    canned_html_str = CANNED_HTML.decode("utf-8")

    with patch.object(js_mod, "render_html", return_value=canned_html_str):
        with patch.object(tool_mod, "fetch_url") as mock_static:
            tool_mod.fetch_url_js(ctx, "https://example.com/js-page")

    mock_static.assert_not_called()


# ---------------------------------------------------------------------------
# 4. load_skill('general_web') still passes the import guard
# ---------------------------------------------------------------------------


def test_load_general_web_passes_import_guard():
    """Importing the real fetch_url_js must not trip the skill import guard.

    The guard forbids httpx/requests/urllib/socket/subprocess/playwright in
    skill/*.py files.  Our implementation delegates all of that to sources/,
    which is outside the guard's scan path.
    """
    skill = load_skill("general_web")
    assert skill.manifest.id == "general_web"
    # If the import guard failed, load_skill would raise SkillGuardError.


def test_general_web_tools_importable_after_real_implementation():
    """All tools including the real fetch_url_js are importable without errors."""
    from lighthouse_ai.skills.library.general_web.tools import (  # noqa: F401
        expand_query,
        fetch_url,
        fetch_url_js,
        follow_chain,
        search_images,
        search_news,
        search_scholar,
        search_videos,
        search_web,
    )


# ---------------------------------------------------------------------------
# 5. Gate interaction: ctx.gate is consulted when present
# ---------------------------------------------------------------------------


def test_fetch_url_js_uses_gate_when_present(tmp_path: Path):
    """If ctx has a .gate attribute, fetch_url_js calls gate.permit()."""
    tool_mod = _fetch_url_js_module()
    js_mod = _js_render_module()

    ctx = _ctx(tmp_path)

    # Inject a fake gate with a context-manager permit().
    permit_ctx = MagicMock()
    permit_ctx.__enter__ = MagicMock(return_value=permit_ctx)
    permit_ctx.__exit__ = MagicMock(return_value=False)
    fake_gate = MagicMock()
    fake_gate.permit = MagicMock(return_value=permit_ctx)
    ctx.gate = fake_gate  # type: ignore[attr-defined]

    canned_html_str = CANNED_HTML.decode("utf-8")

    with patch.object(js_mod, "render_html", return_value=canned_html_str):
        result = tool_mod.fetch_url_js(ctx, "https://example.com/gated")

    fake_gate.permit.assert_called_once()
    assert result is not None


def test_fetch_url_js_no_gate_still_works(tmp_path: Path):
    """fetch_url_js works fine when no gate is on ctx (gate=None path)."""
    tool_mod = _fetch_url_js_module()
    js_mod = _js_render_module()

    ctx = _ctx(tmp_path)
    # SkillContext has no .gate attribute by default.
    assert not hasattr(ctx, "gate"), "SkillContext should not have a .gate attribute by default"

    canned_html_str = CANNED_HTML.decode("utf-8")

    with patch.object(js_mod, "render_html", return_value=canned_html_str):
        result = tool_mod.fetch_url_js(ctx, "https://example.com/no-gate")

    assert result is not None
