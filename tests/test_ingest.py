"""Tests for the document ingestion module (§13).

These exercise the stdlib-only paths because the optional heavy extractors
(trafilatura/pypdf/pdfminer) are not assumed installed in CI. We verify the
security-first ordering (sandbox before parse), text extraction, normalization,
metadata provenance, and the injectable HTTP fetch path (mocked with respx).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import httpx
import pytest
import respx

from lighthouse_ai.ingest import (
    DEFAULT_MAX_TEXT_BYTES,
    PDF_UNAVAILABLE_FLAG,
    extract_text,
    fetch_and_ingest,
    ingest_bytes,
    ingest_file,
)
from lighthouse_ai.rag.chunker import Document, chunk_document
from lighthouse_ai.sandbox.broker import SandboxBroker, Verdict
from lighthouse_ai.sandbox.quarantine import Quarantine
from lighthouse_ai.sandbox.scanners import EICAR_SIGNATURE, EICARScanner


@pytest.fixture
def broker(tmp_path: Path) -> SandboxBroker:
    """A broker backed by a temp quarantine DB with only the EICAR scanner.

    EICARScanner is the canonical redteam check and is auto-installed by the
    broker anyway; passing it explicitly documents intent.
    """
    q = Quarantine(tmp_path / "quarantine.db", tmp_path / "quarantine")
    return SandboxBroker(q, [EICARScanner()])


# --- extract_text: HTML --------------------------------------------------

def test_html_strips_tags() -> None:
    html = b"<html><body><h1>Title</h1><p>Hello world</p></body></html>"
    text = extract_text(html, "text/html", None)
    assert "Title" in text
    assert "Hello world" in text
    assert "<" not in text and ">" not in text


def test_html_strips_script() -> None:
    html = b"<p>visible</p><script>alert('xss');var secret=1;</script>"
    text = extract_text(html, "text/html", None)
    assert "visible" in text
    assert "alert" not in text
    assert "secret" not in text


def test_html_strips_style() -> None:
    html = b"<style>.x{color:red;font-size:99px}</style><p>body text</p>"
    text = extract_text(html, "text/html", None)
    assert "body text" in text
    assert "color" not in text
    assert "font-size" not in text


def test_html_strips_comments() -> None:
    html = b"<!-- hidden note --><p>shown</p>"
    text = extract_text(html, "text/html", None)
    assert "shown" in text
    assert "hidden note" not in text


def test_html_unescapes_entities() -> None:
    html = b"<p>A &amp; B &lt;tag&gt; &quot;q&quot;</p>"
    text = extract_text(html, "text/html", None)
    assert "A & B" in text
    assert "<tag>" in text
    assert '"q"' in text


def test_html_detected_by_filename() -> None:
    text = extract_text(b"<h1>Hi</h1>", None, "page.html")
    assert text == "Hi"


def test_html_detected_by_sniff() -> None:
    text = extract_text(b"<!DOCTYPE html><html><p>sniffed</p></html>", None, None)
    assert "sniffed" in text


def test_html_block_boundaries_separate_words() -> None:
    html = b"<li>one</li><li>two</li>"
    text = extract_text(html, "text/html", None)
    assert "one" in text and "two" in text
    # The two list items must be separated by whitespace, not fused.
    assert "onetwo" not in text
    assert re.search(r"one\s+two", text)


# --- extract_text: plain text -------------------------------------------

def test_plaintext_passthrough() -> None:
    assert extract_text(b"just some words", "text/plain", None) == "just some words"


def test_plaintext_unknown_type_is_decoded() -> None:
    assert extract_text(b"raw bytes here", None, None) == "raw bytes here"


def test_whitespace_collapsed() -> None:
    assert extract_text(b"a    b\t\tc", "text/plain", None) == "a b c"


def test_normalization_strips_zero_width() -> None:
    # Zero-width space (U+200B) embedded between words must be removed (§13.14).
    payload = "clean​text".encode("utf-8")
    assert extract_text(payload, "text/plain", None) == "cleantext"


def test_normalization_strips_control_chars() -> None:
    payload = b"good\x00\x07text"
    out = extract_text(payload, "text/plain", None)
    assert "\x00" not in out and "\x07" not in out
    assert "goodtext" in out.replace(" ", "")


# --- extract_text: PDF (no extractor installed) -------------------------

def test_pdf_without_extractor_returns_empty() -> None:
    # pypdf/pdfminer are optional; with neither installed we get "".
    pytest.importorskip  # marker; we explicitly assert the absent-dep path
    try:
        import pypdf  # noqa: F401
        pytest.skip("pypdf is installed; absent-dep path not exercised")
    except ImportError:
        pass
    pdf = b"%PDF-1.4 fake pdf body"
    assert extract_text(pdf, "application/pdf", None) == ""


# --- ingest_bytes: sandbox ordering -------------------------------------

def test_reject_short_circuits_to_none(broker: SandboxBroker) -> None:
    payload = b"prefix " + EICAR_SIGNATURE + b" suffix"
    assert ingest_bytes(payload, content_type="text/plain", broker=broker) is None


def test_reject_records_quarantine_verdict(broker: SandboxBroker) -> None:
    ingest_bytes(EICAR_SIGNATURE, content_type="text/plain", broker=broker)
    rows = broker.quarantine.list(verdict="reject")
    assert len(rows) == 1
    assert rows[0]["verdict"] == "reject"


def test_admit_returns_document(broker: SandboxBroker) -> None:
    doc = ingest_bytes(b"hello clean content", content_type="text/plain",
                       broker=broker)
    assert isinstance(doc, Document)
    assert doc.text == "hello clean content"
    assert doc.metadata["verdict"] == Verdict.ADMIT.value


# --- ingest_bytes: metadata / provenance --------------------------------

def test_document_id_and_sha256_metadata(broker: SandboxBroker) -> None:
    payload = b"deterministic body"
    expected = hashlib.sha256(payload).hexdigest()
    doc = ingest_bytes(payload, url="https://x.test/a", content_type="text/plain",
                       broker=broker)
    assert doc is not None
    assert doc.metadata["sha256"] == expected
    assert doc.id == f"sha256:{expected}"
    assert doc.metadata["source"] == "https://x.test/a"
    assert doc.metadata["content_type"] == "text/plain"
    assert doc.metadata["bytes_size"] == len(payload)


def test_identical_bytes_produce_same_id(broker: SandboxBroker) -> None:
    a = ingest_bytes(b"same", content_type="text/plain", broker=broker)
    b = ingest_bytes(b"same", content_type="text/plain", broker=broker)
    assert a is not None and b is not None
    assert a.id == b.id


def test_pdf_sets_unavailable_flag(broker: SandboxBroker) -> None:
    try:
        import pypdf  # noqa: F401
        pytest.skip("pypdf installed; flag not set")
    except ImportError:
        pass
    doc = ingest_bytes(b"%PDF-1.4 minimal", content_type="application/pdf",
                       broker=broker)
    # %PDF header with no active content -> EICAR-only broker admits it.
    assert doc is not None
    assert doc.metadata.get(PDF_UNAVAILABLE_FLAG) is True
    assert doc.text == ""


def test_oversized_text_is_truncated(broker: SandboxBroker) -> None:
    big = b"a" * (DEFAULT_MAX_TEXT_BYTES + 1000)
    doc = ingest_bytes(big, content_type="text/plain", broker=broker)
    assert doc is not None
    assert doc.metadata.get("truncated") is True
    assert len(doc.text.encode("utf-8")) <= DEFAULT_MAX_TEXT_BYTES


# --- ingest produces chunkable documents --------------------------------

def test_document_is_chunkable(broker: SandboxBroker) -> None:
    doc = ingest_bytes(b"One sentence. Two sentence. Three.",
                       content_type="text/plain", broker=broker)
    assert doc is not None
    chunks = chunk_document(doc)
    assert chunks
    assert all(c.document_id == doc.id for c in chunks)


# --- ingest_file --------------------------------------------------------

def test_ingest_file_reads_html(tmp_path: Path, broker: SandboxBroker) -> None:
    f = tmp_path / "doc.html"
    f.write_bytes(b"<html><p>file content</p></html>")
    doc = ingest_file(f, broker)
    assert doc is not None
    assert "file content" in doc.text
    assert doc.metadata["source"] == f.as_uri()


def test_ingest_file_rejects_eicar(tmp_path: Path, broker: SandboxBroker) -> None:
    f = tmp_path / "bad.txt"
    f.write_bytes(EICAR_SIGNATURE)
    assert ingest_file(f, broker) is None


# --- fetch_and_ingest (mocked with respx) -------------------------------

@respx.mock
def test_fetch_and_ingest_html(broker: SandboxBroker) -> None:
    route = respx.get("https://example.test/page").mock(
        return_value=httpx.Response(
            200, html="<html><body><p>remote text</p></body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )
    doc = fetch_and_ingest("https://example.test/page", broker)
    assert route.called
    assert doc is not None
    assert "remote text" in doc.text
    assert doc.metadata["source"] == "https://example.test/page"


@respx.mock
def test_fetch_and_ingest_rejects_eicar(broker: SandboxBroker) -> None:
    respx.get("https://evil.test/x").mock(
        return_value=httpx.Response(200, content=EICAR_SIGNATURE,
                                    headers={"content-type": "text/plain"})
    )
    assert fetch_and_ingest("https://evil.test/x", broker) is None


@respx.mock
def test_fetch_and_ingest_raises_on_http_error(broker: SandboxBroker) -> None:
    respx.get("https://example.test/missing").mock(
        return_value=httpx.Response(404)
    )
    with pytest.raises(httpx.HTTPStatusError):
        fetch_and_ingest("https://example.test/missing", broker)


@respx.mock
def test_fetch_and_ingest_uses_injected_client(broker: SandboxBroker) -> None:
    respx.get("https://example.test/inj").mock(
        return_value=httpx.Response(200, text="injected",
                                    headers={"content-type": "text/plain"})
    )
    with httpx.Client() as client:
        doc = fetch_and_ingest("https://example.test/inj", broker, client=client)
    assert doc is not None
    assert doc.text == "injected"


@respx.mock
def test_fetch_and_ingest_follows_redirect(broker: SandboxBroker) -> None:
    respx.get("https://example.test/old").mock(
        return_value=httpx.Response(302, headers={"location": "/new"})
    )
    respx.get("https://example.test/new").mock(
        return_value=httpx.Response(200, text="final",
                                    headers={"content-type": "text/plain"})
    )
    doc = fetch_and_ingest("https://example.test/old", broker)
    assert doc is not None
    assert doc.text == "final"
