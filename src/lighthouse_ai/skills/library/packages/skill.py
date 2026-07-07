"""Package registries skill entrypoints — ``run`` and ``run_watchable``.

Covers three sub-registries: PyPI (Python), npm (JavaScript/Node.js), and
crates.io (Rust).  All network access is delegated to the vetted
``lighthouse_ai.sources.packages`` adapter; no httpx/requests/urllib/socket
imports are permitted in skill files and the registry import guard enforces
this statically.

**Egress note:** ``pypi.org``, ``registry.npmjs.org``, and ``crates.io`` are
NOT on the default Lighthouse platform allowlist.  The skill catches any
exception (including EgressBlocked) and returns [] with a logged note.  To
unlock live fetches:

    lighthouse trust add pypi.org
    lighthouse trust add registry.npmjs.org
    lighthouse trust add crates.io

**Query format for ``run``:**
  - Plain name (e.g. ``"requests"``) → tried as PyPI + npm + crates search.
  - Prefixed: ``"pypi:requests"``, ``"npm:react"``, ``"crates:tokio"`` to
    target a specific registry.

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill

    skill = load_skill("packages")
    result = run_skill(skill, "pypi:httpx")
    for doc in result.documents:
        print(doc.metadata["name"], doc.metadata["version"])
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from lighthouse_ai.sources import packages as _packages

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

log = structlog.get_logger(__name__)

_REGISTRIES = ("pypi", "npm", "crates")


def _parse_prefix(question: str) -> tuple[str | None, str]:
    """Return (registry, query) from a prefixed or plain query string."""
    for reg in _REGISTRIES:
        if question.startswith(f"{reg}:"):
            return reg, question[len(reg) + 1 :]
    return None, question


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research package registries for packages matching ``question``.

    If the question is prefixed with ``pypi:``, ``npm:``, or ``crates:``, only
    that registry is queried.  Otherwise all three registries are tried and
    results are merged (up to ``max_results`` per registry).

    **Egress degradation:** Any exception (including EgressBlocked) is caught
    per-registry; the skill returns whatever partial results succeeded and logs
    a note for each failure.

    Parameters
    ----------
    ctx:
        Capability-restricted context.
    question:
        Package name or search query; optionally prefixed with ``pypi:``,
        ``npm:``, or ``crates:``.
    max_results:
        Maximum number of Documents per registry (not total).
    """
    registry, query = _parse_prefix(question)
    raw_docs: list = []

    registries_to_try = [registry] if registry else list(_REGISTRIES)

    for reg in registries_to_try:
        try:
            if reg == "pypi":
                raw_docs.extend(_packages.pypi_search_package(query, max_results=max_results))
            elif reg == "npm":
                raw_docs.extend(_packages.npm_search_package(query, max_results=max_results))
            elif reg == "crates":
                raw_docs.extend(_packages.crates_search_package(query, max_results=max_results))
        except Exception as exc:
            log.info(
                "packages.skill.error",
                registry=reg,
                error=repr(exc),
                note=f"run `lighthouse trust add` for {reg} to enable live fetches",
            )

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
    """Watch package registries for new releases of ``query``.

    The ``query`` is expected to be in the form ``<registry>:<package_name>``
    (e.g. ``"pypi:django"``, ``"npm:react"``, ``"crates:tokio"``).  Without a
    prefix, all three registries are queried.

    Filtering by ``since`` uses ``upload_time`` (PyPI), ``published_at`` (npm),
    or ``created_at`` (crates.io) on each Document.

    **Egress degradation:** identical to ``run`` — returns [] with a log note
    on any exception.

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        ``<registry>:<package_name>`` or plain package name.
    since:
        Lower-bound datetime (exclusive). Documents with a timestamp at or
        before this value are filtered out.
    max_results:
        Maximum number of Documents per registry after filtering.
    """
    registry, package_name = _parse_prefix(query)
    raw_docs: list = []

    registries_to_try = [registry] if registry else list(_REGISTRIES)

    for reg in registries_to_try:
        try:
            if reg == "pypi":
                raw_docs.extend(
                    _packages.pypi_list_recent_releases_for_package(
                        package_name, max_results=max_results
                    )
                )
            elif reg == "npm":
                raw_docs.extend(
                    _packages.npm_list_recent_releases_for_package(
                        package_name, max_results=max_results
                    )
                )
            elif reg == "crates":
                raw_docs.extend(
                    _packages.crates_list_recent_releases_for_package(
                        package_name, max_results=max_results
                    )
                )
        except Exception as exc:
            log.info(
                "packages.skill.watchable_error",
                registry=reg,
                error=repr(exc),
            )

    docs: list[Document] = []
    for doc in raw_docs:
        if since is not None:
            # Each registry uses a different timestamp key
            for ts_key in ("upload_time", "published_at", "created_at", "updated_at"):
                ts_str = doc.metadata.get(ts_key, "")
                if ts_str:
                    try:
                        # Normalise: PyPI uses "2024-03-15T10:00:00", npm uses ISO
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        ts_naive = ts.replace(tzinfo=None)
                        since_naive = since.replace(tzinfo=None)
                        if ts_naive <= since_naive:
                            break  # skip this doc
                    except (ValueError, AttributeError):
                        pass
                    break  # use first matching timestamp field
            else:
                # No timestamp: include
                pass
            # Cleaner re-check
            should_skip = False
            for ts_key in ("upload_time", "published_at", "created_at", "updated_at"):
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
                    break
            if should_skip:
                continue

        tagged = ctx.make_document(
            doc_id=doc.id,
            text=doc.text,
            metadata=dict(doc.metadata),
        )
        docs.append(tagged)
    return docs
