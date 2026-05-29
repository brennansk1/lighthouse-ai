"""Congress.gov skill entrypoints — ``run`` and ``run_watchable``.

All network access is delegated to the vetted
``lighthouse_ai.sources.congress_gov`` adapter; no httpx/requests/urllib/
socket imports are permitted in skill files and the registry import guard
enforces this statically.

**Egress note:** ``api.congress.gov`` is NOT on the default Lighthouse platform
allowlist. When the domain is absent ``ctx.fetch`` raises ``EgressBlocked``.
The skill catches that and any other exception and returns ``[]`` with a
diagnostic log entry.

To unlock live fetches run: ``lighthouse trust add api.congress.gov``

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("congress")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "clean energy tax credits 2024", broker=broker)
    for doc in result.documents:
        print(doc.metadata["bill_type"], doc.metadata["bill_number"], doc.metadata["title"])
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import structlog

# Import the module (not the bound function) so the adapter stays patchable in
# tests via monkeypatch.setattr("lighthouse_ai.sources.congress_gov.<fn>", ...)
from lighthouse_ai.sources import congress_gov as _congress_gov

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
    """Research a question using Congress.gov bills.

    Delegates to the vetted
    ``lighthouse_ai.sources.congress_gov.search_bills`` adapter and
    re-wraps each returned Document through ``ctx.make_document`` so that
    every document in the corpus carries skill provenance tags.

    **Egress degradation:** If ``api.congress.gov`` is not on the platform
    allowlist, the adapter's HTTP call will be blocked. Any exception (including
    ``EgressBlocked``) is caught; the skill returns ``[]`` and logs a note
    directing the user to run ``lighthouse trust add api.congress.gov``.

    Parameters
    ----------
    ctx:
        Capability-restricted context.
    question:
        The user's research question, bill topic, bill number, or sponsor name.
    max_results:
        Maximum number of Documents to return (default 5).
    """
    try:
        raw_docs = _congress_gov.search_bills(question, max_results=max_results)
    except Exception as exc:
        log.info(
            "congress.skill.egress_blocked_or_error",
            error=repr(exc),
            note="run `lighthouse trust add api.congress.gov` to enable live fetches",
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
    """Watch a congressional committee for new bill referrals.

    Implements Pattern-2 (continuous coverage) by calling
    ``track_committee`` (treating ``query`` as the committee system code)
    and filtering client-side to bills whose ``latest_action_date`` is after
    ``since`` when provided.

    **Egress degradation:** identical to ``run`` — returns ``[]`` with a log
    note if the domain is not on the allowlist.

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        Committee system code to watch (e.g. ``"hsju00"`` for House Judiciary,
        ``"sseg00"`` for Senate Energy and Natural Resources).
    since:
        Lower-bound date (exclusive). Bills whose latest action occurred on or
        before this date are filtered out. ``None`` includes all returned bills.
    max_results:
        Maximum number of Documents to return after filtering.
    """
    try:
        raw_docs = _congress_gov.track_committee(query, max_results=max_results)
    except Exception as exc:
        log.info(
            "congress.skill.egress_blocked_or_error",
            error=repr(exc),
            note="run `lighthouse trust add api.congress.gov` to enable live fetches",
        )
        return []

    docs: list[Document] = []
    for doc in raw_docs:
        if since is not None:
            action_date = doc.metadata.get("latest_action_date", "")
            if action_date:
                try:
                    action_dt = datetime.fromisoformat(action_date[:10])
                    if action_dt <= since.replace(tzinfo=None):
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
