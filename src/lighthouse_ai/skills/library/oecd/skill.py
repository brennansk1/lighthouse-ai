"""OECD skill entrypoints — ``run``.

All network access is delegated to the vetted
``lighthouse_ai.sources.oecd`` adapter; no httpx/requests/urllib/socket
imports are permitted in skill files and the registry import guard enforces
this statically.

**Egress note:** ``sdmx.oecd.org`` is NOT on the default Lighthouse platform
allowlist. When the domain is absent, the adapter's HTTP call will be blocked.
Any exception (including ``EgressBlocked``) is caught; the skill returns ``[]``
with a diagnostic log entry.

Run ``lighthouse trust add sdmx.oecd.org`` to enable live fetches.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from lighthouse_ai.sources import oecd as _oecd

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
    """Research a question using the OECD SDMX API.

    Searches the curated OECD dataset catalog for datasets matching the
    question and wraps each Document through ``ctx.make_document`` so every
    document carries skill provenance tags (``skill_id``, ``skill_version``,
    ``grade``, ``fetch_backend``).

    **Egress degradation:** Any exception (including EgressBlocked) is caught;
    the skill returns ``[]`` and logs a note. The catalog search itself does
    not require network access (it uses the local curated catalog).
    """
    try:
        raw_docs = _oecd.search_dataset(question, max_results=max_results)
    except Exception as exc:
        log.info(
            "oecd.skill.egress_blocked_or_error",
            error=repr(exc),
            note="run `lighthouse trust add sdmx.oecd.org` to enable live fetches",
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
