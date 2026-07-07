"""ClinicalTrials.gov source adapter — ClinicalTrials.gov REST API v2.

ClinicalTrials.gov is the authoritative U.S. (and international) registry of
clinical trials. Records are grade "A" as primary regulatory documents.
The v2 REST API (``/api/v2/studies``) accepts free-text ``query.term`` plus
optional field-specific filters; responses are JSON with a ``studies`` array
and an optional ``nextPageToken`` for pagination. This adapter fetches a
single page (``pageSize=max_results``) for simplicity.

**Egress note:** ``clinicaltrials.gov`` is NOT on the default Lighthouse
platform allowlist. The skill wrapping this adapter will receive an
``EgressBlocked`` exception from ``ctx.fetch``. The skill degrades gracefully
(returns ``[]`` with a logged note). To unlock live fetches run:
``lighthouse trust add clinicaltrials.gov``

The adapter is httpx-based and client-injectable so it is testable under
``respx`` without real network access; when ``client`` is omitted we open and
close a short-lived ``httpx.Client``.
"""

from __future__ import annotations

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

_BASE = "https://clinicaltrials.gov/api/v2/studies"
_HEADERS = {"User-Agent": "Lighthouse/0.1", "Accept": "application/json"}
# Public API host(s) this adapter contacts; the user invoked the ClinicalTrials
# source for these, so they are authorized for egress.
_ALLOWED_HOSTS = frozenset({"clinicaltrials.gov", "www.clinicaltrials.gov"})


def _parse_studies(data: dict) -> list[Document]:
    """Turn a v2 /studies JSON response into Documents.

    Each study has a ``protocolSection`` wrapping ``identificationModule``,
    ``statusModule``, ``descriptionModule``, and ``conditionsModule``.  We
    extract NCT ID, title, brief summary, conditions, and start date.
    """
    studies = data.get("studies") or []
    out: list[Document] = []
    for study in studies:
        ps = study.get("protocolSection") or {}
        id_mod = ps.get("identificationModule") or {}
        status_mod = ps.get("statusModule") or {}
        desc_mod = ps.get("descriptionModule") or {}
        cond_mod = ps.get("conditionsModule") or {}

        nct_id = (id_mod.get("nctId") or "").strip()
        title = " ".join((id_mod.get("officialTitle") or id_mod.get("briefTitle") or "").split())
        if not title:
            continue

        summary = " ".join((desc_mod.get("briefSummary") or "").split())
        conditions = cond_mod.get("conditions") or []
        start_date = (status_mod.get("startDateStruct") or {}).get("date", "")
        overall_status = (status_mod.get("overallStatus") or "").strip()
        url = f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else ""

        text = title
        if summary:
            text = f"{title}. {summary}"

        out.append(
            Document(
                id=f"clinicaltrials:{nct_id}" if nct_id else f"clinicaltrials:{title[:40]}",
                text=text,
                metadata={
                    "source": "clinicaltrials",
                    "url": url,
                    "grade": "A",
                    "title": title,
                    "nct_id": nct_id,
                    "conditions": conditions,
                    "overall_status": overall_status,
                    "start_date": start_date,
                },
            )
        )
    return out


def search_trials(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> list[Document]:
    """Search ClinicalTrials.gov and return up to ``max_results`` trials as Documents.

    Uses the v2 REST API ``/api/v2/studies`` endpoint with ``query.term`` for
    full-text search. Pass ``client`` to reuse a connection (and to make calls
    mockable in tests); otherwise a temporary client is used.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors so callers can
    distinguish "server down" from "no results".
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            _BASE,
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params={
                "query.term": query,
                "pageSize": max_results,
                "format": "json",
            },
            client=client,
        )
        resp.raise_for_status()
        return _parse_studies(resp.json())
    finally:
        if owns_client:
            client.close()
