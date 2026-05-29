"""Zone H sandbox-hardening scanner tests.

Tests are written so the suite passes whether or not yara-python / pikepdf are
installed.  Where a test requires a library it uses ``pytest.importorskip`` to
skip rather than fail.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest

from lighthouse_ai.sandbox.scanners import (
    PikePdfScanner,
    ScanResult,
    YaraScanner,
    hardened_scanners,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_yara_available() -> bool:
    try:
        import yara  # noqa: F401

        return True
    except ImportError:
        return False


def _is_pikepdf_available() -> bool:
    try:
        import pikepdf  # noqa: F401

        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# 1. Graceful degradation when libraries are absent
# ---------------------------------------------------------------------------


class TestYaraScannerDegradation:
    """YaraScanner degrades cleanly when yara-python is not installed."""

    def test_supports_returns_false_without_yara_and_no_injected_rules(
        self, monkeypatch
    ):
        """When yara cannot be imported, supports() should return False."""
        # Patch _yara_available to simulate absent library
        import lighthouse_ai.sandbox.scanners as scanners_mod

        monkeypatch.setattr(scanners_mod, "_yara_available", lambda: False)
        scanner = YaraScanner()
        assert scanner.supports(content_type="application/pdf") is False

    def test_scan_returns_clean_without_yara(self, monkeypatch):
        import lighthouse_ai.sandbox.scanners as scanners_mod

        monkeypatch.setattr(scanners_mod, "_yara_available", lambda: False)
        scanner = YaraScanner()
        result = scanner.scan(b"some payload", filename="file.bin")
        assert isinstance(result, ScanResult)
        assert result.verdict == "clean"
        assert "yara-python not installed" in result.reason

    def test_scan_never_raises_without_yara(self, monkeypatch):
        import lighthouse_ai.sandbox.scanners as scanners_mod

        monkeypatch.setattr(scanners_mod, "_yara_available", lambda: False)
        scanner = YaraScanner()
        # Should not raise for any input
        for payload in [b"", b"\x00" * 1024, b"%PDF-1.4\n"]:
            result = scanner.scan(payload)
            assert result.verdict in ("clean", "quarantine", "reject")


class TestPikePdfScannerDegradation:
    """PikePdfScanner degrades cleanly when pikepdf is not installed."""

    def test_supports_returns_false_without_pikepdf(self, monkeypatch):
        import lighthouse_ai.sandbox.scanners as scanners_mod

        monkeypatch.setattr(scanners_mod, "_pikepdf_available", lambda: False)
        scanner = PikePdfScanner()
        assert scanner.supports(content_type="application/pdf") is False
        assert (
            scanner.supports(content_type="application/pdf", filename="doc.pdf")
            is False
        )

    def test_scan_returns_clean_without_pikepdf(self, monkeypatch):
        import lighthouse_ai.sandbox.scanners as scanners_mod

        monkeypatch.setattr(scanners_mod, "_pikepdf_available", lambda: False)
        scanner = PikePdfScanner()
        result = scanner.scan(b"%PDF-1.4\nhello", filename="doc.pdf")
        assert isinstance(result, ScanResult)
        assert result.verdict == "clean"
        assert "pikepdf not installed" in result.reason

    def test_scan_never_raises_without_pikepdf(self, monkeypatch):
        import lighthouse_ai.sandbox.scanners as scanners_mod

        monkeypatch.setattr(scanners_mod, "_pikepdf_available", lambda: False)
        scanner = PikePdfScanner()
        for payload in [b"", b"\x00\xff" * 500, b"%PDF-1.4\n"]:
            result = scanner.scan(payload)
            assert result.verdict in ("clean", "quarantine", "reject")


# ---------------------------------------------------------------------------
# 2. YaraScanner with injected fake rules object flags matching payload
# ---------------------------------------------------------------------------


class _FakeMatch:
    """Minimal stand-in for a yara.Match object."""

    def __init__(self, rule: str, severity: str = "quarantine"):
        self.rule = rule
        self.meta = {"severity": severity}


class _FakeRules:
    """Duck-type yara.Rules that matches a specific byte pattern."""

    def __init__(self, trigger: bytes, matches: list[_FakeMatch]):
        self._trigger = trigger
        self._matches = matches

    def match(self, data: bytes) -> list[_FakeMatch]:
        return self._matches if self._trigger in data else []


class TestYaraScannerInjectedRules:
    def test_matching_payload_is_quarantined(self):
        fake_rules = _FakeRules(
            trigger=b"EVIL_PAYLOAD",
            matches=[_FakeMatch("EvilRule", "quarantine")],
        )
        scanner = YaraScanner(rules_object=fake_rules)
        result = scanner.scan(b"prefix EVIL_PAYLOAD suffix", filename="bad.bin")
        assert result.verdict == "quarantine"
        assert "EvilRule" in result.reason
        assert result.details is not None
        assert "EvilRule" in result.details["matched_rules"]

    def test_matching_payload_reject_severity(self):
        fake_rules = _FakeRules(
            trigger=b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE",
            matches=[_FakeMatch("EICAR_Test_File", "reject")],
        )
        scanner = YaraScanner(rules_object=fake_rules)
        result = scanner.scan(
            b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        )
        assert result.verdict == "reject"

    def test_non_matching_payload_is_clean(self):
        fake_rules = _FakeRules(
            trigger=b"EVIL_PAYLOAD",
            matches=[_FakeMatch("EvilRule", "quarantine")],
        )
        scanner = YaraScanner(rules_object=fake_rules)
        result = scanner.scan(b"totally benign bytes", filename="ok.bin")
        assert result.verdict == "clean"

    def test_supports_returns_true_with_injected_rules(self):
        fake_rules = _FakeRules(b"x", [])
        scanner = YaraScanner(rules_object=fake_rules)
        # supports() should be True because rules_object is provided regardless of yara
        assert scanner.supports(content_type="text/plain") is True

    def test_match_error_returns_quarantine_not_crash(self):
        broken_rules = MagicMock()
        broken_rules.match.side_effect = RuntimeError("YARA internal error")
        scanner = YaraScanner(rules_object=broken_rules)
        result = scanner.scan(b"anything")
        assert result.verdict == "quarantine"
        assert "YARA match error" in result.reason


# ---------------------------------------------------------------------------
# 3. PikePdfScanner with pikepdf available (skipped when absent)
# ---------------------------------------------------------------------------


class TestPikePdfScannerWithLibrary:
    @staticmethod
    def _make_benign_pdf() -> bytes:
        """Build a minimal valid PDF with no active content."""
        pikepdf = pytest.importorskip("pikepdf")
        buf = io.BytesIO()
        with pikepdf.Pdf.new() as pdf:
            page = pikepdf.Dictionary(
                Type=pikepdf.Name("/Page"),
                MediaBox=pikepdf.Array([0, 0, 612, 792]),
            )
            pdf.make_indirect(page)
            pdf.pages.append(page)
            pdf.save(buf)
        return buf.getvalue()

    @staticmethod
    def _make_openaction_pdf() -> bytes:
        """Build a PDF whose catalog contains /OpenAction."""
        pikepdf = pytest.importorskip("pikepdf")
        buf = io.BytesIO()
        with pikepdf.Pdf.new() as pdf:
            page = pikepdf.Dictionary(
                Type=pikepdf.Name("/Page"),
                MediaBox=pikepdf.Array([0, 0, 612, 792]),
            )
            pdf.make_indirect(page)
            pdf.pages.append(page)
            # Inject a /OpenAction that launches a JavaScript alert
            pdf.Root["/OpenAction"] = pikepdf.Dictionary(
                S=pikepdf.Name("/JavaScript"),
                JS=pikepdf.String("app.alert('xss')"),
            )
            pdf.save(buf)
        return buf.getvalue()

    def test_benign_pdf_is_clean(self):
        pytest.importorskip("pikepdf")
        scanner = PikePdfScanner()
        payload = self._make_benign_pdf()
        result = scanner.scan(payload, filename="benign.pdf")
        assert result.verdict == "clean", result.reason

    def test_openaction_pdf_is_quarantined(self):
        pytest.importorskip("pikepdf")
        scanner = PikePdfScanner()
        payload = self._make_openaction_pdf()
        result = scanner.scan(payload, filename="active.pdf")
        assert result.verdict == "quarantine", result.reason
        assert result.details is not None
        findings = result.details["findings"]
        assert any(
            "/OpenAction" in f or "dangerous action" in f for f in findings
        ), findings

    def test_malformed_pdf_is_quarantined(self):
        pytest.importorskip("pikepdf")
        scanner = PikePdfScanner()
        result = scanner.scan(b"%PDF-1.4\ngarbage\xfe\xff\x00", filename="bad.pdf")
        assert result.verdict == "quarantine"

    def test_supports_pdf_content_type(self):
        pytest.importorskip("pikepdf")
        scanner = PikePdfScanner()
        assert scanner.supports(content_type="application/pdf") is True
        assert scanner.supports(content_type="application/pdf", filename="f.pdf") is True

    def test_supports_pdf_filename_extension(self):
        pytest.importorskip("pikepdf")
        scanner = PikePdfScanner()
        assert scanner.supports(content_type="", filename="report.pdf") is True

    def test_supports_non_pdf_returns_false(self):
        pytest.importorskip("pikepdf")
        scanner = PikePdfScanner()
        assert scanner.supports(content_type="text/html", filename="page.html") is False


# ---------------------------------------------------------------------------
# 4. No false positives on benign content
# ---------------------------------------------------------------------------


class TestNoFalsePositives:
    """Benign content should never be flagged (regression guard)."""

    def test_yara_injected_rules_benign_html_clean(self):
        fake_rules = _FakeRules(b"EVIL_PAYLOAD", [_FakeMatch("EvilRule")])
        scanner = YaraScanner(rules_object=fake_rules)
        payload = b"<html><body><p>Hello world!</p></body></html>"
        result = scanner.scan(payload, filename="page.html")
        assert result.verdict == "clean"

    def test_yara_injected_rules_benign_pdf_clean(self):
        """A plain PDF without any dangerous keyword should not match EvilRule."""
        fake_rules = _FakeRules(b"EVIL_PAYLOAD", [_FakeMatch("EvilRule")])
        scanner = YaraScanner(rules_object=fake_rules)
        payload = b"%PDF-1.4\nstream\nendstream\n%%EOF"
        result = scanner.scan(payload, filename="clean.pdf")
        assert result.verdict == "clean"

    def test_pikepdf_benign_pdf_clean_when_lib_absent(self, monkeypatch):
        import lighthouse_ai.sandbox.scanners as scanners_mod

        monkeypatch.setattr(scanners_mod, "_pikepdf_available", lambda: False)
        scanner = PikePdfScanner()
        result = scanner.scan(b"%PDF-1.4\n", filename="doc.pdf")
        assert result.verdict == "clean"

    def test_yara_degraded_benign_pdf_clean(self, monkeypatch):
        import lighthouse_ai.sandbox.scanners as scanners_mod

        monkeypatch.setattr(scanners_mod, "_yara_available", lambda: False)
        scanner = YaraScanner()
        result = scanner.scan(b"%PDF-1.4\nhello", filename="clean.pdf")
        assert result.verdict == "clean"


# ---------------------------------------------------------------------------
# 5. hardened_scanners() factory
# ---------------------------------------------------------------------------


class TestHardenedScannersFactory:
    def test_returns_list_of_two_scanners(self):
        result = hardened_scanners()
        assert isinstance(result, list)
        assert len(result) == 2

    def test_contains_yara_scanner(self):
        scanners = hardened_scanners()
        names = [s.name for s in scanners]
        assert "yara" in names

    def test_contains_pikepdf_scanner(self):
        scanners = hardened_scanners()
        names = [s.name for s in scanners]
        assert "pikepdf" in names

    def test_returns_fresh_instances_each_call(self):
        s1 = hardened_scanners()
        s2 = hardened_scanners()
        assert s1[0] is not s2[0]

    def test_all_scanners_have_required_protocol_attributes(self):
        """Each scanner must satisfy the Scanner protocol (name, supports, scan)."""
        for scanner in hardened_scanners():
            assert hasattr(scanner, "name")
            assert callable(getattr(scanner, "supports", None))
            assert callable(getattr(scanner, "scan", None))

    def test_scan_never_raises_on_arbitrary_input(self):
        """Regardless of library availability, scan() must not raise."""
        for scanner in hardened_scanners():
            for payload in [b"", b"\x00" * 100, b"%PDF-1.4\n"]:
                # scan() is called directly — it should return a ScanResult or
                # degrade cleanly, never raise
                result = scanner.scan(payload, filename="fuzz.bin")
                assert isinstance(result, ScanResult)
                assert result.verdict in ("clean", "quarantine", "reject")


# ---------------------------------------------------------------------------
# 6. EICAR regression — existing scanner still works alongside hardened ones
# ---------------------------------------------------------------------------


class TestEICARRegressionWithHardenedScanners:
    def test_eicar_still_detected_by_existing_scanner(self):
        from lighthouse_ai.sandbox.scanners import EICAR_SIGNATURE, EICARScanner

        scanner = EICARScanner()
        result = scanner.scan(b"prefix " + EICAR_SIGNATURE + b" suffix")
        assert result.verdict == "reject"

    def test_yara_injected_eicar_rule_flags_signature(self):
        fake_rules = _FakeRules(
            trigger=b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE",
            matches=[_FakeMatch("EICAR_Test_File", "reject")],
        )
        scanner = YaraScanner(rules_object=fake_rules)
        from lighthouse_ai.sandbox.scanners import EICAR_SIGNATURE

        result = scanner.scan(EICAR_SIGNATURE, filename="eicar.txt")
        assert result.verdict == "reject"
