"""Federal Register skill entrypoints — ``run`` and ``run_watchable``.

All network access is delegated to the vetted
``lighthouse_ai.sources.federal_register`` adapter; no httpx/requests/urllib/
socket imports are permitted in skill files and the registry import guard
enforces this statically.

**Egress note:** ``federalregister.gov`` is NOT on the default Lighthouse
platform allowlist. When the domain is absent ``ctx.fetch`` (called internally
by the adapter via the skill) raises ``EgressBlocked``. The skill catches that
and any other exception and returns ``[]`` with a diagnostic log entry.

To unlock live fetches run: ``lighthouse trust add federalregister.gov``

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("federal_register")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "EPA clean air act rule 2024", broker=broker)
    for doc in result.documents:
        print(doc.metadata["document_number"], doc.metadata["title"])
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import structlog

# Import the module (not the bound function) so the adapter stays patchable in
# tests via monkeypatch.setattr("lighthouse_ai.sources.federal_register.<fn>", ...)
from lighthouse_ai.sources import federal_register as _federal_register

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
    """Research a question using the Federal Register.

    Delegates to the vetted
    ``lighthouse_ai.sources.federal_register.search_rules`` adapter and
    re-wraps each returned Document through ``ctx.make_document`` so that
    every document in the corpus carries skill provenance tags
    (``skill_id``, ``skill_version``, ``grade``, ``fetch_backend``).

    **Egress degradation:** If ``federalregister.gov`` is not on the platform
    allowlist, the adapter's HTTP call will be blocked. Any exception (including
    ``EgressBlocked``) is caught; the skill returns ``[]`` and logs a note
    directing the user to run ``lighthouse trust add federalregister.gov``.

    Parameters
    ----------
    ctx:
        Capability-restricted context.
    question:
        The user's research question, agency name, rule topic, or document number.
    max_results:
        Maximum number of Documents to return (default 5).
    """
    try:
        raw_docs = _federal_register.search_rules(question, max_results=max_results)
    except Exception as exc:
        log.info(
            "federal_register.skill.egress_blocked_or_error",
            error=repr(exc),
            note="run `lighthouse trust add federalregister.gov` to enable live fetches",
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
    """Watch the Federal Register for new documents from an agency.

    Implements Pattern-2 (continuous coverage) by calling
    ``list_recent_in_agency`` (treating ``query`` as the agency slug) and
    filtering client-side to documents whose ``publication_date`` is after
    ``since`` when provided.

    **Egress degradation:** identical to ``run`` — returns ``[]`` with a log
    note if the domain is not on the allowlist.

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        Agency slug to watch (e.g. ``"epa"``, ``"fda"``, ``"doj"``).
    since:
        Lower-bound date (exclusive). Documents published on or before this
        date are filtered out. ``None`` includes all returned documents.
    max_results:
        Maximum number of Documents to return after filtering.
    """
    try:
        raw_docs = _federal_register.list_recent_in_agency(query, max_results=max_results)
    except Exception as exc:
        log.info(
            "federal_register.skill.egress_blocked_or_error",
            error=repr(exc),
            note="run `lighthouse trust add federalregister.gov` to enable live fetches",
        )
        return []

    docs: list[Document] = []
    for doc in raw_docs:
        if since is not None:
            pub_date = doc.metadata.get("publication_date", "")
            if pub_date:
                try:
                    pub_dt = datetime.fromisoformat(pub_date[:10])
                    if pub_dt <= since.replace(tzinfo=None):
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
