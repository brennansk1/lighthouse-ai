"""Sandbox broker + scanner + quarantine tests (Sprint 6)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from lighthouse_ai.sandbox import (
    ArchiveBombScanner,
    HTMLScriptScanner,
    PDFJavaScriptScanner,
    Quarantine,
    SandboxBroker,
    Verdict,
)
from lighthouse_ai.sandbox.broker import build_default_broker
from lighthouse_ai.sandbox.scanners import EICAR_SIGNATURE, EICARScanner

# --- scanners ----------------------------------------------------

def test_pdf_no_js_admitted():
    payload = b"%PDF-1.4\n%hello\n"
    s = PDFJavaScriptScanner()
    assert s.scan(payload, filename="x.pdf").verdict == "clean"


def test_pdf_with_js_quarantined():
    payload = b"%PDF-1.4\n/OpenAction << /S /JavaScript /JS (app.alert('xss')) >>\n"
    s = PDFJavaScriptScanner()
    r = s.scan(payload, filename="x.pdf")
    assert r.verdict == "quarantine"
    assert "JavaScript" in r.reason or "JS" in r.reason


def test_non_pdf_with_pdf_extension_quarantined():
    s = PDFJavaScriptScanner()
    r = s.scan(b"not a pdf", filename="fake.pdf")
    assert r.verdict == "quarantine"
    assert "PDF" in r.reason


def test_html_with_script_quarantined():
    s = HTMLScriptScanner()
    r = s.scan(b"<html><script>alert(1)</script></html>", filename="x.html")
    assert r.verdict == "quarantine"


def test_html_with_event_handler_quarantined():
    s = HTMLScriptScanner()
    r = s.scan(b'<a onclick="evil()">x</a>', filename="x.html")
    assert r.verdict == "quarantine"


def test_html_with_javascript_url_quarantined():
    s = HTMLScriptScanner()
    r = s.scan(b'<a href="javascript:evil()">x</a>', filename="x.html")
    assert r.verdict == "quarantine"


def test_clean_html_admitted():
    s = HTMLScriptScanner()
    r = s.scan(b"<html><body><p>hi</p></body></html>", filename="x.html")
    assert r.verdict == "clean"


def test_svg_with_script_quarantined():
    s = HTMLScriptScanner()
    r = s.scan(b'<svg><script>alert(1)</script></svg>', filename="x.svg")
    assert r.verdict == "quarantine"


def test_svg_with_event_handler_quarantined():
    """SVG executes event handlers in-browser exactly like HTML — must catch them."""
    s = HTMLScriptScanner()
    r = s.scan(b'<svg><img src=x onerror="steal()"></svg>', filename="x.svg")
    assert r.verdict == "quarantine"


def test_svg_with_javascript_url_quarantined():
    s = HTMLScriptScanner()
    r = s.scan(b'<svg><a href="javascript:steal()">x</a></svg>', filename="x.svg")
    assert r.verdict == "quarantine"


def test_html_leading_svg_does_not_downgrade_scan():
    """An .html file that merely begins with <svg> must still get the full
    HTML danger check — not the weaker SVG-only one — so event handlers in
    the surrounding HTML are not smuggled through."""
    s = HTMLScriptScanner()
    payload = b'<svg width="1"></svg><body><img src=x onerror=alert(1)></body>'
    r = s.scan(payload, filename="page.html")
    assert r.verdict == "quarantine"


def test_archive_bomb_rejected():
    """Build a 50KB zip whose declared expansion is over 1GB → reject."""
    buf = io.BytesIO()
    huge = b"A" * (10 * 1024 * 1024)  # 10MB
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for i in range(120):
            zf.writestr(f"f{i}.txt", huge)
    s = ArchiveBombScanner(max_ratio=50.0, max_uncompressed_mb=1024)
    r = s.scan(buf.getvalue(), filename="bomb.zip")
    assert r.verdict == "reject"


def test_normal_zip_admitted():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.txt", "hello")
    s = ArchiveBombScanner(max_ratio=100.0)
    r = s.scan(buf.getvalue(), filename="ok.zip")
    assert r.verdict == "clean"


def test_invalid_zip_rejected():
    s = ArchiveBombScanner()
    r = s.scan(b"not a zip", filename="x.zip")
    assert r.verdict == "reject"


def test_nested_zip_bomb_rejected():
    """A zip-in-zip where the inner zip is a bomb must be rejected.

    The outer zip stores the inner zip nearly verbatim (ratio≈1), so the
    top-level check passes.  Only recursive inspection reveals the bomb
    inside.  Regression for the audit finding.
    """
    # Build inner bomb zip: many large entries compressed to very little.
    inner_buf = io.BytesIO()
    huge = b"A" * (10 * 1024 * 1024)  # 10 MB per entry
    with zipfile.ZipFile(inner_buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for i in range(120):
            zf.writestr(f"f{i}.txt", huge)
    inner_bytes = inner_buf.getvalue()

    # Wrap it in an outer zip stored without compression (ratio≈1 at outer level).
    outer_buf = io.BytesIO()
    with zipfile.ZipFile(outer_buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("bomb.zip", inner_bytes)

    s = ArchiveBombScanner(max_ratio=50.0, max_uncompressed_mb=2048)
    r = s.scan(outer_buf.getvalue(), filename="outer.zip")
    assert r.verdict == "reject", f"expected reject, got {r.verdict}: {r.reason}"


def test_nested_zip_benign_passes():
    """A clean zip containing a small zip must be admitted (no false positive)."""
    inner_buf = io.BytesIO()
    with zipfile.ZipFile(inner_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("readme.txt", "hello from inner zip")
    inner_bytes = inner_buf.getvalue()

    outer_buf = io.BytesIO()
    with zipfile.ZipFile(outer_buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("inner.zip", inner_bytes)

    s = ArchiveBombScanner(max_ratio=100.0, max_uncompressed_mb=1024)
    r = s.scan(outer_buf.getvalue(), filename="outer.zip")
    assert r.verdict == "clean", f"expected clean, got {r.verdict}: {r.reason}"


def test_eicar_detected():
    s = EICARScanner()
    payload = b"prefix " + EICAR_SIGNATURE + b" suffix"
    assert s.scan(payload).verdict == "reject"


# --- broker ------------------------------------------------------

def _broker(tmp_path: Path) -> SandboxBroker:
    q = Quarantine(tmp_path / "quarantine.db", tmp_path / "Q")
    return SandboxBroker(q, scanners=[
        EICARScanner(), PDFJavaScriptScanner(),
        HTMLScriptScanner(), ArchiveBombScanner(),
    ])


def test_broker_admits_clean_html(tmp_path):
    b = _broker(tmp_path)
    out = b.admit(b"<p>hello</p>", filename="x.html", content_type="text/html")
    assert out.verdict is Verdict.ADMIT
    assert (tmp_path / "Q" / "admit").exists()


def test_broker_quarantines_html_with_script(tmp_path):
    b = _broker(tmp_path)
    out = b.admit(b"<script>e()</script>", filename="x.html",
                  content_type="text/html")
    assert out.verdict is Verdict.QUARANTINE


def test_broker_rejects_eicar(tmp_path):
    b = _broker(tmp_path)
    out = b.admit(EICAR_SIGNATURE, filename="t.bin", content_type="text/plain")
    assert out.verdict is Verdict.REJECT
    # Rejected payloads are not persisted to disk by default.
    rejected_dir = tmp_path / "Q" / "reject"
    assert not rejected_dir.exists() or not list(rejected_dir.iterdir())


def test_broker_records_in_manifest(tmp_path):
    b = _broker(tmp_path)
    b.admit(b"<p>hi</p>", filename="x.html", content_type="text/html")
    rows = b.quarantine.list()
    assert rows
    assert rows[0]["filename"] == "x.html"


def test_quarantine_purge_clears_disk_and_rows(tmp_path):
    b = _broker(tmp_path)
    b.admit(b"<script>e()</script>", filename="x.html", content_type="text/html")
    assert b.quarantine.list(verdict="quarantine")
    n = b.quarantine.purge("quarantine")
    assert n >= 1
    assert not b.quarantine.list(verdict="quarantine")


def test_quarantine_idempotent_on_same_sha(tmp_path):
    b = _broker(tmp_path)
    payload = b"<p>same</p>"
    b.admit(payload, filename="x.html", content_type="text/html")
    b.admit(payload, filename="x.html", content_type="text/html")
    rows = b.quarantine.list()
    assert len(rows) == 1


def test_broker_redteam_suite(tmp_path):
    """Mini redteam: EICAR + zip bomb + JS-laden HTML + JS PDF all blocked."""
    b = _broker(tmp_path)

    def _bomb_zip() -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for i in range(120):
                zf.writestr(f"f{i}.txt", b"A" * (10 * 1024 * 1024))
        return buf.getvalue()

    cases = [
        (EICAR_SIGNATURE, "t.bin", "text/plain", Verdict.REJECT),
        (_bomb_zip(), "bomb.zip", "application/zip", Verdict.REJECT),
        (b"<script>x</script>", "p.html", "text/html", Verdict.QUARANTINE),
        (b"%PDF-1.4\n/JS (alert)\n", "a.pdf", "application/pdf", Verdict.QUARANTINE),
    ]
    for payload, fn, ct, expected in cases:
        out = b.admit(payload, filename=fn, content_type=ct)
        assert out.verdict is expected, (fn, out.verdict, out.scan_results)


def test_build_default_broker_works(tmp_path):
    b = build_default_broker(tmp_path)
    out = b.admit(b"<p>hello</p>", filename="x.html", content_type="text/html")
    assert out.verdict is Verdict.ADMIT
