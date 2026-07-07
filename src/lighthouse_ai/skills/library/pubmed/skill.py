"""PubMed skill entrypoints — ``run`` and ``run_watchable``.

All network access is delegated to the vetted ``lighthouse_ai.sources.pubmed``
adapter; no httpx/requests/urllib/socket imports are allowed in skill files and
the registry import guard enforces this statically.

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("pubmed")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "metformin type 2 diabetes RCT", broker=broker)
    for doc in result.documents:
        print(doc.metadata["title"], doc.metadata.get("published_date"))
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

# Import the module (not the bound function) so the adapter stays patchable in
# tests via monkeypatch.setattr("lighthouse_ai.sources.pubmed.search_pubmed", ...)
# and a missed patch can never silently hit the network.
from lighthouse_ai.sources import pubmed as _pubmed

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using PubMed biomedical literature.

    Delegates to the vetted ``lighthouse_ai.sources.pubmed.search_pubmed``
    adapter and re-wraps each returned Document through ``ctx.make_document`` so
    that every document carries skill provenance tags (``skill_id``,
    ``skill_version``, ``grade``, ``fetch_backend``).

    PubMed supports MeSH vocabulary in the query string and publication-type
    filters — see SKILL.md for the full guide. The most impactful filters for
    clinical evidence quality:
    - ``[pt]`` publication type: ``"RCT[pt]"``, ``"meta-analysis[pt]"``
    - ``[mh]`` MeSH heading: ``"diabetes mellitus[mh]"``
    - ``[tiab]`` title/abstract: ``"glycemic control[tiab]"``

    Parameters
    ----------
    ctx:
        Capability-restricted context.
    question:
        The user's research question. PubMed query syntax is supported:
        MeSH terms, field tags, Boolean operators (AND/OR/NOT).
    max_results:
        Maximum number of Documents to return (default 5).
    """
    try:
        raw_docs = _pubmed.search_pubmed(question, max_results=max_results)
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


def run_watchable(
    ctx: SkillContext,
    query: str,
    *,
    since: datetime | None = None,
    max_results: int = 5,
) -> list[Document]:
    """Watch PubMed for recently-published articles relevant to ``query``.

    Implements Pattern-2 (continuous coverage) by calling ``search_pubmed``
    sorted by relevance and filtering client-side to entries whose
    ``published_date`` is newer than ``since``.

    PubMed's E-utilities search endpoint does not expose a convenient since=
    on the public relevance-sorted path, so we fetch ``max_results`` papers and
    drop those whose ``published_date`` precedes the checkpoint. Callers should
    add ``"[dp]"`` date-posted range to the query for server-side pre-filtering
    on longer cadences.

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        The topic being watched. MeSH terms and field tags are supported.
    since:
        Lower-bound timestamp (exclusive). Articles with ``published_date`` at
        or before this value are filtered out. When ``None`` all returned
        articles are included (useful for the first tick of a new Watch topic).
    max_results:
        Maximum number of Documents to return after filtering.
    """
    try:
        raw_docs = _pubmed.search_pubmed(query, max_results=max_results)
    except Exception:
        return []

    docs: list[Document] = []
    for doc in raw_docs:
        if since is not None:
            published = doc.metadata.get("published_date", "")
            if published:
                try:
                    # PubMed dates: "2024-3" or "2024-Mar-15" or "2024"
                    # Normalise to just the year (worst case) or YYYY-MM-DD.
                    date_str = (
                        published.replace("-Jan-", "-01-")
                        .replace("-Feb-", "-02-")
                        .replace("-Mar-", "-03-")
                        .replace("-Apr-", "-04-")
                        .replace("-May-", "-05-")
                        .replace("-Jun-", "-06-")
                        .replace("-Jul-", "-07-")
                        .replace("-Aug-", "-08-")
                        .replace("-Sep-", "-09-")
                        .replace("-Oct-", "-10-")
                        .replace("-Nov-", "-11-")
                        .replace("-Dec-", "-12-")
                    )
                    # Pad partial dates with -01 so fromisoformat works
                    parts = date_str.split("-")
                    if len(parts) == 1:
                        date_str = f"{parts[0]}-01-01"
                    elif len(parts) == 2:
                        date_str = f"{parts[0]}-{parts[1].zfill(2)}-01"
                    pub_dt = datetime.fromisoformat(date_str)
                    if pub_dt <= since:
                        continue
                except (ValueError, IndexError):
                    pass  # unparseable date: include the document
        tagged = ctx.make_document(
            doc_id=doc.id,
            text=doc.text,
            metadata=dict(doc.metadata),
        )
        docs.append(tagged)
    return docs
