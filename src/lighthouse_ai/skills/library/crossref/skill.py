"""Crossref skill entrypoint — ``run``.

All network access is delegated to the vetted ``lighthouse_ai.sources.crossref``
adapter; no httpx/requests/urllib/socket imports are allowed in skill files and
the registry import guard enforces this statically.

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("crossref")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "CRISPR gene editing therapeutic applications", broker=broker)
    for doc in result.documents:
        print(doc.metadata["title"], doc.metadata.get("url"))
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Import the module (not the bound function) so the adapter stays patchable in
# tests via monkeypatch.setattr("lighthouse_ai.sources.crossref.search_crossref", ...)
# and a missed patch can never silently hit the network.
from lighthouse_ai.sources import crossref as _crossref

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using the Crossref DOI registry.

    Delegates to the vetted ``lighthouse_ai.sources.crossref.search_crossref``
    adapter and re-wraps each returned Document through ``ctx.make_document`` so
    that every document carries skill provenance tags (``skill_id``,
    ``skill_version``, ``grade``, ``fetch_backend``).

    Crossref automatically assigns grades based on work type:
    - Grade A: ``journal-article``, ``proceedings-article``, ``book-chapter``
      (peer-reviewed types).
    - Grade B: preprints, datasets, reports, and other non-peer-reviewed types.

    DOIs from document metadata can be passed to the retraction_watch skill to
    check whether a paper has been retracted.

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
        raw_docs = _crossref.search_crossref(question, max_results=max_results)
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
