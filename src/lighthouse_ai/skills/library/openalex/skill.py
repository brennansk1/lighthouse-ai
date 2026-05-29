"""OpenAlex skill entrypoints — ``run`` and ``run_watchable``.

All network access is delegated to the vetted ``lighthouse_ai.sources.openalex``
adapter; no httpx/requests/urllib/socket imports are allowed in skill files and
the registry import guard enforces this statically.

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("openalex")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "mRNA vaccine efficacy trials", broker=broker)
    for doc in result.documents:
        print(doc.metadata["title"], doc.metadata.get("cited_by", 0))
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

# Import the module (not the bound function) so the adapter stays patchable in
# tests via monkeypatch.setattr("lighthouse_ai.sources.openalex.search_openalex", ...)
# and a missed patch can never silently hit the network.
from lighthouse_ai.sources import openalex as _openalex

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using the OpenAlex academic graph.

    Delegates to the vetted ``lighthouse_ai.sources.openalex.search_openalex``
    adapter and re-wraps each returned Document through ``ctx.make_document`` so
    that every document carries skill provenance tags (``skill_id``,
    ``skill_version``, ``grade``, ``fetch_backend``).

    OpenAlex covers 250M+ works across all academic disciplines. Affiliation
    metadata (``institution`` field) should be used to assess source independence:
    multiple papers from the same lab or funder are not independent evidence.

    Parameters
    ----------
    ctx:
        Capability-restricted context.
    question:
        The user's research question or keyword query.
    max_results:
        Maximum number of Documents to return (default 5).
    """
    try:
        raw_docs = _openalex.search_openalex(question, max_results=max_results)
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
    """Watch OpenAlex for recently-published works relevant to ``query``.

    Implements Pattern-2 (continuous coverage) by calling ``search_openalex``
    sorted by relevance and filtering client-side to entries whose
    ``published_date`` is newer than ``since``.

    OpenAlex does not expose a server-side ``since=`` on the free keyword search
    endpoint, so we fetch ``max_results`` papers and drop those whose
    ``published_date`` precedes the checkpoint. Callers should pass a generous
    ``max_results`` when the cadence is long (daily or longer).

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        The topic or concept being watched.
    since:
        Lower-bound timestamp (exclusive). Works with ``published_date`` at or
        before this value are filtered out. When ``None`` all returned works are
        included (useful for the first tick of a new Watch topic).
    max_results:
        Maximum number of Documents to return after filtering.
    """
    try:
        raw_docs = _openalex.search_openalex(query, max_results=max_results)
    except Exception:
        return []

    docs: list[Document] = []
    for doc in raw_docs:
        if since is not None:
            published = doc.metadata.get("published_date", "")
            if published:
                try:
                    # OpenAlex dates are ISO 8601 date strings: "2024-03-15"
                    pub_dt = datetime.fromisoformat(published.split("T")[0])
                    if pub_dt <= since:
                        continue
                except ValueError:
                    pass  # unparseable date: include the document
        tagged = ctx.make_document(
            doc_id=doc.id,
            text=doc.text,
            metadata=dict(doc.metadata),
        )
        docs.append(tagged)
    return docs
