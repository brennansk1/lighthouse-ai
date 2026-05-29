"""BEA skill entrypoints — ``run``.

All network access is delegated to the vetted
``lighthouse_ai.sources.bea`` adapter; no httpx/requests/urllib/socket
imports are permitted in skill files and the registry import guard enforces
this statically.

**Egress note:** ``apps.bea.gov`` is NOT on the default Lighthouse platform
allowlist. When the domain is absent, the adapter's HTTP call will be blocked.
Any exception (including ``EgressBlocked``) is caught; the skill returns ``[]``
with a diagnostic log entry.

Run ``lighthouse trust add apps.bea.gov`` to enable live fetches.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from lighthouse_ai.sources import bea as _bea

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

log = structlog.get_logger(__name__)


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using the BEA API.

    Searches BEA datasets matching the question and wraps each returned
    Document through ``ctx.make_document`` so every document carries skill
    provenance tags (``skill_id``, ``skill_version``, ``grade``, ``fetch_backend``).

    **Egress degradation:** Any exception (including EgressBlocked) is caught;
    the skill returns ``[]`` and logs a note.
    """
    try:
        raw_docs = _bea.search_dataset(question, max_results=max_results)
    except Exception as exc:
        log.info(
            "bea.skill.egress_blocked_or_error",
            error=repr(exc),
            note="run `lighthouse trust add apps.bea.gov` to enable live fetches",
        )
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
