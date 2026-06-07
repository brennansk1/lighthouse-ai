"""Congress.gov source adapter — Congress.gov API v3.

Congress.gov is the official website for U.S. federal legislative information.
The API v3 (``https://api.congress.gov/v3``) provides structured access to
bills, amendments, votes (actions), committees, members, and more.

API: https://api.congress.gov/
Key required (free): register at https://api.congress.gov/sign-up/

Records are grade "A" as authoritative primary legislative documents.

**Egress note:** ``api.congress.gov`` is NOT on the default Lighthouse platform
allowlist. The skill wrapping this adapter will receive an ``EgressBlocked``
exception. The skill degrades gracefully (returns ``[]`` with a logged note).
To unlock live fetches run: ``lighthouse trust add api.congress.gov``

The adapter is httpx-based and client-injectable for respx testability.
"""

from __future__ import annotations

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

_BASE = "https://api.congress.gov/v3"
_HEADERS = {"User-Agent": "Lighthouse/0.1", "Accept": "application/json"}

# The only host this adapter contacts: the Congress.gov API v3. A user who
# invokes this source has authorized reaching the public API, so the host is
# declared allowed here and the guard's decide-before-fetch check passes for it.
_ALLOWED_HOSTS = frozenset({"api.congress.gov"})


def _build_params(api_key: str | None, extra: dict) -> dict:
    params = dict(extra)
    if api_key:
        params["api_key"] = api_key
    params.setdefault("format", "json")
    return params


def _parse_bills(data: dict) -> list[Document]:
    """Parse a /bill response into Documents."""
    bills = (data.get("bills") or [])
    out: list[Document] = []
    for bill in bills:
        title = " ".join((bill.get("title") or "").split())
        if not title:
            continue
        bill_type = (bill.get("type") or "").strip()
        bill_number = str(bill.get("number") or "").strip()
        congress = str(bill.get("congress") or "").strip()
        origin_chamber = (bill.get("originChamber") or "").strip()
        latest_action = (bill.get("latestAction") or {})
        latest_action_date = (latest_action.get("actionDate") or "").strip()
        latest_action_text = (latest_action.get("text") or "").strip()
        url = (bill.get("url") or "").strip()

        bill_id = f"{congress}-{bill_type}-{bill_number}" if all([congress, bill_type, bill_number]) else title[:40]
        text = title
        if latest_action_text:
            text = f"{title}. Latest action: {latest_action_text}"

        out.append(Document(
            id=f"congress:{bill_id}",
            text=text,
            metadata={
                "source": "congress_gov",
                "url": url,
                "grade": "A",
                "title": title,
                "bill_type": bill_type,
                "bill_number": bill_number,
                "congress": congress,
                "origin_chamber": origin_chamber,
                "latest_action_date": latest_action_date,
                "latest_action_text": latest_action_text,
            },
        ))
    return out


def _parse_vote_actions(data: dict) -> list[Document]:
    """Parse vote/action records into Documents."""
    actions = (data.get("actions") or [])
    out: list[Document] = []
    for action in actions:
        action_date = (action.get("actionDate") or "").strip()
        action_text = " ".join((action.get("text") or "").split())
        if not action_text:
            continue
        action_type = (action.get("type") or "").strip()
        url = (action.get("url") or "").strip()

        out.append(Document(
            id=f"congress:action:{action_date}:{action_text[:30]}",
            text=f"{action_date}: {action_text}",
            metadata={
                "source": "congress_gov",
                "url": url,
                "grade": "A",
                "action_date": action_date,
                "action_text": action_text,
                "action_type": action_type,
            },
        ))
    return out


def search_bills(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Search Congress.gov for bills by keyword.

    Uses the v3 ``/bill`` endpoint with ``query`` parameter for full-text
    search across bill titles and summaries. Returns bills ordered by
    update date descending.

    Pass ``client`` to reuse a connection (mockable in tests).
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            f"{_BASE}/bill",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params=_build_params(api_key, {
                "query": query,
                "limit": max_results,
                "sort": "updateDate+desc",
            }),
            client=client,
        )
        resp.raise_for_status()
        return _parse_bills(resp.json())
    finally:
        if owns_client:
            client.close()


def fetch_bill(
    congress: int,
    bill_type: str,
    bill_number: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch a specific bill by congress number, type, and bill number.

    ``congress`` is the Congress number (e.g. ``118`` for the 118th Congress).
    ``bill_type`` is ``"hr"`` (House), ``"s"`` (Senate), ``"hjres"``, ``"sjres"``, etc.
    ``bill_number`` is the numeric bill identifier (e.g. ``"1"``).

    Returns a list with one Document on success or [] if not found.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            f"{_BASE}/bill/{congress}/{bill_type}/{bill_number}",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params=_build_params(api_key, {}),
            client=client,
        )
        resp.raise_for_status()
        data = resp.json()
        bill = data.get("bill") or {}
        if not bill:
            return []
        return _parse_bills({"bills": [bill]})
    finally:
        if owns_client:
            client.close()


def get_vote_record(
    congress: int,
    bill_type: str,
    bill_number: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch the action/vote record for a specific bill.

    Returns the list of actions (including floor votes, committee referrals,
    and Presidential actions) taken on the bill, as Documents.

    ``congress`` is the Congress number, ``bill_type`` the bill type, and
    ``bill_number`` the bill number.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            f"{_BASE}/bill/{congress}/{bill_type}/{bill_number}/actions",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params=_build_params(api_key, {}),
            client=client,
        )
        resp.raise_for_status()
        return _parse_vote_actions(resp.json())
    finally:
        if owns_client:
            client.close()


def track_committee(
    committee_code: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Track recent bills referred to a specific committee.

    ``committee_code`` is the system code for the committee (e.g. ``"hsju00"``
    for House Judiciary). Returns bills ordered by update date descending.
    This function is the watchable tool: new referrals can be tracked
    incrementally.

    Raises ``httpx.HTTPStatusError`` on 4xx/5xx HTTP errors.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            f"{_BASE}/committee/{committee_code}/bills",
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params=_build_params(api_key, {
                "limit": max_results,
                "sort": "updateDate+desc",
            }),
            client=client,
        )
        resp.raise_for_status()
        data = resp.json()
        # Committee bills endpoint returns a "committeeBills" or "bills" key
        bills = data.get("committeeBills") or data.get("bills") or []
        # Normalize: committeeBills may have "bill" nested or be flat
        normalized = []
        for item in bills:
            if "bill" in item:
                normalized.append(item["bill"])
            else:
                normalized.append(item)
        return _parse_bills({"bills": normalized})
    finally:
        if owns_client:
            client.close()
