"""Internet Archive audio/video skill — SL10.

Tools
-----
* ``search_av``            — full-text search via advancedsearch.php, restricted
                             to mediatype:(movies OR audio).
* ``fetch_metadata``       — retrieve item metadata from archive.org/metadata/<id>.
* ``fetch_transcript``     — attempt to retrieve a transcript for an item:
                             1. Look up a caption/text file in the item metadata.
                             2. Cache via transcript.py ``cache_transcript``.
                             3. Delegate to ``transcribe_or_fetch_captions``.
                             Returns ``None`` gracefully when no ASR provider
                             is registered (v1 documented stub).
* ``get_collection_listing`` — list items in a named IA collection.

All network I/O goes through ``ctx.fetch``/``ctx.make_document`` — no direct
httpx/requests/urllib imports anywhere in this file.

Security invariants
-------------------
- No httpx / requests / urllib / socket / subprocess imports in this package.
- JSON parsed with stdlib ``json`` only.
- URL encoding done with stdlib-only helper ``_pct_encode``.

No ``datetime.now()`` at module level (constraint: deterministic offline).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from lighthouse_ai.sources import transcript as _transcript

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SEARCH_URL = "https://archive.org/advancedsearch.php"
_METADATA_URL = "https://archive.org/metadata/{identifier}"
_DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"
_DETAILS_URL = "https://archive.org/details/{identifier}"

# advancedsearch returns JSON when fl/output=json is requested
_AV_MEDIATYPE_FILTER = "mediatype:(movies OR audio)"


# ---------------------------------------------------------------------------
# URL helpers (stdlib only — no httpx/urllib)
# ---------------------------------------------------------------------------

def _pct_encode(s: str) -> str:
    """Percent-encode a string for use in a URL query value (stdlib only)."""
    safe = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789"
        "-_.~"
    )
    out: list[str] = []
    for ch in s.encode("utf-8"):
        c = chr(ch)
        if c in safe:
            out.append(c)
        else:
            out.append(f"%{ch:02X}")
    return "".join(out)


def _build_search_url(
    query: str,
    *,
    rows: int = 10,
    extra_filter: str | None = None,
    sort: str = "downloads desc",
    collection: str | None = None,
) -> str:
    """Build an advancedsearch.php URL for AV items."""
    # Combine the user query with the AV mediatype filter.
    if collection:
        full_query = f"({query}) AND collection:({_pct_encode(collection)}) AND {_AV_MEDIATYPE_FILTER}"
    else:
        full_query = f"({query}) AND {_AV_MEDIATYPE_FILTER}"
    if extra_filter:
        full_query = f"({full_query}) AND ({extra_filter})"

    parts = [
        f"{_SEARCH_URL}?q={_pct_encode(full_query)}",
        "fl[]=identifier",
        "fl[]=title",
        "fl[]=description",
        "fl[]=mediatype",
        "fl[]=date",
        "fl[]=subject",
        "fl[]=creator",
        "fl[]=collection",
        f"sort[]={_pct_encode(sort)}",
        f"rows={rows}",
        "page=1",
        "output=json",
    ]
    return "&".join(parts)


# ---------------------------------------------------------------------------
# Tool: search_av
# ---------------------------------------------------------------------------

def search_av(
    ctx: SkillContext,
    query: str,
    *,
    max_results: int = 10,
    collection: str | None = None,
) -> list[dict]:
    """Search archive.org for audio/video items matching ``query``.

    Uses the advancedsearch.php endpoint with ``mediatype:(movies OR audio)``
    filter.  Returns a list of item metadata dicts (identifier, title,
    description, mediatype, date, creator, collection).

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        Full-text search query.
    max_results:
        Maximum items to return.
    collection:
        Optional IA collection identifier to restrict results.

    Returns
    -------
    list[dict]
        List of item metadata dicts; empty list on error or no results.
    """
    url = _build_search_url(query, rows=max_results, collection=collection)
    try:
        resp = ctx.fetch(url)
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    try:
        data = json.loads(resp.content)
    except (json.JSONDecodeError, ValueError):
        return []

    docs_raw = data.get("response", {}).get("docs", [])
    results: list[dict] = []
    for item in docs_raw:
        if not isinstance(item, dict):
            continue
        results.append({
            "identifier": item.get("identifier", ""),
            "title": item.get("title", ""),
            "description": item.get("description", ""),
            "mediatype": item.get("mediatype", ""),
            "date": item.get("date", ""),
            "creator": item.get("creator", ""),
            "subject": item.get("subject", ""),
            "collection": item.get("collection", ""),
            "url": _DETAILS_URL.format(identifier=item.get("identifier", "")),
        })
    return results[:max_results]


# ---------------------------------------------------------------------------
# Tool: fetch_metadata
# ---------------------------------------------------------------------------

def fetch_metadata(
    ctx: SkillContext,
    identifier: str,
) -> dict:
    """Fetch full item metadata for an Internet Archive identifier.

    Calls ``archive.org/metadata/<identifier>`` and returns the parsed JSON
    as a dict.  The ``metadata`` sub-dict contains title, description,
    creator, date, subject, mediatype, etc.  The ``files`` list contains
    all files associated with the item (audio, video, captions, texts).

    Parameters
    ----------
    ctx:
        Skill context.
    identifier:
        Internet Archive item identifier (e.g. ``MSNBC_20060612_060000_Hardball``).

    Returns
    -------
    dict
        Full metadata response dict; empty dict on error.
    """
    url = _METADATA_URL.format(identifier=_pct_encode(identifier))
    try:
        resp = ctx.fetch(url)
    except Exception:
        return {}
    if resp.status_code != 200:
        return {}
    try:
        return json.loads(resp.content)
    except (json.JSONDecodeError, ValueError):
        return {}


# ---------------------------------------------------------------------------
# Tool: fetch_transcript
# ---------------------------------------------------------------------------

def fetch_transcript(
    ctx: SkillContext,
    identifier: str,
    *,
    metadata: dict | None = None,
) -> str | None:
    """Attempt to retrieve a transcript for an Internet Archive item.

    Strategy (highest-priority first):

    1. Check ``transcript.py`` in-process cache for ``identifier``.
    2. If item metadata contains a caption/subtitles/text file (e.g. a ``.srt``,
       ``.vtt``, or ``_text.txt`` file in ``files``), fetch it via ``ctx.fetch``
       and populate the cache via ``cache_transcript``.
    3. Delegate to ``transcribe_or_fetch_captions(identifier)`` which tries any
       registered ASR providers.
    4. Return ``None`` gracefully — ASR is a v1 documented stub.

    Parameters
    ----------
    ctx:
        Skill context.
    identifier:
        Internet Archive item identifier.
    metadata:
        Optional pre-fetched metadata dict (from ``fetch_metadata``).  When
        provided, avoids a redundant metadata fetch to find caption files.

    Returns
    -------
    str or None
        Transcript text if available, ``None`` otherwise.
    """
    # 1. Delegate to transcript.py — checks in-process cache first, then
    #    registered providers.  If something is already cached for this
    #    identifier, return it immediately.
    cached = _transcript.transcribe_or_fetch_captions(identifier)
    if cached is not None:
        return cached

    # 2. Look for a caption/subtitle file in the item metadata.
    if metadata is None:
        metadata = fetch_metadata(ctx, identifier)

    files: list[dict] = metadata.get("files", []) if metadata else []
    caption_file = _find_caption_file(files)

    if caption_file:
        filename = caption_file.get("name", "")
        caption_url = _DOWNLOAD_URL.format(
            identifier=_pct_encode(identifier),
            filename=_pct_encode(filename),
        )
        try:
            resp = ctx.fetch(caption_url)
        except Exception:
            resp = None

        if resp is not None and resp.status_code == 200:
            text = resp.content.decode("utf-8", errors="replace").strip()
            if text:
                # Populate cache so subsequent calls are free.
                _transcript.cache_transcript(identifier, text)
                return text

    # 3. Try any registered ASR providers (may return None — that is fine).
    return _transcript.transcribe_or_fetch_captions(identifier)


def _find_caption_file(files: list[dict]) -> dict | None:
    """Return the first caption/subtitle/text file entry from an IA files list."""
    # Prefer formats in this order: VTT, SRT, CC (closed caption), plain text.
    _CAPTION_EXTS = (".vtt", ".srt", ".cc.txt", "_captions.txt", "_text.txt")
    _CAPTION_FORMATS = {"SubRip", "WebVTT", "Closed Caption Text", "Text"}

    # Check by format field first (most reliable).
    for f in files:
        if not isinstance(f, dict):
            continue
        if f.get("format", "") in _CAPTION_FORMATS:
            return f

    # Fall back to extension heuristic.
    for f in files:
        if not isinstance(f, dict):
            continue
        name = f.get("name", "").lower()
        for ext in _CAPTION_EXTS:
            if name.endswith(ext):
                return f

    return None


# ---------------------------------------------------------------------------
# Tool: get_collection_listing
# ---------------------------------------------------------------------------

def get_collection_listing(
    ctx: SkillContext,
    collection: str,
    *,
    max_results: int = 10,
) -> list[dict]:
    """List audio/video items in a named Internet Archive collection.

    Parameters
    ----------
    ctx:
        Skill context.
    collection:
        Internet Archive collection identifier (e.g. ``tvarchive``,
        ``prelinger``, ``oldtimeradio``).
    max_results:
        Maximum items to return.

    Returns
    -------
    list[dict]
        List of item metadata dicts; empty list on error or empty collection.
    """
    return search_av(ctx, "*", max_results=max_results, collection=collection)


# ---------------------------------------------------------------------------
# run() — primary entrypoint
# ---------------------------------------------------------------------------

def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using Internet Archive audio/video collections.

    Strategy
    --------
    1. ``search_av`` — query advancedsearch.php for AV items matching ``question``.
    2. For each hit call ``fetch_metadata`` to get the full item record.
    3. Attempt ``fetch_transcript`` (caption files + transcript.py providers).
    4. Build a ``Document`` via ``ctx.make_document`` with title + description +
       transcript (if available) as the body text.

    Parameters
    ----------
    ctx:
        Capability-restricted context.
    question:
        Research question or keyword query.
    max_results:
        Maximum number of Documents to return (default 5).

    Returns
    -------
    list[Document]
        Broker-admitted Documents tagged ``source="internet_archive_av"``.
    """
    hits = search_av(ctx, question, max_results=max_results)
    if not hits:
        return []

    docs: list[Document] = []
    for hit in hits:
        identifier = hit.get("identifier", "")
        if not identifier:
            continue

        # Fetch full metadata to get the files list (needed for caption lookup).
        meta = fetch_metadata(ctx, identifier)
        item_meta = meta.get("metadata", {}) if meta else {}

        title = item_meta.get("title", hit.get("title", identifier))
        description = item_meta.get("description", hit.get("description", ""))
        creator = item_meta.get("creator", hit.get("creator", ""))
        date = item_meta.get("date", hit.get("date", ""))
        subject = item_meta.get("subject", hit.get("subject", ""))
        mediatype = item_meta.get("mediatype", hit.get("mediatype", ""))
        collection = item_meta.get("collection", hit.get("collection", ""))

        # Attempt transcript retrieval; fall back to description gracefully.
        transcript = fetch_transcript(ctx, identifier, metadata=meta)

        if transcript:
            body = transcript
            text_type = "transcript"
        elif description:
            body = description if isinstance(description, str) else " ".join(description)
            text_type = "description"
        else:
            body = title
            text_type = "title_only"

        # Build document text: title + body.
        doc_text = f"{title}. {body}" if body and body != title else title

        doc = ctx.make_document(
            doc_id=f"ia_av:{identifier}",
            text=doc_text,
            metadata={
                "source": "internet_archive_av",
                "identifier": identifier,
                "url": _DETAILS_URL.format(identifier=identifier),
                "title": title,
                "creator": creator,
                "date": date,
                "subject": subject,
                "mediatype": mediatype,
                "collection": collection,
                "text_type": text_type,
            },
        )
        docs.append(doc)
        if len(docs) >= max_results:
            break

    return docs
