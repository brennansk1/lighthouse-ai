"""Content scanners (§15.5). Each scanner inspects bytes and returns a verdict.

The bundled scanners are pure-Python — they don't depend on qpdf, oletools,
or ClamAV being installed. Production wraps those tools and adds a YARA
ruleset that syncs daily from MalwareBazaar / ThreatFox / URLhaus.

Scanners deliberately err on the side of *quarantine* (not reject) when
they detect ambiguity. The Broker decides final admit/quarantine/reject
policy by aggregating scanner verdicts.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from typing import Literal, Protocol

VerdictKind = Literal["clean", "quarantine", "reject"]


@dataclass(frozen=True)
class ScanResult:
    scanner: str
    verdict: VerdictKind
    reason: str = ""
    details: dict | None = None


class Scanner(Protocol):
    name: str

    def supports(self, *, content_type: str, filename: str | None = None) -> bool: ...

    def scan(self, payload: bytes, *, filename: str | None = None) -> ScanResult: ...


# --- PDF JavaScript scanner ----------------------------------------------

_PDF_JS_PATTERNS = [
    rb"/JavaScript",
    rb"/JS",
    rb"/OpenAction",
    rb"/Launch",
    rb"/EmbeddedFile",
]


class PDFJavaScriptScanner:
    name = "pdf_js"

    def supports(self, *, content_type: str, filename: str | None = None) -> bool:
        if "pdf" in (content_type or "").lower():
            return True
        if filename and filename.lower().endswith(".pdf"):
            return True
        return False

    def scan(self, payload: bytes, *, filename: str | None = None) -> ScanResult:
        if not payload.startswith(b"%PDF"):
            return ScanResult(self.name, "quarantine",
                              "missing %PDF header — not a valid PDF")
        hits = [p for p in _PDF_JS_PATTERNS if p in payload]
        if hits:
            return ScanResult(
                self.name, "quarantine",
                f"active-content markers: {[h.decode(errors='replace') for h in hits]}",
                {"hits": [h.decode(errors='replace') for h in hits]},
            )
        return ScanResult(self.name, "clean")


# --- HTML script scanner -------------------------------------------------

_HTML_DANGER_RE = re.compile(
    rb"<script\b|on\w+\s*=\s*[\"']|javascript:",
    re.IGNORECASE,
)
_SVG_SCRIPT_RE = re.compile(rb"<script\b", re.IGNORECASE)


class HTMLScriptScanner:
    name = "html_script"

    def supports(self, *, content_type: str, filename: str | None = None) -> bool:
        ct = (content_type or "").lower()
        if "html" in ct or "xml" in ct or "svg" in ct:
            return True
        if filename and filename.lower().endswith((".html", ".htm", ".svg", ".xhtml")):
            return True
        return False

    def scan(self, payload: bytes, *, filename: str | None = None) -> ScanResult:
        is_svg = (filename or "").lower().endswith(".svg") or b"<svg" in payload[:200]
        pattern = _SVG_SCRIPT_RE if is_svg else _HTML_DANGER_RE
        if pattern.search(payload):
            return ScanResult(self.name, "quarantine",
                              "active content (script / event handler / javascript:)")
        return ScanResult(self.name, "clean")


# --- Archive bomb scanner ------------------------------------------------

class ArchiveBombScanner:
    """Reject zip archives whose declared size exceeds a compression ratio.

    Heuristic: if the *declared* uncompressed total is more than
    ``max_ratio`` × the compressed payload, treat as a bomb.
    """

    name = "archive_bomb"

    def __init__(self, max_ratio: float = 100.0, max_uncompressed_mb: int = 1024):
        self.max_ratio = max_ratio
        self.max_uncompressed_mb = max_uncompressed_mb

    def supports(self, *, content_type: str, filename: str | None = None) -> bool:
        ct = (content_type or "").lower()
        if "zip" in ct or "x-zip" in ct:
            return True
        if filename and filename.lower().endswith((".zip", ".docx", ".xlsx", ".epub")):
            return True
        return False

    def scan(self, payload: bytes, *, filename: str | None = None) -> ScanResult:
        import io
        compressed_size = max(len(payload), 1)
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                uncompressed = sum(zi.file_size for zi in zf.infolist())
        except zipfile.BadZipFile:
            return ScanResult(self.name, "reject", "not a valid zip archive")
        ratio = uncompressed / compressed_size
        if uncompressed > self.max_uncompressed_mb * 1024 * 1024:
            return ScanResult(self.name, "reject",
                              f"declared {uncompressed} bytes exceeds "
                              f"{self.max_uncompressed_mb}MB cap")
        if ratio > self.max_ratio:
            return ScanResult(self.name, "reject",
                              f"compression ratio {ratio:.1f} > {self.max_ratio}",
                              {"ratio": ratio, "uncompressed": uncompressed})
        return ScanResult(self.name, "clean",
                          details={"ratio": ratio, "uncompressed": uncompressed})


# --- EICAR test scanner (proves wiring) ---------------------------------

EICAR_SIGNATURE = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class EICARScanner:
    """Detects the well-known EICAR antivirus test signature.

    This is what the design's ``lighthouse sandbox redteam`` exercise uses.
    Real installs add ClamAV behind the same interface.
    """

    name = "eicar"

    def supports(self, *, content_type: str, filename: str | None = None) -> bool:
        return True  # always check

    def scan(self, payload: bytes, *, filename: str | None = None) -> ScanResult:
        if EICAR_SIGNATURE in payload:
            return ScanResult(self.name, "reject", "EICAR antivirus test signature")
        return ScanResult(self.name, "clean")
