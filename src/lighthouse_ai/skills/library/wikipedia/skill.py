"""Wikipedia skill entrypoints — ``run`` and ``run_watchable``.

All network access goes through ``ctx`` primitives (no httpx/requests/urllib).
The import guard in the registry enforces this statically.

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("wikipedia")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "What is the Higgs boson?", broker=broker)
    for doc in result.documents:
        print(doc.metadata["title"], doc.text[:120])
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from .tools.fetch_page import fetch_page
from .tools.recent_revisions import recent_revisions
from .tools.search import search

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using Wikipedia.

    Strategy
    --------
    1. Search Wikipedia for the question (Action API ``list=search``).
    2. For each of the top ``max_results`` hits fetch the REST summary
       (fast, lead paragraph only).  For the single best-ranked hit also
       fetch the full extract so the corpus contains at least one detailed
       document.
    3. De-duplicate by URL and return up to ``max_results`` documents.

    Documents are tagged with ``source="wikipedia"``, ``title``, ``url``,
    and the framework-level ``skill_id``/``skill_version`` fields applied by
    the runner.

    Parameters
    ----------
    ctx:
        Capability-restricted context (fetch + make_document only).
    question:
        The user's research question.
    max_results:
        Maximum number of Documents to return (default 5).
    """
    hits = search(ctx, question, limit=max_results)
    if not hits:
        return []

    docs: list[Document] = []
    seen_urls: set[str] = set()

    for i, hit in enumerate(hits[:max_results]):
        title = hit.get("title", "")
        if not title:
            continue
        use_full = i == 0  # Full extract only for the top result
        doc = fetch_page(ctx, title, full_extract=use_full)
        if doc is None:
            # Fallback: build a minimal document from the search snippet.
            snippet = hit.get("snippet", "")
            if snippet:
                doc = ctx.make_document(
                    doc_id=f"wikipedia:snippet:{_slugify(title)}",
                    text=snippet,
                    metadata={
                        "source": "wikipedia",
                        "title": title,
                        "url": hit.get("url", ""),
                        "type": "snippet",
                    },
                )
        if doc is None:
            continue
        url = doc.metadata.get("url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        docs.append(doc)

    return docs


def run_watchable(
    ctx: SkillContext,
    query: str,
    *,
    since: datetime | None = None,
    max_results: int = 5,
) -> list[Document]:
    """Watch Wikipedia for recent edits relevant to ``query``.

    Implements Pattern-2 (continuous coverage) by delegating to the
    :func:`~.tools.recent_revisions.recent_revisions` tool which queries the
    MediaWiki Action API ``list=recentchanges`` and filters by topic terms.

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        The topic being watched (used to filter relevant recent changes).
    since:
        Lower-bound timestamp (exclusive).  When ``None`` defaults to 24 h ago
        so the first Watch tick always returns something meaningful.
    max_results:
        Maximum number of revision documents to return.
    """
    return recent_revisions(ctx, query, since=since, max_results=max_results)


# ---- helpers ---------------------------------------------------------------


def _slugify(text: str) -> str:
    """Return a URL-safe slug for a title (used in doc_id only)."""
    return text.lower().replace(" ", "_").replace("/", "-")
