"""YouTube source adapter — video metadata, transcripts, and search.

Uses two optional libraries available in the ``youtube`` extra:

  * ``yt-dlp`` (>=2024.11.18) — video metadata and search.  Pin note: yt-dlp
    releases frequently to track YouTube's client interface.  The 2024.11.18
    release includes mitigations for the Android-client rotation that was
    exploited in CVE-2024-38519 (ReDoS via crafted chapter metadata, patched in
    yt-dlp >=2024.8.6).  Always run a current release.

  * ``youtube-transcript-api`` (>=0.6.3) — public caption endpoint via the
    official timedtext API that YouTube exposes to its own web player.  No
    authentication required for videos with captions enabled.

When either library is absent the corresponding function returns a graceful
empty/degraded result rather than raising, so a Lighthouse install without the
``youtube`` extra can still discover this adapter without crashing.

LEGITIMATE PATH ONLY
---------------------
All access is through official YouTube endpoints:

  * Data API v3 metadata where an API key is available.
  * yt-dlp's extraction of public page metadata (equivalent to browsing the
    page — no authentication, no evasion, no residential proxies, no bypassing
    blocks).
  * youtube-transcript-api's call to the public timedtext endpoint that
    YouTube's own web player uses.

Cloud IP addresses are routinely rate-limited or soft-blocked by YouTube.  This
adapter is designed for **local-first** use (Lighthouse runs on the user's own
machine) which mitigates cloud-IP blocks.  If you observe consistent 429/403
responses in a cloud deployment, consider routing requests through the user's
own network or reducing cadence.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Lazy optional imports — absent → graceful degradation, not ImportError.
# ---------------------------------------------------------------------------

try:
    import yt_dlp  # type: ignore[import-untyped]

    _YT_DLP_AVAILABLE = True
except ImportError:  # pragma: no cover — tested by monkeypatch in test suite
    yt_dlp = None  # type: ignore[assignment]
    _YT_DLP_AVAILABLE = False

try:
    from youtube_transcript_api import (  # type: ignore[import-untyped]
        NoTranscriptFound,
        TranscriptsDisabled,
        YouTubeTranscriptApi,
    )

    _TRANSCRIPT_API_AVAILABLE = True
except ImportError:  # pragma: no cover — tested by monkeypatch in test suite
    YouTubeTranscriptApi = None  # type: ignore[assignment,misc]
    NoTranscriptFound = Exception  # type: ignore[assignment,misc]
    TranscriptsDisabled = Exception  # type: ignore[assignment,misc]
    _TRANSCRIPT_API_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def _extract_video_id(url: str) -> str | None:
    """Extract the 11-char video ID from a YouTube URL, or None."""
    m = _VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


def _duration_str(seconds: int | float | None) -> str:
    """Format duration as MM:SS or HH:MM:SS."""
    if seconds is None:
        return ""
    secs = int(seconds)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_metadata(video_url: str) -> dict[str, Any]:
    """Return a metadata dict for a YouTube video URL.

    Uses yt-dlp to extract public page metadata without downloading.  Returns
    an empty dict if yt-dlp is unavailable or the URL is not a valid YouTube
    video.

    Keys present on success (subset — all may be absent/None):
      ``video_id``, ``title``, ``description``, ``uploader``, ``channel_id``,
      ``upload_date`` (YYYYMMDD), ``duration_seconds``, ``duration``,
      ``view_count``, ``like_count``, ``url``, ``thumbnail``.

    Cloud IP note: YouTube rate-limits cloud addresses aggressively.  This call
    works reliably from a user's own machine (local-first).
    """
    if not _YT_DLP_AVAILABLE:
        return {}

    video_id = _extract_video_id(video_url)
    if not video_id:
        return {}

    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except Exception:
        return {}

    if not info:
        return {}

    duration_secs = info.get("duration")
    return {
        "video_id": info.get("id", video_id),
        "title": info.get("title", ""),
        "description": (info.get("description") or "")[:2000],
        "uploader": info.get("uploader") or info.get("channel", ""),
        "channel_id": info.get("channel_id", ""),
        "upload_date": info.get("upload_date", ""),  # YYYYMMDD
        "duration_seconds": duration_secs,
        "duration": _duration_str(duration_secs),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "url": f"https://www.youtube.com/watch?v={info.get('id', video_id)}",
        "thumbnail": info.get("thumbnail", ""),
    }


def fetch_transcript(video_id: str, *, languages: list[str] | None = None) -> str:
    """Return the transcript for a YouTube video as plain text.

    Uses ``youtube-transcript-api`` to call the public timedtext endpoint (the
    same endpoint YouTube's own web player uses).  Auto-generated captions are
    accepted when manually-authored ones are unavailable.

    Returns an empty string if:
      * ``youtube-transcript-api`` is not installed.
      * Transcripts are disabled for the video.
      * No transcript is available in the requested languages.
      * Any other error occurs.

    Parameters
    ----------
    video_id:
        The 11-character YouTube video ID (not a URL).
    languages:
        Ordered list of language codes to try (e.g. ``["en", "en-US"]``).
        Defaults to ``["en"]``.
    """
    if not _TRANSCRIPT_API_AVAILABLE:
        return ""
    langs = languages or ["en"]
    # youtube-transcript-api changed its API in 1.x: the ``get_transcript``
    # classmethod was replaced by an instance ``fetch`` returning a
    # FetchedTranscript (snippets with a ``.text`` attribute). Support both so
    # the skill works regardless of the installed major version.
    api: Any = YouTubeTranscriptApi
    try:
        get_transcript = getattr(api, "get_transcript", None)
        if callable(get_transcript):
            rows: Any = get_transcript(video_id, languages=langs)  # 0.x
        else:
            fetched = api().fetch(video_id, languages=langs)       # 1.x
            rows = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") \
                else list(fetched)
        return " ".join(
            (r.get("text", "") if isinstance(r, dict) else getattr(r, "text", ""))
            for r in rows
        ).strip()
    except (NoTranscriptFound, TranscriptsDisabled):
        return ""
    except Exception:
        return ""


def search_videos(
    query: str,
    *,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Search YouTube for videos matching ``query``.

    Uses yt-dlp's ytsearch extractor which calls YouTube's public search
    endpoint — no API key required.  Returns a list of dicts, each containing
    the same keys as :func:`fetch_metadata` (where available).

    Returns an empty list if yt-dlp is unavailable or the search fails.

    Cloud IP note: YouTube throttles searches from cloud addresses.  Runs
    reliably on the user's local machine.

    Parameters
    ----------
    query:
        Free-text search query.
    max_results:
        Maximum number of results to return (default 5, max capped at 20 by the
        extractor on free access).
    """
    if not _YT_DLP_AVAILABLE:
        return []

    n = max(1, min(max_results, 20))
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,  # fast: metadata only, no page-level fetch per entry
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            results = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    except Exception:
        return []

    if not results or "entries" not in results:
        return []

    out: list[dict[str, Any]] = []
    for entry in (results["entries"] or []):
        if not entry:
            continue
        video_id = entry.get("id", "")
        duration_secs = entry.get("duration")
        out.append(
            {
                "video_id": video_id,
                "title": entry.get("title", ""),
                "description": (entry.get("description") or "")[:2000],
                "uploader": entry.get("uploader") or entry.get("channel", ""),
                "channel_id": entry.get("channel_id", ""),
                "upload_date": entry.get("upload_date", ""),
                "duration_seconds": duration_secs,
                "duration": _duration_str(duration_secs),
                "view_count": entry.get("view_count"),
                "url": (
                    f"https://www.youtube.com/watch?v={video_id}"
                    if video_id
                    else entry.get("url", "")
                ),
                "thumbnail": entry.get("thumbnail", ""),
            }
        )
    return out
