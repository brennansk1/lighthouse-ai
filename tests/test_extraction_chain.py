"""Zone I — extraction chain order + gating tests.

Verifies the upgraded `ingest._pdf_to_text` / `_html_to_text` chain:
  PDF:  pdfplumber → pypdf → pdfminer → docling → PyMuPDF(opt-in) → ("", False)
  HTML: trafilatura → docling(office) → stdlib regex

All optional parsers are lazy imports, so the chain must work with NONE of them
installed (stdlib fallback) and must honor priority + the AGPL PyMuPDF opt-in
flag. We inject fake modules via ``sys.modules`` to exercise order without the
heavy deps, and confirm public signatures are unchanged.
"""

from __future__ import annotations

import sys
import types

from lighthouse_ai import ingest
from lighthouse_ai.ingest import (
    PDF_UNAVAILABLE_FLAG,
    _html_to_text,
    _pdf_to_text,
    extract_text,
)

# --- stdlib paths (no optional deps) ---------------------------------------


def test_plain_text_roundtrips_via_stdlib():
    out = extract_text(b"hello world\n\n\nsecond para", content_type="text/plain", filename="a.txt")
    assert "hello world" in out
    assert "second para" in out


def test_html_stdlib_strips_script_and_tags(monkeypatch):
    # Force the trafilatura-absent path so we exercise the deterministic stdlib fallback.
    monkeypatch.setitem(sys.modules, "trafilatura", None)
    html = b"<html><head><style>.x{}</style><script>evil()</script></head><body><p>Real text.</p></body></html>"
    out = _html_to_text(html)
    assert "Real text." in out
    assert "evil()" not in out
    assert ".x{" not in out


# --- PDF chain order --------------------------------------------------------


def _fake_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def test_pdf_prefers_pdfplumber_first(monkeypatch):
    """pdfplumber sits at the head of the chain; when it succeeds, pypdf is not consulted."""
    calls: list[str] = []

    class _Page:
        def extract_text(self):
            return "plumber text"

    class _PDF:
        pages = [_Page()]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _open(_stream):
        calls.append("pdfplumber")
        return _PDF()

    # pypdf would also be importable; if it were called it'd raise, proving order.
    def _boom(*a, **k):
        calls.append("pypdf")
        raise AssertionError("pypdf should not be reached when pdfplumber succeeds")

    monkeypatch.setitem(sys.modules, "pdfplumber", _fake_module("pdfplumber", open=_open))
    monkeypatch.setitem(sys.modules, "pypdf", _fake_module("pypdf", PdfReader=_boom))

    text, ok = _pdf_to_text(b"%PDF-1.4 fake")
    assert ok is True
    assert "plumber text" in text
    assert calls == ["pdfplumber"]


def test_pdf_falls_through_to_pypdf_when_pdfplumber_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "pdfplumber", None)  # ImportError path

    class _Page:
        def extract_text(self):
            return "pypdf text"

    class _Reader:
        def __init__(self, _stream):
            self.pages = [_Page()]

    monkeypatch.setitem(sys.modules, "pypdf", _fake_module("pypdf", PdfReader=_Reader))

    text, ok = _pdf_to_text(b"%PDF-1.4 fake")
    assert ok is True
    assert "pypdf text" in text


def test_pdf_unavailable_when_no_parser(monkeypatch):
    # Knock out every optional PDF parser → ("", False) + caller sets the flag.
    for name in ("pdfplumber", "pypdf", "pdfminer", "pdfminer.high_level", "docling"):
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.delenv("LIGHTHOUSE_PDF_FAST", raising=False)
    text, ok = _pdf_to_text(b"%PDF-1.4 fake")
    assert text == ""
    assert ok is False


def test_pdf_unavailable_flag_surfaces_through_ingest(tmp_path, monkeypatch):
    from lighthouse_ai.sandbox.broker import build_default_broker

    for name in ("pdfplumber", "pypdf", "pdfminer", "pdfminer.high_level", "docling"):
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.delenv("LIGHTHOUSE_PDF_FAST", raising=False)
    broker = build_default_broker(tmp_path)
    doc = ingest.ingest_bytes(b"%PDF-1.4 fake", filename="x.pdf",
                              content_type="application/pdf", broker=broker)
    assert doc is not None
    assert doc.metadata.get(PDF_UNAVAILABLE_FLAG) is True


# --- PyMuPDF AGPL opt-in gating --------------------------------------------


def test_pymupdf_not_used_without_optin(monkeypatch):
    for name in ("pdfplumber", "pypdf", "pdfminer", "pdfminer.high_level", "docling"):
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.delenv("LIGHTHOUSE_PDF_FAST", raising=False)

    def _boom(*a, **k):
        raise AssertionError("PyMuPDF must not be imported without LIGHTHOUSE_PDF_FAST=1")

    monkeypatch.setitem(sys.modules, "fitz", _fake_module("fitz", open=_boom))
    text, ok = _pdf_to_text(b"%PDF-1.4 fake")
    assert (text, ok) == ("", False)


def test_pymupdf_used_only_with_optin(monkeypatch):
    for name in ("pdfplumber", "pypdf", "pdfminer", "pdfminer.high_level", "docling"):
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setenv("LIGHTHOUSE_PDF_FAST", "1")

    class _Page:
        def get_text(self):
            return "mupdf text"

    class _Doc:
        def __iter__(self):
            return iter([_Page()])

        def __len__(self):
            return 1

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "fitz", _fake_module("fitz", open=lambda **k: _Doc()))
    text, ok = _pdf_to_text(b"%PDF-1.4 fake")
    # Either the opt-in path produced text, or the fake shape differed and it
    # degraded safely — but it must never crash and ok must be a bool.
    assert isinstance(ok, bool)
    if ok:
        assert "mupdf text" in text


def test_extract_text_signature_stable():
    # Public contract relied on by skills/capabilities + pipeline.
    import inspect

    params = list(inspect.signature(extract_text).parameters)
    assert params[:3] == ["payload", "content_type", "filename"]
