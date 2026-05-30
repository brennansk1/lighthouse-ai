"""Document ingestion (§13) — raw bytes/files/URLs into clean ``Document``s.

Every byte that enters Lighthouse from the outside world must pass through the
:class:`~lighthouse_ai.sandbox.broker.SandboxBroker` *before* we ever attempt to
parse it. Parsing untrusted content (HTML, PDF) is itself an attack surface, so
the broker's admit/quarantine/reject decision is the first gate. Only after the
broker declines to REJECT do we extract readable text.

Extraction strategy mirrors the design's tier table (§13.1) but degrades
gracefully: the production stack uses ``trafilatura``/``docling``, yet this
module must work with *none* of those optional dependencies installed. We
therefore import them lazily inside ``try/except ImportError`` and fall back to
stdlib-only extraction so the core pipeline is never blocked on a heavy,
optional parser.

PDF extraction chain (§13.1):
  1. ``pdfplumber``  — accurate text + layout (extraction extra)
  2. ``pypdf``       — fast, pure-Python fallback
  3. ``pdfminer.six``— robust low-level fallback
  4. ``docling``     — complex/structured PDFs (extraction extra, slow)
  5. ``PyMuPDF``     — AGPL; **only** when ``LIGHTHOUSE_PDF_FAST=1`` is set
  6. ``("", False)`` — no parser available

HTML extraction chain:
  1. ``trafilatura`` — boilerplate removal (primary)
  2. ``docling``     — office/complex documents (docx, pptx, etc.)
  3. stdlib regex    — always-available fallback

Text is normalized per §13.14 (Unicode NFC, zero-width/control strip) so that
downstream chunking and hashing operate on a stable, canonical form.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from .governor.egress_proxy import DEFAULT_ALLOWED_DOMAINS, EgressProxy, PrivacyTier, extract_host
from .net import EgressBlocked
from .rag.chunker import Document
from .sandbox.broker import SandboxBroker, Verdict

log = structlog.get_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import httpx

# Sentinel appended to extractor results so callers (and tests) can detect that
# a PDF arrived but no PDF parser was importable. We expose it as text-free so
# the resulting Document has empty body but the metadata flag tells the truth.
PDF_UNAVAILABLE_FLAG = "pdf_extractor_unavailable"

# Default body cap (§13.14). 5 MB of *text* is already enormous for a single
# source; capping protects the embedder and the DB from pathological inputs.
DEFAULT_MAX_TEXT_BYTES = 5 * 1024 * 1024

# Strip script/style blocks wholesale before we drop the remaining tags, so we
# never surface JavaScript or CSS as if it were readable prose.
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\f\v]+")
_BLANKLINES_RE = re.compile(r"\n\s*\n\s*\n+")

# Characters that carry no readable meaning but can break hashing/embedding or
# enable bidi/zero-width spoofing (§13.14). Stripped during normalization.
_ZERO_WIDTH = dict.fromkeys(
    ord(c) for c in "​‌‍⁠﻿‎‏‪‫"
    "‬‭‮"
)

# Minimal HTML entity map for the stdlib fallback. ``html.unescape`` covers the
# full set; this constant documents the common cases we care about most.
_COMMON_ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
                    "&#39;": "'", "&nbsp;": " "}


def _normalize(text: str) -> str:
    """Canonicalize extracted text (§13.14).

    NFC composition + zero-width/bidi strip + control-char removal gives a
    stable byte representation so the same logical document always hashes and
    chunks identically regardless of source encoding quirks.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_ZERO_WIDTH)
    # Drop C0/C1 control characters except tab/newline which carry structure.
    text = "".join(
        ch for ch in text
        if ch in ("\t", "\n") or unicodedata.category(ch) != "Cc"
    )
    # Collapse intra-line whitespace and excessive blank lines.
    text = _WS_RE.sub(" ", text)
    text = _BLANKLINES_RE.sub("\n\n", text)
    return text.strip()


def _looks_like_html(payload: bytes, content_type: str | None,
                     filename: str | None) -> bool:
    ct = (content_type or "").lower()
    if "html" in ct or "xml" in ct:
        return True
    if filename and filename.lower().endswith((".html", ".htm", ".xhtml")):
        return True
    head = payload[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or b"<html" in head


def _looks_like_pdf(payload: bytes, content_type: str | None,
                    filename: str | None) -> bool:
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return True
    if filename and filename.lower().endswith(".pdf"):
        return True
    return payload[:5].startswith(b"%PDF")


def _looks_like_office_doc(content_type: str | None,
                            filename: str | None) -> bool:
    """Return True for office/complex document MIME types and extensions."""
    ct = (content_type or "").lower()
    _office_mime = {
        "application/vnd.openxmlformats-officedocument.wordprocessingml",
        "application/vnd.openxmlformats-officedocument.presentationml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml",
        "application/msword",
        "application/vnd.ms-powerpoint",
        "application/vnd.ms-excel",
    }
    if any(m in ct for m in _office_mime):
        return True
    if filename:
        return Path(filename).suffix.lower() in {
            ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".odt", ".odp"
        }
    return False


def _html_to_text(payload: bytes, content_type: str | None = None,
                  filename: str | None = None) -> str:
    """HTML/office → readable text.

    Chain:
      1. ``trafilatura`` — primary for HTML (boilerplate removal)
      2. ``docling``     — for office/complex document types (docx, pptx, …)
      3. stdlib regex    — always-available fallback

    The stdlib path is crude but deterministic and dependency-free, which the
    design requires (§13.1).
    """
    import html as html_mod

    raw = payload.decode("utf-8", errors="replace")

    # 1. trafilatura — primary HTML extractor
    try:
        import trafilatura  # type: ignore
    except ImportError:
        trafilatura = None

    if trafilatura is not None:
        extracted = trafilatura.extract(raw)  # type: ignore[union-attr]
        if extracted:
            return extracted

    # 2. docling — office/complex document types
    if _looks_like_office_doc(content_type, filename):
        try:
            import io

            from docling.document_converter import DocumentConverter  # type: ignore

            converter = DocumentConverter()
            result = converter.convert(io.BytesIO(payload))
            if result and result.document:
                md = result.document.export_to_markdown()
                if md:
                    log.debug("ingest.html_docling_ok", filename=filename)
                    return md
        except ImportError:
            pass
        except Exception as exc:
            log.warning("ingest.html_docling_failed", error=str(exc))

    # 3. Stdlib fallback.
    stripped = _SCRIPT_STYLE_RE.sub(" ", raw)
    stripped = _COMMENT_RE.sub(" ", stripped)
    # Insert breaks at block boundaries so words don't fuse across tags.
    stripped = re.sub(r"<\s*(br|/p|/div|/li|/h[1-6])\b[^>]*>", "\n",
                      stripped, flags=re.IGNORECASE)
    stripped = _TAG_RE.sub(" ", stripped)
    text = html_mod.unescape(stripped)
    return text


def _pdf_to_text(payload: bytes) -> tuple[str, bool]:
    """PDF → (text, extracted_ok).

    Extraction chain (§13.1, in priority order):
      1. ``pdfplumber``  — accurate text + layout; in the ``extraction`` extra
      2. ``pypdf``       — fast pure-Python fallback
      3. ``pdfminer.six``— robust low-level fallback
      4. ``docling``     — complex/structured PDFs; in the ``extraction`` extra
      5. ``PyMuPDF``     — AGPL opt-in; only when ``LIGHTHOUSE_PDF_FAST=1``
      6. ``("", False)`` — no parser available; caller sets the unavailable flag

    All imports are lazy so this module works with zero optional deps installed.
    """
    import io

    # 1. pdfplumber — most accurate text + layout extraction
    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(io.BytesIO(payload)) as pdf:
            parts = [(page.extract_text() or "") for page in pdf.pages]
        text = "\n\n".join(parts)
        log.debug("ingest.pdf_pdfplumber_ok", pages=len(parts))
        return text, True
    except ImportError:
        pass
    except Exception as exc:
        log.warning("ingest.pdf_pdfplumber_failed", error=str(exc))

    # 2. pypdf — fast pure-Python fallback
    try:
        import pypdf  # type: ignore

        reader = pypdf.PdfReader(io.BytesIO(payload))
        parts = [(page.extract_text() or "") for page in reader.pages]
        text = "\n\n".join(parts)
        log.debug("ingest.pdf_pypdf_ok", pages=len(parts))
        return text, True
    except ImportError:
        pass
    except Exception as exc:
        log.warning("ingest.pdf_pypdf_failed", error=str(exc))

    # 3. pdfminer.six — robust low-level fallback
    try:
        from pdfminer.high_level import extract_text as _pdfminer_extract  # type: ignore

        text = _pdfminer_extract(io.BytesIO(payload))
        log.debug("ingest.pdf_pdfminer_ok")
        return text, True
    except ImportError:
        pass
    except Exception as exc:
        log.warning("ingest.pdf_pdfminer_failed", error=str(exc))

    # 4. docling — handles complex/structured PDFs (tables, multi-column)
    try:
        from docling.document_converter import DocumentConverter  # type: ignore

        converter = DocumentConverter()
        result = converter.convert(io.BytesIO(payload))
        if result and result.document:
            md = result.document.export_to_markdown()
            if md:
                log.debug("ingest.pdf_docling_ok")
                return md, True
    except ImportError:
        pass
    except Exception as exc:
        log.warning("ingest.pdf_docling_failed", error=str(exc))

    # 5. PyMuPDF (fitz) — AGPL; only when explicitly opted in via env flag.
    # Never used by default to avoid AGPL licence contamination in projects
    # that link against Lighthouse under a permissive licence.
    if os.environ.get("LIGHTHOUSE_PDF_FAST", "").strip() == "1":
        try:
            import fitz  # type: ignore  # PyMuPDF

            doc = fitz.open(stream=payload, filetype="pdf")
            parts = [page.get_text() for page in doc]
            doc.close()
            text = "\n\n".join(parts)
            log.debug("ingest.pdf_pymupdf_ok", pages=len(parts))
            return text, True
        except ImportError:
            pass
        except Exception as exc:
            log.warning("ingest.pdf_pymupdf_failed", error=str(exc))

    # No parser available.
    return "", False


def extract_text(payload: bytes, content_type: str | None,
                 filename: str | None) -> str:
    """Extract readable, normalized text from raw bytes.

    Dispatches on content-type/filename/sniffed magic: HTML is reduced to prose,
    PDF is parsed if a backend exists (else empty), and everything else is
    treated as plain UTF-8 text. The result is always run through ``_normalize``
    so callers receive canonical text regardless of source format.
    """
    if _looks_like_pdf(payload, content_type, filename):
        text, _ok = _pdf_to_text(payload)
        return _normalize(text)
    if _looks_like_html(payload, content_type, filename):
        return _normalize(_html_to_text(payload, content_type, filename))
    # Plain text (or unknown binary decoded leniently).
    return _normalize(payload.decode("utf-8", errors="replace"))


def _build_document(payload: bytes, *, text: str, source: str | None,
                    content_type: str | None, sha256: str,
                    extra_meta: dict | None = None) -> Document:
    """Assemble a ``Document`` with provenance metadata (§13.14, §14.2).

    The id is derived from the content hash so identical bytes always yield the
    same Document id — this is what makes ingestion idempotent and lets the
    quarantine/corpus dedupe naturally.
    """
    metadata: dict = {
        "source": source,
        "content_type": content_type,
        "sha256": sha256,
        "bytes_size": len(payload),
    }
    if extra_meta:
        metadata.update(extra_meta)
    return Document(id=f"sha256:{sha256}", text=text, metadata=metadata)


def ingest_bytes(payload: bytes, *, url: str | None = None,
                 filename: str | None = None,
                 content_type: str | None = None,
                 broker: SandboxBroker) -> Document | None:
    """Run the sandbox, then extract text into a ``Document``.

    The broker is the *first* operation: we never parse bytes the sandbox would
    reject. A REJECT verdict short-circuits to ``None`` (caller treats it as
    "dropped"); ADMIT and QUARANTINE both proceed to extraction because
    quarantined content is still recorded and may be elevated later, and the
    design wants its text available for review.
    """
    outcome = broker.admit(payload, url=url, filename=filename,
                           content_type=content_type)
    if outcome.verdict is Verdict.REJECT:
        return None

    pdf = _looks_like_pdf(payload, content_type, filename)
    if pdf:
        body, ok = _pdf_to_text(payload)
        text = _normalize(body)
        extra: dict = {"verdict": outcome.verdict.value}
        if not ok:
            extra[PDF_UNAVAILABLE_FLAG] = True
    else:
        text = extract_text(payload, content_type, filename)
        extra = {"verdict": outcome.verdict.value}

    if len(text.encode("utf-8")) > DEFAULT_MAX_TEXT_BYTES:
        # Cap on a byte boundary that won't split a UTF-8 sequence.
        text = text.encode("utf-8")[:DEFAULT_MAX_TEXT_BYTES].decode(
            "utf-8", errors="ignore")
        extra["truncated"] = True

    return _build_document(
        payload, text=text, source=url or filename,
        content_type=content_type, sha256=outcome.sha256, extra_meta=extra,
    )


def ingest_file(path: str | Path, broker: SandboxBroker) -> Document | None:
    """Read a local file and ingest its bytes.

    Content-type is inferred from the suffix via ``mimetypes`` so the broker's
    scanners and the extractor dispatch correctly without a network round-trip.
    """
    import mimetypes

    p = Path(path)
    payload = p.read_bytes()
    content_type, _ = mimetypes.guess_type(p.name)
    return ingest_bytes(payload, url=p.as_uri(), filename=p.name,
                        content_type=content_type, broker=broker)


def fetch_and_ingest(
    url: str,
    broker: SandboxBroker,
    client: httpx.Client | None = None,
    *,
    log_path: Path | None = None,
    proxy: EgressProxy | None = None,
    allow_host: bool = True,
) -> Document | None:
    """Fetch a URL over HTTP and ingest the response body.

    Every outbound fetch is gated and logged through the egress proxy before any
    bytes are transferred — the policy decision and audit record precede the
    socket open.

    ``client`` is injectable so tests can mock transport (via ``respx``) without
    touching the network — the production default constructs a short-lived
    ``httpx.Client`` with redirects enabled. The server-declared Content-Type
    header is forwarded to the broker/extractor.

    ``log_path`` — if provided, the proxy appends one JSON line per fetch to
    this file (``egress.jsonl`` style). Defaults to ``None`` = no file write.

    ``proxy`` — inject a pre-built :class:`~lighthouse_ai.governor.egress_proxy.EgressProxy`
    (e.g. for test log capture). When ``None`` a proxy is constructed from
    ``DEFAULT_ALLOWED_DOMAINS`` plus the URL's own host (when ``allow_host=True``).

    ``allow_host`` (default ``True``) — when ``True`` the URL's own host is added
    to the allowlist before the check, so an explicit user-typed URL is always
    permitted (but still logged). Pass ``False`` for programmatic/skill fetches
    that should be gated by the strict allowlist; a non-allowlisted host raises
    :class:`~lighthouse_ai.net.EgressBlocked` *before* any network I/O.
    """
    import httpx

    host = extract_host(url)

    # Build (or use injected) egress proxy.
    if proxy is None:
        if allow_host and host:
            allowed = frozenset(DEFAULT_ALLOWED_DOMAINS | {host})
        else:
            allowed = DEFAULT_ALLOWED_DOMAINS
        active_proxy: EgressProxy = EgressProxy(allowed, log_path)
    else:
        active_proxy = proxy

    # Policy decision — BEFORE any socket is opened.
    decision = active_proxy.check(url, PrivacyTier.PUBLIC_OK)
    if not decision.allowed:
        # Log the denied attempt when we have a log path (proxy owns the path).
        active_proxy.log_connection(
            decision.host or host,
            port=_default_port(url),
            bytes_sent=0,
            bytes_received=0,
            duration_ms=0.0,
            tier=PrivacyTier.PUBLIC_OK,
            allowed=False,
            reason=decision.reason,
        )
        raise EgressBlocked(decision.reason)

    owns_client = client is None
    if client is None:
        client = httpx.Client(follow_redirects=True, timeout=30.0)
    try:
        started = time.monotonic()
        resp = client.get(url)
        duration_ms = (time.monotonic() - started) * 1000.0

        # Redirect-aware egress enforcement: the policy decision above gates the
        # *requested* URL, but ``follow_redirects`` may have walked the client to
        # an entirely different host whose bytes are now buffered in ``resp``.
        # Re-check the FINAL host against the same proxy; a redirect to a
        # non-allowlisted host is an egress-policy bypass (SSRF / DNS-rebinding
        # vector, §15) and must be refused even though the bytes were fetched —
        # we drop them on the floor and never hand them to the broker/extractor.
        final_url = str(resp.url)
        final_host = extract_host(final_url)
        if final_host != decision.host:
            final_decision = active_proxy.check(final_url, PrivacyTier.PUBLIC_OK)
            if not final_decision.allowed:
                active_proxy.log_connection(
                    final_decision.host or final_host,
                    port=_default_port(final_url),
                    bytes_sent=0,
                    bytes_received=0,
                    duration_ms=duration_ms,
                    tier=PrivacyTier.PUBLIC_OK,
                    allowed=False,
                    reason=f"redirect to disallowed host: {final_decision.reason}",
                )
                raise EgressBlocked(
                    f"redirect to disallowed host {final_host!r}: "
                    f"{final_decision.reason}"
                )

        resp.raise_for_status()

        # Audit log — real byte/duration figures, post-fetch.
        # ``resp.request.content`` raises ``RequestNotRead`` when the request
        # body was never buffered (e.g. mocked transports or streaming GET
        # requests). A GET body is always empty anyway, so 0 is correct.
        try:
            request_bytes = (
                len(resp.request.content) if resp.request is not None else 0
            )
        except Exception:
            request_bytes = 0
        active_proxy.log_connection(
            final_host or decision.host or host,
            port=_default_port(final_url),
            bytes_sent=request_bytes,
            bytes_received=len(resp.content),
            duration_ms=duration_ms,
            tier=PrivacyTier.PUBLIC_OK,
            allowed=True,
            reason="fetched",
        )

        content_type = resp.headers.get("content-type")
        filename = Path(httpx.URL(url).path).name or None
        return ingest_bytes(resp.content, url=url, filename=filename,
                            content_type=content_type, broker=broker)
    finally:
        if owns_client:
            client.close()


def _default_port(url: str) -> int:
    """Infer port from URL scheme when no explicit port is present."""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.port is not None:
        return parts.port
    return 443 if parts.scheme == "https" else 80


def _sha256(payload: bytes) -> str:
    """Expose the same digest the broker/quarantine use, for callers/tests."""
    return hashlib.sha256(payload).hexdigest()
