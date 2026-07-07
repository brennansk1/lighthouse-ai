"""SandboxBroker — the single chokepoint for ingested content (§15.4).

Pipeline:
    1. Hash the payload.
    2. Run every applicable scanner.
    3. Aggregate verdicts: any "reject" wins; else any "quarantine" wins; else admit.
    4. Record in quarantine.db.

Future sprints add: download via bubblewrap/sandbox-exec subprocess, YARA
ruleset, ClamAV daemon socket, WORM mirror with chflags uchg.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .quarantine import Quarantine, QuarantineRecord
from .scanners import EICARScanner, Scanner, ScanResult


class Verdict(str, Enum):
    ADMIT = "admit"
    QUARANTINE = "quarantine"
    REJECT = "reject"


@dataclass(frozen=True)
class BrokerOutcome:
    verdict: Verdict
    sha256: str
    record: QuarantineRecord
    scan_results: list[ScanResult] = field(default_factory=list)


class SandboxBroker:
    def __init__(self, quarantine: Quarantine, scanners: list[Scanner] | None = None):
        # EICAR is always installed; it's the canonical redteam check.
        self.scanners: list[Scanner] = list(scanners or [])
        if not any(s.name == "eicar" for s in self.scanners):
            self.scanners.insert(0, EICARScanner())
        self.quarantine = quarantine

    def admit(
        self,
        payload: bytes,
        *,
        url: str | None = None,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> BrokerOutcome:
        sha = Quarantine.hash_bytes(payload)
        results: list[ScanResult] = []
        for scanner in self.scanners:
            if not scanner.supports(content_type=content_type or "", filename=filename):
                continue
            try:
                results.append(scanner.scan(payload, filename=filename))
            except Exception as exc:
                results.append(ScanResult(scanner.name, "quarantine", f"scanner error: {exc!r}"))

        verdict = self._aggregate(results)
        reasons = [
            {
                "scanner": r.scanner,
                "verdict": r.verdict,
                "reason": r.reason,
                "details": r.details or {},
            }
            for r in results
        ]
        rec = self.quarantine.record(
            sha256=sha,
            url=url,
            filename=filename,
            content_type=content_type,
            verdict=verdict.value,
            reasons=reasons,
            payload=payload,
        )
        return BrokerOutcome(verdict=verdict, sha256=sha, record=rec, scan_results=results)

    @staticmethod
    def _aggregate(results: list[ScanResult]) -> Verdict:
        verdicts = {r.verdict for r in results}
        if "reject" in verdicts:
            return Verdict.REJECT
        if "quarantine" in verdicts:
            return Verdict.QUARANTINE
        return Verdict.ADMIT


def build_default_broker(data_dir: Path) -> SandboxBroker:
    """Convenience: assemble a broker with bundled scanners + quarantine."""
    from .scanners import (
        ArchiveBombScanner,
        HTMLScriptScanner,
        PDFJavaScriptScanner,
    )

    q = Quarantine(data_dir / "quarantine.db", data_dir / "quarantine")
    scanners: list[Scanner] = [
        EICARScanner(),
        PDFJavaScriptScanner(),
        HTMLScriptScanner(),
        ArchiveBombScanner(),
    ]
    return SandboxBroker(q, scanners)
