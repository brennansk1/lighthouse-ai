"""FRED skill entrypoints — ``run`` and ``run_watchable``.

All network access is delegated to the vetted
``lighthouse_ai.sources.fred`` adapter; no httpx/requests/urllib/socket
imports are permitted in skill files and the registry import guard enforces
this statically.

**Egress note:** ``api.stlouisfed.org`` is NOT on the default Lighthouse
platform allowlist. When the domain is absent, the adapter's HTTP call will be
blocked. Any exception (including ``EgressBlocked``) is caught; the skill
returns ``[]`` with a diagnostic log entry.

Run ``lighthouse trust add api.stlouisfed.org`` to enable live fetches.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from lighthouse_ai.sources import fred as _fred

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
    """Research a question using the FRED API.

    Searches for series matching the question, then wraps each Document
    through ``ctx.make_document`` so every document carries skill provenance
    tags (``skill_id``, ``skill_version``, ``grade``, ``fetch_backend``).

    **Egress degradation:** Any exception (including EgressBlocked) is caught;
    the skill returns ``[]`` and logs a note.
    """
    try:
        raw_docs = _fred.search_series(question, max_results=max_results)
    except Exception as exc:
        log.info(
            "fred.skill.egress_blocked_or_error",
            error=repr(exc),
            note="run `lighthouse trust add api.stlouisfed.org` to enable live fetches",
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


def run_watchable(
    ctx: SkillContext,
    query: str,
    *,
    since: datetime | None = None,
    max_results: int = 5,
) -> list[Document]:
    """Watch FRED for new or updated data releases matching ``query``.

    Lists FRED data releases (``list_releases``) and returns Documents.
    The ``since`` parameter is accepted for interface consistency; FRED
    releases do not have a server-side ``since=`` filter so all matching
    releases are returned (Watch tick handles deduplication externally).

    **Egress degradation:** identical to ``run`` — returns ``[]`` with a log
    note if the domain is not on the allowlist.
    """
    try:
        raw_docs = _fred.list_releases(max_results=max_results)
    except Exception as exc:
        log.info(
            "fred.skill.egress_blocked_or_error",
            error=repr(exc),
            note="run `lighthouse trust add api.stlouisfed.org` to enable live fetches",
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
