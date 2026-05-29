"""arXiv skill entrypoints — ``run`` and ``run_watchable``.

All network access is delegated to the vetted ``lighthouse_ai.sources.arxiv``
adapter; no httpx/requests/urllib/socket imports are allowed in skill files and
the registry import guard enforces this statically.

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("arxiv")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "transformer attention mechanisms efficiency", broker=broker)
    for doc in result.documents:
        print(doc.metadata["title"], doc.text[:120])
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

# Import the module (not the bound function) so the adapter stays patchable in
# tests via monkeypatch.setattr("lighthouse_ai.sources.arxiv.search_arxiv", ...)
# and a missed patch can never silently hit the network.
from lighthouse_ai.sources import arxiv as _arxiv

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using arXiv preprints.

    Delegates to the vetted ``lighthouse_ai.sources.arxiv.search_arxiv`` adapter
    and re-wraps each returned Document through ``ctx.make_document`` so that
    every document in the corpus carries skill provenance tags
    (``skill_id``, ``skill_version``, ``grade``, ``fetch_backend``).

    Parameters
    ----------
    ctx:
        Capability-restricted context.
    question:
        The user's research question or keyword query. arXiv field prefixes are
        supported: ``cat:cs.LG``, ``au:LeCun``, ``ti:attention``.
    max_results:
        Maximum number of Documents to return (default 5).
    """
    try:
        raw_docs = _arxiv.search_arxiv(question, max_results=max_results)
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
    """Watch arXiv for newly-submitted papers relevant to ``query``.

    Implements Pattern-2 (continuous coverage) by calling
    ``search_arxiv`` sorted by submission date and filtering
    client-side to entries newer than ``since``.

    The arXiv API does not support server-side ``since=`` filtering on its public
    query endpoint, so we fetch ``max_results`` recent papers and drop those
    whose ``published_date`` precedes the checkpoint. Callers should pass a
    generous ``max_results`` when the cadence is long (daily or longer).

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        The topic being watched (keyword query, field prefixes supported).
    since:
        Lower-bound timestamp (exclusive). Papers with ``published_date`` at or
        before this value are filtered out. When ``None`` all returned papers
        are included (useful for the first tick of a new Watch topic).
    max_results:
        Maximum number of Documents to return after filtering.
    """
    try:
        raw_docs = _arxiv.search_arxiv(query, max_results=max_results)
    except Exception:
        return []

    docs: list[Document] = []
    for doc in raw_docs:
        if since is not None:
            published = doc.metadata.get("published_date", "")
            if published:
                try:
                    # arXiv dates are ISO 8601: "2024-03-15T12:00:00Z"
                    pub_dt = datetime.fromisoformat(published.rstrip("Z"))
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
