"""Content scanners (§15.5). Each scanner inspects bytes and returns a verdict.

The bundled scanners are pure-Python — they don't depend on qpdf, oletools,
or ClamAV being installed. Production wraps those tools and adds a YARA
ruleset that syncs daily from MalwareBazaar / ThreatFox / URLhaus.

Scanners deliberately err on the side of *quarantine* (not reject) when
they detect ambiguity. The Broker decides final admit/quarantine/reject
policy by aggregating scanner verdicts.

Zone H — sandbox hardening (optional extras):
  * :class:`YaraScanner`   — YARA ruleset matching; needs ``yara-python>=4.4``.
  * :class:`PikePdfScanner` — deeper PDF structure inspection; needs ``pikepdf>=9.0``.
  * :func:`hardened_scanners` — factory returning both hardened scanners so callers
    can opt in::

        from lighthouse_ai.sandbox.scanners import hardened_scanners
        from lighthouse_ai.sandbox.broker import build_default_broker
        broker = SandboxBroker(quarantine, build_default_scanners() + hardened_scanners())

    Both scanners degrade gracefully when the underlying library is absent:
    ``supports()`` returns ``False`` and ``scan()`` returns a clean result with an
    explanatory note, so the ``sandbox-hardening`` extra is fully optional.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from typing import Any, Literal, Protocol

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
            return ScanResult(self.name, "quarantine", "missing %PDF header — not a valid PDF")
        hits = [p for p in _PDF_JS_PATTERNS if p in payload]
        if hits:
            return ScanResult(
                self.name,
                "quarantine",
                f"active-content markers: {[h.decode(errors='replace') for h in hits]}",
                {"hits": [h.decode(errors="replace") for h in hits]},
            )
        return ScanResult(self.name, "clean")


# --- HTML script scanner -------------------------------------------------

# NB: the event-handler alternative is ``\bon\w+\s*=`` (no quote required).
# HTML/SVG attribute values may be unquoted (``onerror=alert(1)``), so an
# earlier ``on\w+\s*=\s*["']`` pattern silently admitted unquoted handlers.
# A bare ``on…=`` attribute is always an event handler in HTML, so matching it
# unconditionally is the fail-closed (quarantine) choice; the ``\b`` keeps
# benign substrings like ``reason=`` / ``comparison=`` from matching.
_HTML_DANGER_RE = re.compile(
    rb"<script\b|\bon\w+\s*=|javascript:",
    re.IGNORECASE,
)


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
        # SVG executes <script>, event handlers (onload/onerror/…), and
        # ``javascript:`` URLs in the browser exactly as HTML does, so both
        # markup families get the same full danger check.  (A previous version
        # used a weaker <script>-only pattern for anything that looked like SVG,
        # which let an .html document beginning with <svg> smuggle event
        # handlers through.)
        if _HTML_DANGER_RE.search(payload):
            return ScanResult(
                self.name, "quarantine", "active content (script / event handler / javascript:)"
            )
        return ScanResult(self.name, "clean")


# --- Archive bomb scanner ------------------------------------------------


class ArchiveBombScanner:
    """Reject zip archives whose declared size exceeds a compression ratio.

    Heuristic: if the *declared* uncompressed total is more than
    ``max_ratio`` × the compressed payload, treat as a bomb.

    Recursive inspection (bounded): archive entries that are themselves zip
    archives are opened up to ``_NESTED_DEPTH_CAP`` levels deep and their
    declared-uncompressed sizes are added to the running total, so a
    zip-in-zip where the outer stores the inner bomb verbatim (ratio≈1) is
    caught.  A cap on total entries across all recursion levels prevents a
    scan-time bomb.
    """

    name = "archive_bomb"

    _NESTED_DEPTH_CAP: int = 3  # max recursion depth for nested zips
    _NESTED_ENTRY_CAP: int = 500  # max total entries examined across all levels
    # Never decompress a nested archive larger than this to recurse into it:
    # its *declared* size already counts toward the bomb total, and actually
    # reading a multi-GB nested member into RAM would itself be the
    # memory-exhaustion bomb we are trying to detect (scan-time DoS).
    _NESTED_READ_CAP_BYTES: int = 32 * 1024 * 1024  # 32 MiB

    # Zip-like filename suffixes that warrant recursive inspection.
    _ZIP_EXTENSIONS: tuple[str, ...] = (".zip", ".docx", ".xlsx", ".epub")

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

    def _sum_uncompressed(self, data: bytes, depth: int, entry_counter: list[int]) -> int:
        """Recursively sum declared uncompressed sizes for *data* (a zip blob).

        Parameters
        ----------
        data:
            Raw bytes of a zip file.
        depth:
            Current recursion depth (0 = top level).
        entry_counter:
            Single-element list used as a mutable counter shared across all
            recursive calls.  Incremented per entry; inspection stops when the
            cap is reached to prevent a scan-time bomb.

        Returns
        -------
        int
            Total declared uncompressed bytes, including nested archives.
        """
        import io as _io

        total = 0
        try:
            with zipfile.ZipFile(_io.BytesIO(data)) as zf:
                for zi in zf.infolist():
                    entry_counter[0] += 1
                    if entry_counter[0] > self._NESTED_ENTRY_CAP:
                        break
                    total += zi.file_size
                    # Recurse into nested zips if within depth cap — but only if
                    # the nested archive is small enough to read safely. A nested
                    # member that *declares* a large size has already added that
                    # size to `total` (which trips the bomb check); decompressing
                    # it here would be the scan-time memory bomb itself.
                    if (
                        depth < self._NESTED_DEPTH_CAP
                        and zi.filename.lower().endswith(self._ZIP_EXTENSIONS)
                        and zi.file_size <= self._NESTED_READ_CAP_BYTES
                    ):
                        try:
                            # Bound the actual read too, in case the declared
                            # file_size lies (e.g. is 0 but the stream is huge).
                            with zf.open(zi.filename) as fh:
                                nested_data = fh.read(self._NESTED_READ_CAP_BYTES + 1)
                            if len(nested_data) > self._NESTED_READ_CAP_BYTES:
                                continue  # real content exceeded cap; don't recurse
                        except Exception:
                            continue
                        nested = self._sum_uncompressed(nested_data, depth + 1, entry_counter)
                        total += nested
        except zipfile.BadZipFile:
            pass
        return total

    def scan(self, payload: bytes, *, filename: str | None = None) -> ScanResult:
        import io

        compressed_size = max(len(payload), 1)
        # Validate the outer zip first.
        try:
            with zipfile.ZipFile(io.BytesIO(payload)):
                pass
        except zipfile.BadZipFile:
            return ScanResult(self.name, "reject", "not a valid zip archive")

        entry_counter: list[int] = [0]
        uncompressed = self._sum_uncompressed(payload, depth=0, entry_counter=entry_counter)

        ratio = uncompressed / compressed_size
        if uncompressed > self.max_uncompressed_mb * 1024 * 1024:
            return ScanResult(
                self.name,
                "reject",
                f"declared {uncompressed} bytes exceeds {self.max_uncompressed_mb}MB cap",
            )
        if ratio > self.max_ratio:
            return ScanResult(
                self.name,
                "reject",
                f"compression ratio {ratio:.1f} > {self.max_ratio}",
                {"ratio": ratio, "uncompressed": uncompressed},
            )
        return ScanResult(
            self.name, "clean", details={"ratio": ratio, "uncompressed": uncompressed}
        )


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


# ---------------------------------------------------------------------------
# Zone H — hardened scanners (optional extras: yara-python, pikepdf)
# ---------------------------------------------------------------------------

# Default YARA rules shipped with this module.  The rule set is intentionally
# minimal and false-positive-safe — it targets canonical hostile-payload
# signatures used in adversarial testing rather than production threat intel
# (which is delivered via the daily MalwareBazaar sync described in the design
# doc).  New rules should be vetted against a benign corpus before landing here.
_DEFAULT_YARA_RULES_SOURCE = r"""
rule EICAR_Test_File {
    meta:
        description = "EICAR antivirus test file"
        severity    = "reject"
    strings:
        $eicar = "EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
    condition:
        $eicar
}

rule PDF_Suspicious_OpenAction {
    meta:
        description = "PDF with /OpenAction — may auto-execute on open"
        severity    = "quarantine"
    strings:
        $header    = { 25 50 44 46 }          // %PDF
        $openaction = "/OpenAction" nocase
    condition:
        $header at 0 and $openaction
}

rule PDF_Embedded_JavaScript {
    meta:
        description = "PDF with embedded JavaScript action"
        severity    = "quarantine"
    strings:
        $header = { 25 50 44 46 }
        $js1    = "/JavaScript" nocase
        $js2    = "/JS" nocase
    condition:
        $header at 0 and any of ($js1, $js2)
}

rule PDF_Launch_Action {
    meta:
        description = "PDF /Launch action — can spawn arbitrary processes"
        severity    = "quarantine"
    strings:
        $header = { 25 50 44 46 }
        $launch = "/Launch" nocase
    condition:
        $header at 0 and $launch
}
"""


def _yara_available() -> bool:
    """Return True if yara-python can be imported."""
    try:
        import yara  # noqa: F401

        return True
    except ImportError:
        return False


class YaraScanner:
    """YARA-based scanner using an injected or default ruleset.

    The scanner degrades gracefully when ``yara-python`` is not installed:
    ``supports()`` returns ``False`` so the broker skips it entirely, and
    ``scan()`` returns a clean result with a note about the missing library.

    Parameters
    ----------
    rules_source:
        Raw YARA source string.  Pass a custom string in tests to exercise
        specific rules without touching the filesystem.
    rules_object:
        A pre-compiled ``yara.Rules`` object.  Takes precedence over
        ``rules_source`` when supplied.  Useful for injecting mocks in tests.
    """

    name = "yara"

    def __init__(
        self,
        rules_source: str | None = None,
        rules_object: Any | None = None,
    ) -> None:
        self._rules_source = rules_source or _DEFAULT_YARA_RULES_SOURCE
        self._rules_object = rules_object  # pre-compiled yara.Rules or duck-type
        self._compiled: Any | None = None  # lazy-compiled from rules_source

    def _get_rules(self) -> Any | None:
        """Return compiled rules, compiling from source if needed.

        Returns None when yara-python is unavailable.
        """
        if self._rules_object is not None:
            return self._rules_object
        if self._compiled is not None:
            return self._compiled
        # Honor the same availability check as supports() so the two code paths
        # stay consistent (and so a caller that disables yara is respected even
        # when the library is importable).
        if not _yara_available():
            return None
        try:
            import yara

            self._compiled = yara.compile(source=self._rules_source)
            return self._compiled
        except ImportError:
            return None

    def supports(self, *, content_type: str, filename: str | None = None) -> bool:
        return _yara_available() or self._rules_object is not None

    def scan(self, payload: bytes, *, filename: str | None = None) -> ScanResult:
        rules = self._get_rules()
        if rules is None:
            return ScanResult(
                self.name,
                "clean",
                "yara-python not installed; install sandbox-hardening extra to enable",
            )
        try:
            matches = rules.match(data=payload)
        except Exception as exc:
            return ScanResult(self.name, "quarantine", f"YARA match error: {exc!r}")

        if not matches:
            return ScanResult(self.name, "clean")

        # Determine worst severity from matched rule metadata.
        severity: VerdictKind = "quarantine"
        names: list[str] = []
        for m in matches:
            names.append(m.rule)
            meta_severity = (getattr(m, "meta", {}) or {}).get("severity", "quarantine")
            if meta_severity == "reject":
                severity = "reject"

        return ScanResult(
            self.name,
            severity,
            f"YARA rules matched: {', '.join(names)}",
            {"matched_rules": names},
        )


# ---------------------------------------------------------------------------
# PikePdfScanner
# ---------------------------------------------------------------------------


def _pikepdf_available() -> bool:
    try:
        import pikepdf  # noqa: F401

        return True
    except ImportError:
        return False


class PikePdfScanner:
    """Deep PDF inspection using pikepdf.

    Checks that the existing :class:`PDFJavaScriptScanner` (byte-pattern scan)
    cannot catch reliably:

    * ``/OpenAction`` and ``/AA`` (additional actions) at the catalog level.
    * ``/Launch``, ``/SubmitForm``, ``/ImportData`` action types.
    * Embedded files (``/EmbeddedFile`` stream objects anywhere in the tree).
    * Malformed / absent cross-reference tables (xref) — pikepdf raises
      ``PdfError`` or ``PasswordError`` which we surface as quarantine.

    Degrades cleanly when pikepdf is not installed: ``supports()`` returns
    ``False`` and ``scan()`` returns clean with a note.
    """

    name = "pikepdf"

    # Action sub-types considered dangerous
    _DANGEROUS_ACTION_S = frozenset(
        [
            "/Launch",
            "/JavaScript",
            "/JS",
            "/SubmitForm",
            "/ImportData",
            "/GoToR",
            "/URI",  # URI actions can invoke shell handlers on some viewers
        ]
    )

    def supports(self, *, content_type: str, filename: str | None = None) -> bool:
        if not _pikepdf_available():
            return False
        if "pdf" in (content_type or "").lower():
            return True
        if filename and filename.lower().endswith(".pdf"):
            return True
        return False

    def scan(self, payload: bytes, *, filename: str | None = None) -> ScanResult:
        if not _pikepdf_available():
            return ScanResult(
                self.name,
                "clean",
                "pikepdf not installed; install sandbox-hardening extra to enable",
            )

        import io as _io

        import pikepdf

        try:
            pdf = pikepdf.open(_io.BytesIO(payload))
        except pikepdf.PasswordError:
            return ScanResult(self.name, "quarantine", "PDF is password-protected — cannot inspect")
        except pikepdf.PdfError as exc:
            return ScanResult(self.name, "quarantine", f"malformed PDF (pikepdf): {exc}")
        except Exception as exc:
            return ScanResult(self.name, "quarantine", f"unexpected PDF parse error: {exc!r}")

        findings: list[str] = []

        try:
            catalog = pdf.Root

            # /OpenAction — executes when the document is opened
            if "/OpenAction" in catalog:
                findings.append("/OpenAction in document catalog")

            # /AA (additional actions) on the catalog
            if "/AA" in catalog:
                findings.append("/AA (additional-actions) in document catalog")

            # Walk action dictionaries for dangerous sub-types
            for key in ("/OpenAction", "/AA"):
                if key not in catalog:
                    continue
                action = catalog[key]
                self._check_action(action, findings)

            # Embedded files: /EmbeddedFile streams anywhere
            for obj in pdf.objects:
                try:
                    if isinstance(obj, pikepdf.Stream):
                        st = obj.stream_dict
                        if "/Type" in st and str(st["/Type"]) == "/EmbeddedFile":
                            findings.append("embedded file stream detected")
                            break
                        subtype = st.get("/Subtype", "")
                        if str(subtype) == "/EmbeddedFile":
                            findings.append("embedded file stream detected")
                            break
                except Exception:
                    pass

            # Page-level /AA and /Actions
            for page in pdf.pages:
                if "/AA" in page:
                    findings.append("/AA (additional-actions) on a page")
                    break
                if "/Annots" in page:
                    for annot in page["/Annots"]:
                        try:
                            # pikepdf objects are dynamic (Object.__getattr__);
                            # treat as Any so the guarded get_object() call type-
                            # checks (mypy otherwise sees Object as non-callable).
                            _annot: Any = annot
                            annot_obj = _annot
                            if hasattr(_annot, "get_object"):
                                annot_obj = _annot.get_object()
                            if "/A" in annot_obj:
                                self._check_action(annot_obj["/A"], findings)
                        except Exception:
                            pass

        finally:
            pdf.close()

        if not findings:
            return ScanResult(self.name, "clean")

        return ScanResult(
            self.name,
            "quarantine",
            f"suspicious PDF structure: {'; '.join(findings)}",
            {"findings": findings},
        )

    def _check_action(self, action: Any, findings: list[str]) -> None:
        """Recursively inspect an action dictionary for dangerous /S sub-types."""
        try:
            if hasattr(action, "keys"):
                s_val = action.get("/S", "")
                if str(s_val) in self._DANGEROUS_ACTION_S:
                    findings.append(f"dangerous action /S={s_val}")
                # /Next chain
                if "/Next" in action:
                    self._check_action(action["/Next"], findings)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# hardened_scanners() factory
# ---------------------------------------------------------------------------


def hardened_scanners() -> list[Scanner]:
    """Return the Zone H hardened scanner instances.

    Both scanners degrade gracefully when their optional dependency
    (``yara-python`` or ``pikepdf``) is absent, so this list is always safe
    to include in a broker even without the ``sandbox-hardening`` extra.

    Typical usage::

        from lighthouse_ai.sandbox.broker import build_default_broker
        from lighthouse_ai.sandbox.scanners import hardened_scanners
        from lighthouse_ai.sandbox import SandboxBroker
        from lighthouse_ai.sandbox.quarantine import Quarantine

        quarantine = Quarantine(...)
        broker = build_default_broker(data_dir)
        # -- OR --
        broker = SandboxBroker(quarantine,
                               [EICARScanner(), PDFJavaScriptScanner(),
                                HTMLScriptScanner(), ArchiveBombScanner()]
                               + hardened_scanners())

    The function always returns a fresh list of new instances, so it is safe
    to call multiple times.
    """
    return [YaraScanner(), PikePdfScanner()]
