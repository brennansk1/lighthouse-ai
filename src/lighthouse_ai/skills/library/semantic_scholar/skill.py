"""Semantic Scholar skill entrypoint — ``run``.

All network access is delegated to the vetted
``lighthouse_ai.sources.semantic_scholar`` adapter; no httpx/requests/urllib/
socket imports are allowed in skill files and the registry import guard enforces
this statically.

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("semantic_scholar")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "contrastive learning self-supervised representation", broker=broker)
    for doc in result.documents:
        print(doc.metadata["title"], doc.metadata.get("citation_count", 0))
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Import the module (not the bound function) so the adapter stays patchable in
# tests via monkeypatch.setattr(
#     "lighthouse_ai.sources.semantic_scholar.search_semantic_scholar", ...)
# and a missed patch can never silently hit the network.
from lighthouse_ai.sources import semantic_scholar as _s2

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using Semantic Scholar.

    Delegates to the vetted
    ``lighthouse_ai.sources.semantic_scholar.search_semantic_scholar`` adapter
    and re-wraps each returned Document through ``ctx.make_document`` so that
    every document carries skill provenance tags (``skill_id``,
    ``skill_version``, ``grade``, ``fetch_backend``).

    The key differentiator vs OpenAlex is the ``citation_count`` metadata and
    the S2 influential-citation signal (available via the graph API). Use this
    skill when the question is about *how* a paper is received, replicated, or
    challenged — not just whether it exists.

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
        raw_docs = _s2.search_semantic_scholar(question, max_results=max_results)
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
