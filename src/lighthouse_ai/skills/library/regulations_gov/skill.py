"""regulations.gov skill entrypoints — ``run`` and ``run_watchable``.

All network access is delegated to the vetted
``lighthouse_ai.sources.regulations_gov`` adapter; no httpx/requests/urllib/
socket imports are permitted in skill files and the registry import guard
enforces this statically.

**Egress note:** ``api.regulations.gov`` is NOT on the default Lighthouse
platform allowlist. When the domain is absent ``ctx.fetch`` raises
``EgressBlocked``. The skill catches that and any other exception and returns
``[]`` with a diagnostic log entry.

To unlock live fetches run: ``lighthouse trust add api.regulations.gov``

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("regulations_gov")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "EPA clean air particulate matter", broker=broker)
    for doc in result.documents:
        print(doc.metadata["docket_id"], doc.metadata["title"])
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import structlog

# Import the module (not the bound function) so the adapter stays patchable in
# tests via monkeypatch.setattr("lighthouse_ai.sources.regulations_gov.<fn>", ...)
from lighthouse_ai.sources import regulations_gov as _regulations_gov

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
    """Research a question using regulations.gov dockets.

    Delegates to the vetted
    ``lighthouse_ai.sources.regulations_gov.search_dockets`` adapter and
    re-wraps each returned Document through ``ctx.make_document`` so that
    every document in the corpus carries skill provenance tags.

    **Egress degradation:** If ``api.regulations.gov`` is not on the platform
    allowlist, the adapter's HTTP call will be blocked. Any exception (including
    ``EgressBlocked``) is caught; the skill returns ``[]`` and logs a note
    directing the user to run ``lighthouse trust add api.regulations.gov``.

    Parameters
    ----------
    ctx:
        Capability-restricted context.
    question:
        The user's research question, docket ID, agency name, or rule topic.
    max_results:
        Maximum number of Documents to return (default 5).
    """
    try:
        raw_docs = _regulations_gov.search_dockets(question, max_results=max_results)
    except Exception as exc:
        log.info(
            "regulations_gov.skill.egress_blocked_or_error",
            error=repr(exc),
            note="run `lighthouse trust add api.regulations.gov` to enable live fetches",
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
    """Watch a regulations.gov docket for new document activity.

    Implements Pattern-2 (continuous coverage) by calling
    ``track_docket_activity`` (treating ``query`` as the docket ID) and
    filtering client-side to documents whose ``posted_date`` is after ``since``
    when provided.

    **Egress degradation:** identical to ``run`` — returns ``[]`` with a log
    note if the domain is not on the allowlist.

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        Docket ID to watch (e.g. ``"EPA-HQ-OAR-2023-0072"``).
    since:
        Lower-bound date (exclusive). Documents posted on or before this date
        are filtered out. ``None`` includes all returned documents.
    max_results:
        Maximum number of Documents to return after filtering.
    """
    try:
        raw_docs = _regulations_gov.track_docket_activity(query, max_results=max_results)
    except Exception as exc:
        log.info(
            "regulations_gov.skill.egress_blocked_or_error",
            error=repr(exc),
            note="run `lighthouse trust add api.regulations.gov` to enable live fetches",
        )
        return []

    docs: list[Document] = []
    for doc in raw_docs:
        if since is not None:
            posted = doc.metadata.get("posted_date", "")
            if posted:
                try:
                    posted_dt = datetime.fromisoformat(posted[:10])
                    if posted_dt <= since.replace(tzinfo=None):
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
