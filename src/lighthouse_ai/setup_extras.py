"""On-demand installer for the optional feature bundles.

Lighthouse ships lightweight: the heavy optional stacks (ML reranker, faithfulness
gate, injection classifier, rich extraction, JS rendering, …) are declared as
``[project.optional-dependencies]`` extras and not pulled by the base install.
This module lets a user install them on demand — from the Settings tab or the
``lighthouse install-extras`` CLI — without touching a terminal package manager.

Design:
  * ``extras_status()`` reports each bundle + whether it's importable right now.
  * ``start_install(names)`` resolves the exact packages for the chosen extras
    from the *installed* distribution metadata (so it works identically for an
    editable dev checkout and a pip-installed wheel) and runs ``pip install`` in
    a background thread, tracking progress in a module-global state.
  * ``install_status()`` exposes that progress for polling.

Nothing here imports torch/playwright/etc. at module load — only the probes do,
lazily, so importing this module stays cheap.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import threading
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger(__name__)

#: Distribution name as published (matches pyproject ``[project] name``).
_DIST = "lighthouse-ai"


@dataclass(frozen=True)
class ExtraInfo:
    name: str  # the pyproject extra key
    label: str  # user-facing name
    description: str  # plain-language "what this unlocks"
    probe_module: str  # an import that proves the bundle is installed
    needs_browser: bool = False  # js-render also needs `playwright install chromium`


#: User-facing catalog of the optional bundles. ``probe_module`` is the import
#: used to detect "already installed"; the actual packages come from metadata.
EXTRAS: tuple[ExtraInfo, ...] = (
    ExtraInfo(
        "faithfulness",
        "Faithfulness gate",
        "Score how well each claim is entailed by its sources "
        "(MiniCheck/HHEM). Pulls sentence-transformers.",
        "sentence_transformers",
    ),
    ExtraInfo(
        "reranker",
        "Neural reranker",
        "Higher retrieval precision with a cross-encoder "
        "(bge-reranker-v2-m3). Pulls FlagEmbedding/torch.",
        "FlagEmbedding",
    ),
    ExtraInfo(
        "injection-ml",
        "ML prompt-injection screen",
        "A deBERTa classifier behind the regex injection gate. Pulls transformers + optimum.",
        "transformers",
    ),
    ExtraInfo(
        "extraction",
        "Rich document extraction",
        "Better HTML/PDF/office extraction (trafilatura, pdfplumber, docling).",
        "trafilatura",
    ),
    ExtraInfo(
        "pdf-fast",
        "Fast PDF parsing",
        "PyMuPDF for faster, higher-fidelity PDF text (AGPL, opt-in).",
        "fitz",
    ),
    ExtraInfo(
        "politeness",
        "Web politeness layer",
        "robots.txt, crawl-delay and per-domain rate budgets for the web fetcher.",
        "protego",
    ),
    ExtraInfo(
        "sandbox-hardening",
        "Hardened file scanners",
        "YARA signatures + deep PDF inspection (pikepdf) on every upload.",
        "yara",
    ),
    ExtraInfo(
        "youtube",
        "YouTube + transcripts",
        "Fetch video metadata and captions for the YouTube skill.",
        "yt_dlp",
    ),
    ExtraInfo(
        "js-render",
        "JavaScript page rendering",
        "Render JS-heavy pages with a headless browser (Playwright + Chromium).",
        "playwright",
        needs_browser=True,
    ),
)

_BY_NAME = {e.name: e for e in EXTRAS}


def _is_installed(probe_module: str) -> bool:
    try:
        return importlib.util.find_spec(probe_module) is not None
    except Exception:
        return False


def extras_status() -> list[dict]:
    """Each optional bundle + whether it's currently importable."""
    st = install_status()
    busy = st["state"] == "running"
    target = set(st.get("extras") or [])
    out = []
    for e in EXTRAS:
        installed = _is_installed(e.probe_module)
        out.append(
            {
                "name": e.name,
                "label": e.label,
                "description": e.description,
                "installed": installed,
                "installing": busy and (not target or e.name in target) and not installed,
                "needs_browser": e.needs_browser,
            }
        )
    return out


def _extra_packages(extra: str) -> list[str]:
    """Resolve the exact pip requirements for ``extra`` from installed metadata.

    Reads the distribution's ``Requires-Dist`` markers (``…; extra == "name"``)
    so dev checkouts and wheels agree. Falls back to ``lighthouse-ai[extra]`` if
    metadata can't be read."""
    try:
        import importlib.metadata as md

        reqs = md.requires(_DIST) or []
    except Exception:
        return [f"{_DIST}[{extra}]"]
    pkgs: list[str] = []
    needle = f'extra == "{extra}"'
    alt = f"extra == '{extra}'"
    for r in reqs:
        if needle in r or alt in r:
            pkgs.append(r.split(";", 1)[0].strip())
    return pkgs or [f"{_DIST}[{extra}]"]


# --------------------------------------------------------------------------- #
# Background install state
# --------------------------------------------------------------------------- #
@dataclass
class _InstallState:
    state: str = "idle"  # idle | running | done | error
    extras: list[str] = field(default_factory=list)
    log_tail: list[str] = field(default_factory=list)
    error: str | None = None


_state = _InstallState()
_lock = threading.Lock()


def install_status() -> dict:
    with _lock:
        return {
            "state": _state.state,
            "extras": list(_state.extras),
            "log_tail": list(_state.log_tail[-20:]),
            "error": _state.error,
        }


def resolve_extras(names: list[str] | None) -> list[str]:
    """Normalize a request to a list of known extra names. ``None``/``["all"]``
    → every bundle that isn't already installed."""
    if not names or names == ["all"]:
        return [e.name for e in EXTRAS if not _is_installed(e.probe_module)]
    return [n for n in names if n in _BY_NAME]


def install_extras_blocking(names: list[str] | None) -> _InstallState:
    """Synchronous install (used by the CLI). Returns the final state."""
    extras = resolve_extras(names)
    with _lock:
        _state.state = "running"
        _state.extras = extras
        _state.log_tail = []
        _state.error = None
    if not extras:
        with _lock:
            _state.state = "done"
            _state.log_tail.append("All selected features already installed.")
        return _state

    pkgs: list[str] = []
    for ex in extras:
        pkgs.extend(_extra_packages(ex))
    cmd = [sys.executable, "-m", "pip", "install", *dict.fromkeys(pkgs)]
    log.info("setup_extras.install", extras=extras, packages=pkgs)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        tail = (proc.stdout or "").splitlines()[-10:] + (proc.stderr or "").splitlines()[-5:]
        with _lock:
            _state.log_tail.extend(tail)
        if proc.returncode != 0:
            raise RuntimeError(f"pip exited {proc.returncode}")
        # js-render also needs the browser binary.
        if any(_BY_NAME[e].needs_browser for e in extras):
            with _lock:
                _state.log_tail.append("Installing Chromium for Playwright…")
            br = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True,
                check=False,
            )
            with _lock:
                _state.log_tail.extend((br.stdout or "").splitlines()[-3:])
        with _lock:
            _state.state = "done"
    except Exception as exc:  # pragma: no cover - exercised via the CLI/UI
        log.warning("setup_extras.install_failed", error=str(exc))
        with _lock:
            _state.state = "error"
            _state.error = str(exc)
    return _state


def start_install(names: list[str] | None) -> dict:
    """Kick off a background install; returns the immediate status. A second
    call while one is running is a no-op that reports the in-flight install."""
    with _lock:
        if _state.state == "running":
            return {"state": "running", "extras": list(_state.extras), "already_running": True}
    extras = resolve_extras(names)
    if not extras:
        return {"state": "done", "extras": [], "note": "nothing to install"}
    t = threading.Thread(
        target=install_extras_blocking, args=(names,), name="extras-install", daemon=True
    )
    t.start()
    return {"state": "running", "extras": extras}
