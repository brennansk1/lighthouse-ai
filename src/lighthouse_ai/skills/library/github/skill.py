"""GitHub skill entrypoints — ``run`` and ``run_watchable``.

All network access is delegated to the vetted
``lighthouse_ai.sources.github`` adapter; no httpx/requests/urllib/
socket imports are permitted in skill files and the registry import guard
enforces this statically.

**Auth note:** Set ``lighthouse config set github.token <PAT>`` to raise the
GitHub API rate limit from 60 req/hr (unauthenticated) to 5 000 req/hr.
Unauthenticated use still works but will hit the low rate limit quickly.

**Domain note:** ``api.github.com`` and ``github.com`` are on the DEFAULT
Lighthouse egress allowlist.  No trust-add is required.

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill

    skill = load_skill("github")
    result = run_skill(skill, "rust async runtime")
    for doc in result.documents:
        print(doc.metadata["full_name"], doc.metadata["stars"])
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from lighthouse_ai.sources import github as _github

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
    """Research GitHub for repositories matching ``question``.

    Delegates to ``lighthouse_ai.sources.github.search_repos`` and re-wraps
    each returned Document through ``ctx.make_document`` for provenance tagging.

    **Egress degradation:** Any exception (including EgressBlocked if the domain
    were somehow removed from the allowlist) is caught; the skill returns [] with
    a diagnostic log entry.

    Parameters
    ----------
    ctx:
        Capability-restricted context.
    question:
        Search query — repository name, topic, language, organisation, etc.
    max_results:
        Maximum number of Documents to return.
    """
    try:
        raw_docs = _github.search_repos(question, max_results=max_results)
    except Exception as exc:
        log.info(
            "github.skill.error",
            error=repr(exc),
            note="check github.token config and allowlist; set `lighthouse config set github.token <PAT>`",
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
    max_results: int = 10,
) -> list[Document]:
    """Watch GitHub for new releases, issues, or commits matching ``query``.

    Implements Pattern-2 (continuous coverage).  The ``query`` is expected to be
    in the form ``<owner>/<repo>`` to watch releases; plain text falls back to
    repo search.  Filtering by ``since`` uses the ``published_at`` / ``created_at``
    / ``committed_at`` timestamp on each Document.

    **Egress degradation:** identical to ``run`` — returns [] with a log note on
    any exception.

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        ``owner/repo`` to watch for new releases/issues, or a search query.
    since:
        Lower-bound datetime (exclusive). Documents with a timestamp at or before
        this value are filtered out.  ``None`` includes all returned documents.
    max_results:
        Maximum number of Documents to return after filtering.
    """
    # Try to parse as owner/repo for release watching
    raw_docs: list = []
    if "/" in query and len(query.split("/")) == 2:
        owner, repo = query.split("/", 1)
        try:
            raw_docs = _github.list_releases(owner, repo, max_results=max_results)
        except Exception as exc:
            log.info("github.skill.watchable_releases_error", error=repr(exc), query=query)
    else:
        # Fall back to repo search
        try:
            raw_docs = _github.search_repos(query, max_results=max_results)
        except Exception as exc:
            log.info("github.skill.watchable_search_error", error=repr(exc), query=query)

    docs: list[Document] = []
    for doc in raw_docs:
        if since is not None:
            # Check published_at, created_at, or committed_at
            for ts_key in ("published_at", "created_at", "committed_at", "pushed_at"):
                ts_str = doc.metadata.get(ts_key, "")
                if ts_str:
                    try:
                        # GitHub timestamps are ISO 8601 with Z suffix
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        ts_naive = ts.replace(tzinfo=None)
                        since_naive = since.replace(tzinfo=None)
                        if ts_naive <= since_naive:
                            break  # filtered out
                    except (ValueError, AttributeError):
                        pass  # unparseable: include
            else:
                # No timestamp fields found or none parsed — include
                pass
            # Re-check: if we broke, skip this doc
            # Restructure to avoid complex for-else logic
            should_skip = False
            for ts_key in ("published_at", "created_at", "committed_at", "pushed_at"):
                ts_str = doc.metadata.get(ts_key, "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        ts_naive = ts.replace(tzinfo=None)
                        since_naive = since.replace(tzinfo=None)
                        if ts_naive <= since_naive:
                            should_skip = True
                    except (ValueError, AttributeError):
                        pass
                    break  # use first timestamp field found
            if should_skip:
                continue

        tagged = ctx.make_document(
            doc_id=doc.id,
            text=doc.text,
            metadata=dict(doc.metadata),
        )
        docs.append(tagged)
    return docs
