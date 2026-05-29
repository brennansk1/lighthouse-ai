"""CourtListener / RECAP skill entrypoints — ``run`` and ``run_watchable``.

All network access is delegated to the vetted ``lighthouse_ai.sources.courtlistener``
adapter; audio-transcript lookups go through the shared
``lighthouse_ai.sources.transcript`` helper.  No raw httpx/requests/urllib/socket
imports are present in this file — the registry import guard enforces this
statically.

Tools provided by this skill
-----------------------------
``run`` / ``search_cases``
    Free-text search across CourtListener opinions (Pattern-1 / Pattern-3).

``fetch_opinion``
    Retrieve a single opinion by cluster ID or URL; returns one Document.

``list_dockets_for_party``
    Search dockets associated with a named party.

``get_citation_treatment``
    Approximate "Shepardizing" — find opinions that cite a given case.
    **Not Westlaw/Lexis-grade**: coverage gaps exist for unpublished or
    older opinions.  Always caveat downstream.

``get_oral_argument_audio``
    Return an oral-argument Document.  CourtListener stores audio references
    for many federal appeals; transcript text is obtained via the shared
    audio-transcript pipeline (``sources/transcript.py``).  When no transcript
    is available the Document's text falls back to case metadata.

``track_docket`` (watchable)
    Watch a docket for new filings since a given timestamp (Pattern-2).

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("courtlistener")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "Fourth Amendment unreasonable search seizure 2023", broker=broker)
    for doc in result.documents:
        print(doc.metadata["title"], doc.metadata.get("court"))
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

# Import modules (not bound functions) so the adapters are monkeypatchable in
# tests via ``monkeypatch.setattr("lighthouse_ai.sources.courtlistener.search_courtlistener", …)``
# and a missed patch can never silently hit the network.
from lighthouse_ai.sources import courtlistener as _cl
from lighthouse_ai.sources import transcript as _transcript

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


# ---------------------------------------------------------------------------
# Pattern-1 / Pattern-3 — multi-source synthesis & conversational on-demand
# ---------------------------------------------------------------------------


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a legal question using CourtListener opinion search.

    Delegates to the vetted ``lighthouse_ai.sources.courtlistener.search_courtlistener``
    adapter and re-wraps each returned Document through ``ctx.make_document`` so
    that every document in the corpus carries skill provenance tags
    (``skill_id``, ``skill_version``, ``grade``, ``fetch_backend``).

    Parameters
    ----------
    ctx:
        Capability-restricted context; ``make_document`` is the only primitive
        called here (opinion text is first-party API text, not a raw web page).
    question:
        The user's legal research question or keyword query.  Boolean operators
        (AND, OR) are supported by the CourtListener API.  Phrase search with
        quotes is supported.
    max_results:
        Maximum number of Documents to return (default 5).
    """
    try:
        raw_docs = _cl.search_courtlistener(question, max_results=max_results)
    except Exception:
        return []

    docs: list[Document] = []
    for doc in raw_docs:
        tagged = ctx.make_document(
            doc_id=doc.id,
            text=doc.text,
            metadata=dict(doc.metadata),
        )
        docs.append(tagged)
    return docs


# ---------------------------------------------------------------------------
# Named tool: fetch_opinion
# ---------------------------------------------------------------------------


def fetch_opinion(
    ctx: SkillContext,
    cluster_id_or_url: str,
    *,
    max_results: int = 1,
) -> list[Document]:
    """Retrieve a single CourtListener opinion by cluster ID or absolute URL.

    Calls ``search_courtlistener`` with the identifier as the query term.
    CourtListener supports querying by cluster ID directly in the free-text
    endpoint; for a direct fetch by ID the v4 REST ``/clusters/{id}/`` endpoint
    would be preferred but is not yet wrapped by the adapter.

    Returns a list with at most one Document (may be empty if not found).
    """
    try:
        raw_docs = _cl.search_courtlistener(cluster_id_or_url, max_results=max_results)
    except Exception:
        return []

    docs: list[Document] = []
    for doc in raw_docs[:1]:
        tagged = ctx.make_document(
            doc_id=doc.id,
            text=doc.text,
            metadata=dict(doc.metadata),
        )
        docs.append(tagged)
    return docs


# ---------------------------------------------------------------------------
# Named tool: list_dockets_for_party
# ---------------------------------------------------------------------------


def list_dockets_for_party(
    ctx: SkillContext,
    party_name: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Search CourtListener for cases in which ``party_name`` is a litigant.

    Issues an opinion search with the party name as the query; CourtListener
    indexes case names and party fields so this surfaces relevant dockets.

    Parameters
    ----------
    ctx:
        Skill context.
    party_name:
        Name of the party to search for (individual, corporation, or
        government entity).
    max_results:
        Maximum Documents to return.
    """
    try:
        raw_docs = _cl.search_courtlistener(party_name, max_results=max_results)
    except Exception:
        return []

    docs: list[Document] = []
    for doc in raw_docs:
        tagged = ctx.make_document(
            doc_id=doc.id,
            text=doc.text,
            metadata=dict(doc.metadata, tool="list_dockets_for_party"),
        )
        docs.append(tagged)
    return docs


# ---------------------------------------------------------------------------
# Named tool: get_citation_treatment
# ---------------------------------------------------------------------------


def get_citation_treatment(
    ctx: SkillContext,
    citing_case: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Find opinions that cite ``citing_case`` (approximate Shepardizing).

    **Coverage caveat**: This is NOT Westlaw/Lexis-grade citation treatment.
    CourtListener's citation graph is built from RECAP-scraped and
    Free Law Project-indexed documents.  Gaps exist for:
    - Unpublished opinions not in CourtListener's index.
    - State court opinions outside CourtListener's current coverage.
    - Very recent filings not yet processed.

    Always note this limitation when using citation treatment for legal
    research conclusions.

    Parameters
    ----------
    ctx:
        Skill context.
    citing_case:
        Case name, citation string (e.g. "410 U.S. 113"), or cluster ID.
    max_results:
        Maximum number of citing opinions to return.
    """
    query = f'cites:"{citing_case}"'
    try:
        raw_docs = _cl.search_courtlistener(query, max_results=max_results)
    except Exception:
        return []

    docs: list[Document] = []
    for doc in raw_docs:
        tagged = ctx.make_document(
            doc_id=doc.id,
            text=doc.text,
            metadata=dict(doc.metadata, tool="get_citation_treatment"),
        )
        docs.append(tagged)
    return docs


# ---------------------------------------------------------------------------
# Named tool: get_oral_argument_audio
# ---------------------------------------------------------------------------


def get_oral_argument_audio(
    ctx: SkillContext,
    case_query: str,
    *,
    max_results: int = 3,
) -> list[Document]:
    """Return oral-argument Documents for cases matching ``case_query``.

    Strategy
    --------
    1. Search CourtListener for opinions matching ``case_query``.
    2. For each hit, construct an audio reference from the case URL and query
       the shared ``sources/transcript.py`` helper for an existing transcript.
    3. Return a Document per result; text is the transcript when available,
       otherwise a metadata summary (case name + snippet from the opinion).

    Transcript availability
    -----------------------
    CourtListener stores audio for many federal appeals arguments but does not
    provide machine-readable transcripts for most of them.  The shared
    ``transcribe_or_fetch_captions`` function returns ``None`` for most
    CourtListener audio references in v1 — no ASR backend is registered.
    The Document is still useful for its case metadata and opinion snippet.

    Parameters
    ----------
    ctx:
        Skill context.
    case_query:
        Case name or keyword query to find the oral argument.
    max_results:
        Maximum Documents to return.
    """
    try:
        raw_docs = _cl.search_courtlistener(case_query, max_results=max_results)
    except Exception:
        return []

    docs: list[Document] = []
    for doc in raw_docs:
        # Construct a CourtListener audio reference from the opinion URL.
        opinion_url = doc.metadata.get("url", "")
        audio_ref = opinion_url  # CourtListener audio lives at the same base URL

        # Attempt transcript via the shared pipeline.
        transcript_text = _transcript.transcribe_or_fetch_captions(audio_ref)

        if transcript_text:
            text = transcript_text
            text_type = "transcript"
        else:
            # Graceful fallback: use the opinion snippet / case name.
            text = doc.text
            text_type = "metadata_fallback"

        tagged = ctx.make_document(
            doc_id=f"cl_audio:{doc.id}",
            text=text,
            metadata=dict(
                doc.metadata,
                tool="get_oral_argument_audio",
                text_type=text_type,
                audio_ref=audio_ref,
            ),
        )
        docs.append(tagged)
    return docs


# ---------------------------------------------------------------------------
# Pattern-2 — Watch (continuous coverage): track_docket
# ---------------------------------------------------------------------------


def run_watchable(
    ctx: SkillContext,
    query: str,
    *,
    since: datetime | None = None,
    max_results: int = 5,
) -> list[Document]:
    """Watch a docket or case query for new filings since ``since``.

    Implements the ``track_docket`` watchable tool declared in the manifest.
    Searches for opinions matching ``query`` and filters client-side to those
    whose ``published_date`` (date_filed) is newer than ``since``.

    CourtListener's API does not expose a server-side ``filed_after`` filter on
    the free-text search endpoint, so filtering is done post-fetch.  Pass a
    generous ``max_results`` when the cadence is long (daily or longer) to
    avoid missing filings that fall below the pagination threshold.

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        Case name, party name, or keyword query to watch.  Use
        ``docket_number:1:23-cv-04567`` syntax for precise docket tracking when
        the docket number is known.
    since:
        Lower-bound datetime (exclusive).  Opinions with ``published_date`` at
        or before this value are filtered out.  When ``None`` all returned
        opinions are included (useful for the first tick of a new Watch topic).
    max_results:
        Maximum number of Documents to return after filtering.
    """
    try:
        raw_docs = _cl.search_courtlistener(query, max_results=max_results)
    except Exception:
        return []

    docs: list[Document] = []
    for doc in raw_docs:
        if since is not None:
            date_filed = doc.metadata.get("published_date", "")
            if date_filed:
                try:
                    # CourtListener dates are ISO 8601 or plain YYYY-MM-DD.
                    normalized = date_filed.replace("Z", "").split("T")[0]
                    filed_dt = datetime.fromisoformat(normalized)
                    if filed_dt <= since:
                        continue
                except ValueError:
                    pass  # unparseable date: include the document

        tagged = ctx.make_document(
            doc_id=doc.id,
            text=doc.text,
            metadata=dict(doc.metadata, watchable_tool="track_docket"),
        )
        docs.append(tagged)
    return docs
