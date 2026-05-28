"""Sandbox subsystem (design §15) — Sprint 6 scope.

Public surface:
  * :class:`Verdict` — admit | quarantine | reject.
  * :class:`Scanner` Protocol; bundled scanners for PDF, HTML, archives.
  * :class:`SandboxBroker` — orchestrates download→scan→admit/quarantine.
  * :class:`Quarantine` — per-file manifest in ``quarantine.db``.

Real sandbox-exec / bubblewrap wrappers spawn subprocesses; the framework
here treats them as opaque "isolated downloader" functions you plug in.
"""

from __future__ import annotations

from .broker import SandboxBroker, Verdict
from .quarantine import Quarantine
from .scanners import (
    ArchiveBombScanner,
    HTMLScriptScanner,
    PDFJavaScriptScanner,
    Scanner,
    ScanResult,
)

__all__ = [
    "ArchiveBombScanner",
    "HTMLScriptScanner",
    "PDFJavaScriptScanner",
    "Quarantine",
    "SandboxBroker",
    "ScanResult",
    "Scanner",
    "Verdict",
]
