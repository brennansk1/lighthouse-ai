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

Text is normalized per §13.14 (Unicode NFC, zero-width/control strip) so that
downstream chunking and hashing operate on a stable, canonical form.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

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


def _html_to_text(payload: bytes) -> str:
    """HTML → readable text.

    Prefer ``trafilatura`` when importable because it does real boilerplate
    removal (nav/footer/ads). When it is absent we fall back to a stdlib regex
    pass that strips ``<script>``/``<style>``/comments, removes the remaining
    tags, unescapes entities, and collapses whitespace. The fallback is crude
    but deterministic and dependency-free, which the design requires.
    """
    import html as html_mod

    raw = payload.decode("utf-8", errors="replace")

    try:
        import trafilatura  # type: ignore
    except ImportError:
        trafilatura = None

    if trafilatura is not None:
        extracted = trafilatura.extract(raw)  # type: ignore[union-attr]
        if extracted:
            return extracted

    # Stdlib fallback.
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

    Tries ``pypdf`` then ``pdfminer.six``; both are optional. When neither is
    importable we return ``("", False)`` so the caller can flag the Document as
    having an unavailable extractor rather than silently producing garbage.
    """
    import io

    try:
        import pypdf  # type: ignore

        reader = pypdf.PdfReader(io.BytesIO(payload))
        # Extract page-by-page so one corrupt page doesn't lose the whole doc.
        parts: list[str] = []
        for i, page in enumerate(reader.pages):
            try:
                parts.append(page.extract_text() or "")
            except Exception as page_exc:  # noqa: BLE001 - skip the bad page only
                log.warning("ingest.pdf_page_failed", page=i, error=str(page_exc))
        return "\n\n".join(parts), True
    except ImportError:
        pass
    except Exception as exc:
        log.warning("ingest.pdf_pypdf_failed", error=str(exc))

    try:
        from pdfminer.high_level import extract_text as _pdfminer_extract  # type: ignore

        return _pdfminer_extract(io.BytesIO(payload)), True
    except ImportError:
        return "", False
    except Exception as exc:
        log.warning("ingest.pdf_pdfminer_failed", error=str(exc))
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
        return _normalize(_html_to_text(payload))
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


def fetch_and_ingest(url: str, broker: SandboxBroker,
                     client: httpx.Client | None = None) -> Document | None:
    """Fetch a URL over HTTP and ingest the response body.

    ``client`` is injectable so tests can mock transport (via ``respx``) without
    touching the network — the production default constructs a short-lived
    ``httpx.Client`` with redirects enabled. The server-declared Content-Type
    header is forwarded to the broker/extractor.
    """
    import httpx

    owns_client = client is None
    if client is None:
        client = httpx.Client(follow_redirects=True, timeout=30.0)
    try:
        resp = client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type")
        filename = Path(httpx.URL(url).path).name or None
        return ingest_bytes(resp.content, url=url, filename=filename,
                            content_type=content_type, broker=broker)
    finally:
        if owns_client:
            client.close()


def _sha256(payload: bytes) -> str:
    """Expose the same digest the broker/quarantine use, for callers/tests."""
    return hashlib.sha256(payload).hexdigest()
