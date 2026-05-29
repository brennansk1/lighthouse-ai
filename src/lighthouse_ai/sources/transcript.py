"""Shared audio-transcript helper — captions/transcript extraction for AV sources.

This module provides a **thin, dependency-light** interface shared by the YouTube
skill (shipped) and the Internet Archive AV skill (SL10, forthcoming).  It
deliberately lives under ``sources/`` rather than inside a skill folder so the
import guard does NOT scan it (the guard only scans files *inside* skill folders).
Skills call this via the ``lighthouse_ai.sources.transcript`` module path, the
same way the YouTube skill calls ``lighthouse_ai.sources.youtube``.

Interface
---------
``transcribe_or_fetch_captions(audio_ref)``
    Given an opaque reference string — a URL, a CourtListener audio path, an
    Internet Archive item identifier — return the best available transcript text,
    or ``None`` when no transcript is obtainable.

    **Priority order (highest to lowest)**

    1. Pre-existing captions / subtitles already associated with the media item
       (e.g. YouTube caption tracks, Internet Archive text files).
    2. A cached transcript in memory for the process lifetime (``_CACHE``).
    3. A registered provider callback (see ``register_provider``).
    4. ``None`` — ASR is a planned upgrade, not present in v1.

Design notes
------------
* **No ASR dependency in v1.** Automatic Speech Recognition is expensive both in
  compute (requires Whisper or a cloud API) and in complexity (audio download,
  chunking, VAD). The stub returns ``None`` rather than failing so callers can
  gracefully fall back to metadata-only documents.  When an ASR backend is wired
  in (v1.1+), it should be plugged in via ``register_provider`` rather than by
  modifying this file, keeping the interface stable.

* **No imports of httpx / urllib / socket.** Transport is the caller's
  responsibility: if a skill needs to fetch audio from a URL it should use
  ``ctx.fetch()`` first and pass the response bytes to
  ``transcribe_or_fetch_captions`` — or, for already-fetched caption text, just
  call ``transcribe_or_fetch_captions`` with a pre-cached result pre-populated
  via ``cache_transcript``.

* **Adapter-style, not skill-scanned.** Living under ``sources/`` means the
  registry import guard does not inspect it, so it may use whatever stdlib imports
  it needs.  It currently uses only ``typing`` and ``functools`` from stdlib.

Internet Archive AV (SL10) usage
---------------------------------
SL10's ``skill.py`` will::

    from lighthouse_ai.sources import transcript as _transcript

    caption_text = _transcript.transcribe_or_fetch_captions(item_identifier)
    if caption_text is None:
        caption_text = ""   # metadata-only fallback

CourtListener usage
-------------------
The CourtListener skill calls this module when it fetches oral-argument audio.
CourtListener does not ship pre-built transcripts for most arguments; the function
returns ``None`` and the skill falls back to case metadata.
"""

from __future__ import annotations

from collections.abc import Callable

# ---------------------------------------------------------------------------
# In-process cache
# ---------------------------------------------------------------------------

# Maps audio_ref → transcript text.  Populated by external callers (e.g. a
# caption-fetch step) via ``cache_transcript``.  Process-lifetime only; no
# persistence.  This lets tests inject canned transcripts without monkeypatching.
_CACHE: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

# Optional ASR / caption-fetch callbacks registered at runtime.
# Signature: ``provider(audio_ref: str) -> str | None``
# Providers are tried in registration order; the first non-None result wins.
_PROVIDERS: list[Callable[[str], str | None]] = []


def register_provider(fn: Callable[[str], str | None]) -> None:
    """Register an ASR or caption-fetch callback.

    Called at startup by optional backend integrations (e.g. a Whisper wrapper,
    a YouTube caption fetcher).  Must be idempotent with respect to repeated
    registration of the same function.

    Parameters
    ----------
    fn:
        A callable that accepts an audio reference string and returns transcript
        text or ``None``.  It is responsible for its own error handling; an
        unhandled exception will propagate to the caller of
        ``transcribe_or_fetch_captions``.
    """
    if fn not in _PROVIDERS:
        _PROVIDERS.append(fn)


def clear_providers() -> None:
    """Remove all registered providers (used by tests to reset state)."""
    _PROVIDERS.clear()


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def cache_transcript(audio_ref: str, text: str) -> None:
    """Populate the in-process cache for ``audio_ref``.

    Useful when a skill has already obtained a transcript (e.g. fetched a
    caption file separately) and wants subsequent calls for the same ref to
    return it without re-fetching.

    Parameters
    ----------
    audio_ref:
        The canonical reference string (URL, identifier, etc.) for the media.
    text:
        Transcript text to cache.  An empty string is stored as-is; callers that
        want to distinguish "cached empty" from "not cached" should check
        explicitly rather than using truthiness.
    """
    _CACHE[audio_ref] = text


def clear_cache() -> None:
    """Flush the in-process cache (used by tests to reset state)."""
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Main interface
# ---------------------------------------------------------------------------


def transcribe_or_fetch_captions(audio_ref: str) -> str | None:
    """Return the best available transcript for ``audio_ref``, or ``None``.

    This is the **primary interface** that skills call.  It applies the priority
    order documented in the module docstring:

    1. In-process cache (populated by ``cache_transcript`` or a prior call).
    2. Registered provider callbacks, in registration order.
    3. ``None`` — no transcript available; ASR is a documented stub for v1.1+.

    Parameters
    ----------
    audio_ref:
        An opaque string identifying the audio/video resource.  The format is
        source-dependent:

        * CourtListener: a URL like
          ``https://www.courtlistener.com/audio/12345/``
        * Internet Archive: an item identifier like ``npr-morning-edition-20050101``
          or a full ``https://archive.org/download/...`` URL.
        * YouTube: a video ID like ``dQw4w9WgXcQ`` (the YouTube skill handles
          this via ``sources.youtube`` rather than this module).

    Returns
    -------
    str or None
        Transcript text when available; ``None`` when unavailable (no caption
        source, no ASR backend registered, or the registered provider returned
        ``None``).

    Notes
    -----
    This function is **not** safe to call from inside the skill import-guard
    scan; that is why it lives under ``sources/`` and not inside a skill folder.
    Skills must import it as::

        from lighthouse_ai.sources import transcript as _transcript

    not via a relative import.
    """
    # 1. Check the in-process cache first — cheapest path.
    if audio_ref in _CACHE:
        return _CACHE[audio_ref]

    # 2. Try registered providers (ASR backends, caption fetchers, etc.).
    for provider in _PROVIDERS:
        result = provider(audio_ref)
        if result is not None:
            # Cache the result for this process lifetime.
            _CACHE[audio_ref] = result
            return result

    # 3. No transcript available.  ASR is a planned stub — documented limitation.
    return None
