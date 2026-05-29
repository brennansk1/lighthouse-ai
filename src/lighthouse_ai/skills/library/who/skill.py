"""WHO Global Health Observatory skill entrypoints — ``run`` and ``run_watchable``.

All network access is delegated to the vetted ``lighthouse_ai.sources.who``
adapter; no httpx/requests/urllib/socket imports are permitted in skill files
and the registry import guard enforces this statically.

**Egress note:** ``ghoapi.azureedge.net`` and ``who.int`` are NOT on the
default Lighthouse platform allowlist. When the domain is absent, ``ctx.fetch``
(called internally by the adapter) raises ``EgressBlocked``. The skill catches
that and any other exception and returns ``[]`` with a diagnostic log entry.
The skill loads and passes the import guard regardless of allowlist status.

To unlock live fetches run:
  ``lighthouse trust add ghoapi.azureedge.net``

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("who")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "maternal mortality rate by country", broker=broker)
    for doc in result.documents:
        print(doc.metadata["title"], doc.text[:120])
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import structlog

# Import the module (not the bound function) so the adapter stays patchable in
# tests via monkeypatch.setattr("lighthouse_ai.sources.who.search_who", ...)
# and a missed patch can never silently hit the network.
from lighthouse_ai.sources import who as _who

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
    """Research a question using WHO Global Health Observatory data.

    Delegates to the vetted ``lighthouse_ai.sources.who.search_who`` adapter
    and re-wraps each returned Document through ``ctx.make_document`` so that
    every document in the corpus carries skill provenance tags
    (``skill_id``, ``skill_version``, ``grade``, ``fetch_backend``).

    **Egress degradation:** If ``ghoapi.azureedge.net`` is not on the platform
    allowlist, the adapter's HTTP call will be blocked. Any exception (including
    ``EgressBlocked``) is caught; the skill returns ``[]`` and logs a note
    directing the user to run ``lighthouse trust add ghoapi.azureedge.net``.

    Parameters
    ----------
    ctx:
        Capability-restricted context.
    question:
        The user's research question (health indicator name, condition, country,
        or ICD code fragment).
    max_results:
        Maximum number of Documents to return (default 5).
    """
    try:
        raw_docs = _who.search_who(question, max_results=max_results)
    except Exception as exc:
        log.info(
            "who.skill.egress_blocked_or_error",
            error=repr(exc),
            note=(
                "run `lighthouse trust add ghoapi.azureedge.net` to enable "
                "live WHO GHO fetches"
            ),
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
    """Watch WHO GHO for newly-available indicators matching ``query``.

    Implements Pattern-2 (continuous coverage) for outbreak/indicator monitoring.
    The GHO OData API does not expose a time-ordered "new indicators since X"
    endpoint, so this implementation returns matching indicators regardless of
    ``since`` — the caller/dispatcher should track document IDs to detect
    genuinely new entries across ticks.

    In practice the most valuable watchable use case for WHO is outbreak
    monitoring via the Disease Outbreak News feed (``who.int/csr/don``), but
    that requires a separate fetch path not supported by the GHO OData API.
    This implementation uses the same GHO indicator search as ``run``.

    **Egress degradation:** identical to ``run`` — returns ``[]`` with a log
    note if the domain is not on the allowlist.

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        Health condition, indicator name, or country to watch.
    since:
        Accepted for interface compatibility but not used for server-side
        filtering (GHO OData does not support time-ordered indicator listing).
    max_results:
        Maximum number of Documents to return.
    """
    # since is accepted for API compatibility but GHO does not support it
    _ = since
    try:
        raw_docs = _who.search_who(query, max_results=max_results)
    except Exception as exc:
        log.info(
            "who.skill.egress_blocked_or_error",
            error=repr(exc),
            note=(
                "run `lighthouse trust add ghoapi.azureedge.net` to enable "
                "live WHO GHO fetches"
            ),
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
