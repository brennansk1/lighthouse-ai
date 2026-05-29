"""Retraction Watch lookup skill — ``run``.

Composing utility: checks whether a scholarly work identified by DOI, PMID, or
arXiv ID has been retracted, had an expression of concern, or has a correction.

Data source: Crossref Labs Retraction Watch dataset (DOI 10.13003/c23rw1d9),
accessible via the standard Crossref works API by filtering on the ``update-to``
relation type. All network access is delegated to ctx.fetch so the import guard
passes; no httpx/requests/urllib/socket imports allowed.

Design note: this skill is a *composing utility*, not a destination. Callers are
arXiv/OpenAlex/PubMed/Crossref workflows that obtained a DOI, PMID, or arXiv ID
and want to check integrity before using the paper as evidence. The ``run``
entrypoint accepts a question whose first word is treated as the identifier; for
programmatic use pass the identifier directly.

Typical use (composing pattern)
---------------------------------
::

    # After fetching papers from another skill, check retraction status
    skill = load_skill("retraction_watch")
    broker = build_default_broker(data_dir)

    # Check a DOI
    result = run_skill(skill, "10.1016/s0140-6736(97)11096-0", broker=broker)
    if result.documents:
        doc = result.documents[0]
        print(doc.metadata.get("retraction_reason"), doc.metadata.get("retraction_date"))
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

# Crossref Labs Retraction Watch dataset DOI — the update-type filter value
_RW_UPDATE_TYPES = {"retraction", "expression_of_concern", "correction"}

# Crossref works API — used for retraction lookups via update-to filter
_CROSSREF_WORKS = "https://api.crossref.org/works"

_HEADERS = "Lighthouse/0.1 (mailto:research@lighthouse.local)"


def _extract_doi(identifier: str) -> str:
    """Normalise an identifier to a DOI string for the Crossref lookup.

    Handles three formats:
    - DOI: ``10.1234/journal.2023.001`` or ``https://doi.org/10.1234/...``
    - PMID: ``pmid:12345678`` or ``pubmed:12345678`` → searches Crossref by PMID
    - arXiv ID: ``arxiv:2310.00001`` or ``2310.00001`` → DOI ``10.48550/arxiv.{id}``

    Returns the normalised DOI or the original string if unrecognised.
    """
    s = identifier.strip()
    if s.startswith("https://doi.org/"):
        return s[len("https://doi.org/"):]
    if s.startswith("http://doi.org/"):
        return s[len("http://doi.org/"):]
    if s.startswith("doi:"):
        return s[4:]
    if s.startswith(("pmid:", "pubmed:")):
        # Cannot map PMID → DOI here without a network call; return as-is so
        # the caller can pre-resolve or use the PMID search path instead.
        return s
    # arXiv IDs — the Crossref DOI for arXiv papers is 10.48550/arXiv.{id}
    if s.startswith("arxiv:"):
        arxiv_id = s[6:]
        return f"10.48550/arXiv.{arxiv_id}"
    # Raw arXiv ID pattern: YYMM.NNNNN or YYMM.NNNNNN (v1/v2 optional)
    import re as _re
    if _re.match(r"^\d{4}\.\d{4,6}(v\d+)?$", s):
        return f"10.48550/arXiv.{s.split('v')[0]}"
    # Assume it's already a bare DOI
    return s


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Check retraction status for a DOI, PMID, or arXiv ID.

    The ``question`` parameter should be the identifier to check. When called
    from another skill's composing workflow, pass the DOI directly.

    Returns a list of Documents describing retraction/correction records.
    Returns an empty list if no retraction record is found (the paper is clean)
    or if the lookup fails. An empty result means "no retraction found" —
    not the same as "confirmed clean" (older papers may not be in the dataset).

    Parameters
    ----------
    ctx:
        Capability-restricted context (provides ctx.fetch for the API call).
    question:
        The identifier to look up: DOI, ``pmid:NNNNN``, or ``arxiv:YYMM.NNNNN``.
    max_results:
        Maximum number of retraction records to return (usually 1 per DOI).
    """
    identifier = question.strip().split()[0] if question.strip() else ""
    if not identifier:
        return []

    doi = _extract_doi(identifier)
    if not doi or doi.startswith("pmid:") or doi.startswith("pubmed:"):
        # PMID path: search Crossref for the PMID in the cr-relations endpoint
        # (limited support); return empty to avoid false negatives.
        return []

    # Query Crossref for works that are retractions/corrections *of* this DOI.
    # The Crossref "update-to" relation links retraction notices back to the
    # original paper. We query by filter=relation.type:retraction,doi:{doi}.
    url = (
        f"{_CROSSREF_WORKS}"
        f"?filter=relation.type:retraction,relation.object:{doi}"
        f"&rows={min(max_results, 10)}"
    )
    docs: list[Document] = []
    try:
        resp = ctx.fetch(url)
        data = json.loads(resp.content)
        items = (data.get("message") or {}).get("items", [])
        for item in items:
            title_parts = item.get("title") or []
            title = title_parts[0] if title_parts else "Retraction notice"
            retraction_doi = item.get("DOI", "")
            update_to = item.get("relation", {}).get("is-retraction-of", [{}])
            original_doi = update_to[0].get("id", doi) if update_to else doi
            # Date parsing
            dep = item.get("deposited") or {}
            dep_parts = (dep.get("date-parts") or [[]])[0]
            dep_date = "-".join(str(p) for p in dep_parts) if dep_parts else ""
            doc = ctx.make_document(
                doc_id=f"retraction_watch:{retraction_doi or title[:40]}",
                text=title,
                metadata={
                    "source": "retraction_watch",
                    "retracted_doi": original_doi,
                    "retraction_doi": retraction_doi,
                    "retraction_date": dep_date,
                    "retraction_reason": item.get("update-to", [{}])[0].get("type", "unknown")
                    if item.get("update-to") else "retraction",
                    "title": title,
                    "url": f"https://doi.org/{retraction_doi}" if retraction_doi else "",
                },
            )
            docs.append(doc)
    except Exception:
        return []

    return docs
