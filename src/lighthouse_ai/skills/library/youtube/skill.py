"""YouTube skill entrypoints — ``run`` and ``run_watchable``.

All network access is performed through the vetted ``sources/youtube.py``
adapter (which is NOT inside the skill folder and is therefore not scanned
by the import guard).  This file itself imports only the adapter and the
skill context — no raw httpx/urllib/socket/subprocess.

The skill fetches video metadata + transcripts for the top search hits and
wraps each result in a ``Document`` via ``ctx.make_document`` (transcripts
are first-party API text, not fetched as raw web pages).

Grade
-----
``default_grade = "C"`` reflects that YouTube hosts user-generated content.
The planner should note channel authority for individual results; official
publisher or academic institution channels may warrant a higher grade
assessment in a downstream discipline step.

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("youtube")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "neural network explained", broker=broker)
    for doc in result.documents:
        print(doc.metadata["title"], doc.text[:120])
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from lighthouse_ai.sources import youtube as _yt

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


# ---------------------------------------------------------------------------
# Pattern-1 / 3 — multi-source synthesis & conversational on-demand
# ---------------------------------------------------------------------------


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using YouTube video search and transcripts.

    Strategy
    --------
    1. Search YouTube for videos matching ``question`` (via yt-dlp).
    2. For each hit attempt to fetch the public transcript (via
       youtube-transcript-api).  Videos without transcripts are still returned
       using their title + description as the document text.
    3. Wrap each result in a ``Document`` tagged ``source="youtube"`` with
       the video URL, title, channel, and upload date.

    When yt-dlp is not installed the search returns no results and the
    function returns an empty list gracefully.

    Parameters
    ----------
    ctx:
        Capability-restricted context; ``make_document`` is the only
        primitive called here (transcript text is API-sourced, not a web
        page fetch).
    question:
        The user's research question or search query.
    max_results:
        Maximum number of Documents to return (default 5).
    """
    hits = _yt.search_videos(question, max_results=max_results)
    if not hits:
        return []

    docs: list[Document] = []
    for hit in hits:
        video_id = hit.get("video_id", "")
        title = hit.get("title", "")
        if not title and not video_id:
            continue

        # Prefer transcript; fall back to description.
        transcript = _yt.fetch_transcript(video_id) if video_id else ""
        if transcript:
            body = transcript
            text_type = "transcript"
        else:
            description = hit.get("description", "").strip()
            body = description if description else title
            text_type = "description"

        doc_text = f"{title}. {body}" if body != title else title
        doc_id = f"youtube:{video_id}" if video_id else f"youtube:{_slugify(title)}"

        doc = ctx.make_document(
            doc_id=doc_id,
            text=doc_text,
            metadata={
                "source": "youtube",
                "video_id": video_id,
                "title": title,
                "url": hit.get("url", ""),
                "uploader": hit.get("uploader", ""),
                "channel_id": hit.get("channel_id", ""),
                "upload_date": hit.get("upload_date", ""),
                "duration": hit.get("duration", ""),
                "view_count": hit.get("view_count"),
                "thumbnail": hit.get("thumbnail", ""),
                "text_type": text_type,
                # grade is set by the context from manifest default_grade
            },
        )
        docs.append(doc)

    return docs


# ---------------------------------------------------------------------------
# Pattern-2 — Watch (continuous coverage)
# ---------------------------------------------------------------------------


def run_watchable(
    ctx: SkillContext,
    query: str,
    *,
    since: datetime | None = None,
    max_results: int = 5,
) -> list[Document]:
    """Watch YouTube for recent uploads matching ``query``.

    Implements the ``search_recent`` watchable tool declared in the manifest.
    Searches for fresh videos matching ``query`` with an upload-recency bias
    baked into yt-dlp's default search ranking.

    The ``since`` parameter is accepted for API compatibility with the Watch
    runner but YouTube's public search API does not expose a
    machine-filterable upload timestamp.  Post-search filtering by
    ``upload_date`` is applied when ``since`` is provided and the hit's
    ``upload_date`` field is available (format YYYYMMDD).

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        The topic being watched.
    since:
        Lower-bound datetime (exclusive).  Results older than this are
        filtered out when ``upload_date`` is present.
    max_results:
        Maximum Documents to return.
    """
    # Fetch a slightly larger set so filtering by ``since`` doesn't drain results.
    fetch_n = min(max_results * 3, 20)
    hits = _yt.search_videos(query, max_results=fetch_n)
    if not hits:
        return []

    since_date: str | None = None
    if since is not None:
        # Normalise to YYYYMMDD for comparison with yt-dlp's upload_date field.
        since_date = since.strftime("%Y%m%d")

    docs: list[Document] = []
    for hit in hits:
        if since_date:
            upload_date = hit.get("upload_date", "")
            if upload_date and upload_date <= since_date:
                continue  # older than the watch checkpoint

        video_id = hit.get("video_id", "")
        title = hit.get("title", "")
        if not title and not video_id:
            continue

        transcript = _yt.fetch_transcript(video_id) if video_id else ""
        if transcript:
            body = transcript
            text_type = "transcript"
        else:
            description = hit.get("description", "").strip()
            body = description if description else title
            text_type = "description"

        doc_text = f"{title}. {body}" if body != title else title
        doc_id = f"youtube:{video_id}" if video_id else f"youtube:{_slugify(title)}"

        doc = ctx.make_document(
            doc_id=doc_id,
            text=doc_text,
            metadata={
                "source": "youtube",
                "video_id": video_id,
                "title": title,
                "url": hit.get("url", ""),
                "uploader": hit.get("uploader", ""),
                "channel_id": hit.get("channel_id", ""),
                "upload_date": hit.get("upload_date", ""),
                "duration": hit.get("duration", ""),
                "view_count": hit.get("view_count"),
                "thumbnail": hit.get("thumbnail", ""),
                "text_type": text_type,
                "watchable_tool": "search_recent",
            },
        )
        docs.append(doc)
        if len(docs) >= max_results:
            break

    return docs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Return a URL-safe slug for use in doc_id only."""
    return text.lower().replace(" ", "_").replace("/", "-")[:60]
