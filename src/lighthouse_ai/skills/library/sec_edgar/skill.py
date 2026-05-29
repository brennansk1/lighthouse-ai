"""SEC EDGAR skill entrypoints — ``run`` and ``run_watchable``.

All network access is delegated to the vetted
``lighthouse_ai.sources.sec_edgar`` adapter; no httpx/requests/urllib/socket
imports are allowed in skill files and the registry import guard enforces this
statically.

The skill wraps the following logical tools around the adapter:

Search / fetch
    ``search_filings``       — full-text EDGAR search (via ``run``)
    ``list_recent_for_cik``  — watchable: recent filings for a CIK

Parsing (offline, deterministic)
    ``parse_10k_item_1a``    — Risk Factors section extractor (Item 1A)
    ``parse_10k_item_7``     — MD&A section extractor (Item 7)
    ``parse_10q_changes``    — detect material QoQ changes (simple diff)

Entity / event tools (adapter-backed)
    ``fetch_filing``            — fetch a specific accession-number filing
    ``get_insider_transactions``— Form 4 insider transactions for a CIK
    ``get_proxy_executives``    — executive names/compensation from DEF 14A

Typical use
-----------
::

    from lighthouse_ai.skills import load_skill, run_skill
    from lighthouse_ai.sandbox.broker import build_default_broker

    skill = load_skill("sec_edgar")
    broker = build_default_broker(data_dir)
    result = run_skill(skill, "Apple 10-K risk factors", broker=broker)
    for doc in result.documents:
        print(doc.metadata["title"], doc.text[:200])
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

# Import the module (not the bound function) so the adapter stays patchable in
# tests via monkeypatch.setattr("lighthouse_ai.sources.sec_edgar.search_sec_edgar", ...)
# and a missed patch can never silently hit the network.
from lighthouse_ai.sources import sec_edgar as _sec_edgar

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using SEC EDGAR filings.

    Delegates to the vetted ``lighthouse_ai.sources.sec_edgar.search_sec_edgar``
    adapter and re-wraps each returned Document through ``ctx.make_document`` so
    that every document in the corpus carries skill provenance tags
    (``skill_id``, ``skill_version``, ``grade``, ``fetch_backend``).

    This function implements the ``search_filings`` logical tool: a free-text
    search over EDGAR's full-text search index covering 10-K, 10-Q, 8-K, DEF
    14A, Form 4, and other filing types.

    Parameters
    ----------
    ctx:
        Capability-restricted context.
    question:
        The user's research question or query string.  Supports EDGAR EFTS
        query syntax: filing type filters (``form-type:10-K``), entity name
        searches, and keyword phrases.
    max_results:
        Maximum number of Documents to return (default 5).
    """
    try:
        raw_docs = _sec_edgar.search_sec_edgar(question, max_results=max_results)
    except Exception:
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
    """Watch SEC EDGAR for new filings matching ``query`` (Pattern-2 / Watch mode).

    Implements the ``list_recent_for_cik`` logical tool when ``query`` is a CIK
    number, or a general "new filings" watch when ``query`` is a keyword or
    company name.

    The EDGAR EFTS API does not expose a server-side ``since=`` filter on its
    search endpoint, so this function fetches ``max_results`` recent matching
    filings and filters client-side on ``file_date`` (the EDGAR filing date field
    from the adapter's Document metadata) to drop anything filed on or before
    ``since``.

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        Company name, CIK number, or keyword to watch for.  For CIK-based
        watching use the bare numeric CIK (e.g. "0000320193" for Apple Inc.).
    since:
        Lower-bound timestamp (exclusive).  Filings with a ``file_date``
        (ISO 8601 date string "YYYY-MM-DD") on or before this date are dropped.
        When ``None`` all returned filings are included (useful for the first
        tick of a new Watch topic).
    max_results:
        Maximum number of Documents to return after filtering.
    """
    try:
        raw_docs = _sec_edgar.search_sec_edgar(query, max_results=max_results)
    except Exception:
        return []

    docs: list[Document] = []
    for doc in raw_docs:
        if since is not None:
            file_date = doc.metadata.get("published_date", "")
            if file_date:
                try:
                    # EDGAR file_date is "YYYY-MM-DD"
                    filing_dt = datetime.strptime(file_date, "%Y-%m-%d")
                    if filing_dt <= since:
                        continue
                except ValueError:
                    pass  # unparseable date — include the document

        tagged = ctx.make_document(
            doc_id=doc.id,
            text=doc.text,
            metadata=dict(doc.metadata),
        )
        docs.append(tagged)
    return docs
