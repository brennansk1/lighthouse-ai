"""BEA (Bureau of Economic Analysis) source adapter — BEA API.

The U.S. Bureau of Economic Analysis provides data on GDP, national income,
personal income, international trade, and regional/industry accounts.
The API base URL is ``https://apps.bea.gov/api/data``.

Key datasets used here:
  * ``NIPA`` — National Income and Product Accounts (GDP, personal income, etc.)
  * ``Regional`` — regional economic data by state/metro area
  * ``GDPbyIndustry`` — industry-level GDP

**Auth:** A free API key is required. Register at https://apps.bea.gov/API/signup/.
Pass via ``api_key`` parameter or the ``BEA_API_KEY`` environment variable.

**Egress note:** ``apps.bea.gov`` must be on the Lighthouse platform allowlist.
Run ``lighthouse trust add apps.bea.gov`` to enable live fetches.

The adapter is httpx-based and client-injectable for respx testability.
"""

from __future__ import annotations

import os

import httpx

from ..net import guarded_get
from ..rag.chunker import Document

_BASE = "https://apps.bea.gov/api/data"
_HEADERS = {"User-Agent": "Lighthouse/0.1", "Accept": "application/json"}
_ALLOWED_HOSTS = frozenset({"apps.bea.gov"})


def _api_key(api_key: str | None) -> str:
    """Resolve API key from argument or environment variable."""
    return api_key or os.environ.get("BEA_API_KEY", "")


def _parse_dataset_list(data: dict, query: str) -> list[Document]:
    """Parse GetDataSetList response into Documents filtered by query."""
    result = data.get("BEAAPI", {}).get("Results", {})
    datasets = result.get("Dataset") or []
    query_lower = query.lower()
    out: list[Document] = []
    for ds in datasets:
        name = (ds.get("DatasetName") or "").strip()
        description = " ".join((ds.get("DatasetDescription") or "").split())
        if not name:
            continue
        # Client-side relevance filter
        combined = f"{name} {description}".lower()
        if query_lower and not any(w in combined for w in query_lower.split()):
            continue
        text = description if description else name
        url = f"https://apps.bea.gov/api/data/?&UserID=KEY&method=GetData&DataSetName={name}"
        out.append(
            Document(
                id=f"bea:dataset:{name}",
                text=text,
                metadata={
                    "source": "bea",
                    "url": url,
                    "grade": "A",
                    "title": description or name,
                    "dataset_name": name,
                },
            )
        )
    return out


def _parse_nipa_data(data: dict, table_name: str) -> list[Document]:
    """Parse NIPA GetData response into Documents."""
    result = data.get("BEAAPI", {}).get("Results", {})
    data_rows = result.get("Data") or []
    if not data_rows:
        return []

    # Group by LineDescription for concise summaries
    by_line: dict[str, list[str]] = {}
    for row in data_rows:
        line_desc = (row.get("LineDescription") or "").strip()
        time_period = (row.get("TimePeriod") or "").strip()
        data_value = (row.get("DataValue") or "").strip()
        if not line_desc or not data_value or data_value == "---":
            continue
        by_line.setdefault(line_desc, []).append(f"{time_period}: {data_value}")

    out: list[Document] = []
    for line_desc, values in list(by_line.items())[:5]:
        recent = values[-5:]
        text = f"BEA NIPA {table_name} — {line_desc}: {'; '.join(recent)}"
        out.append(
            Document(
                id=f"bea:nipa:{table_name}:{line_desc[:30]}",
                text=text,
                metadata={
                    "source": "bea",
                    "url": f"https://apps.bea.gov/iTable/?reqid=19&step=2&isuri=1&TableID={table_name}",
                    "grade": "A",
                    "title": f"BEA NIPA {table_name} — {line_desc}",
                    "dataset": "NIPA",
                    "table_name": table_name,
                    "line_description": line_desc,
                },
            )
        )
    return out


def search_dataset(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Search BEA dataset list for entries matching ``query``.

    Fetches the full dataset list and filters client-side. Returns up to
    ``max_results`` Documents. Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    key = _api_key(api_key)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            _BASE,
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params={
                "UserID": key,
                "method": "GetDataSetList",
                "ResultFormat": "JSON",
            },
            client=client,
        )
        resp.raise_for_status()
        docs = _parse_dataset_list(resp.json(), query)
        return docs[:max_results]
    finally:
        if owns_client:
            client.close()


def fetch_table(
    table_name: str,
    *,
    frequency: str = "A",
    year: str = "ALL",
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch a NIPA table by table name.

    ``frequency`` is ``'A'`` (annual), ``'Q'`` (quarterly), or ``'M'`` (monthly).
    ``year`` can be ``'ALL'`` or a comma-separated list of years (e.g. ``'2022,2023'``).
    Returns Documents with line-level observations. Raises ``httpx.HTTPStatusError`` on error.
    """
    key = _api_key(api_key)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            _BASE,
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params={
                "UserID": key,
                "method": "GetData",
                "DataSetName": "NIPA",
                "TableName": table_name,
                "Frequency": frequency,
                "Year": year,
                "ResultFormat": "JSON",
            },
            client=client,
        )
        resp.raise_for_status()
        docs = _parse_nipa_data(resp.json(), table_name)
        return docs[:max_results]
    finally:
        if owns_client:
            client.close()


def list_nipa_tables(
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """List available NIPA tables.

    Returns up to ``max_results`` Documents describing NIPA table names and
    their descriptions. Raises ``httpx.HTTPStatusError`` on error.
    """
    key = _api_key(api_key)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            _BASE,
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params={
                "UserID": key,
                "method": "GetParameterValuesFiltered",
                "DataSetName": "NIPA",
                "TargetParameter": "TableName",
                "ResultFormat": "JSON",
            },
            client=client,
        )
        resp.raise_for_status()
        result = resp.json().get("BEAAPI", {}).get("Results", {})
        param_values = result.get("ParamValue") or []
        out: list[Document] = []
        for pv in param_values[:max_results]:
            table_name = (pv.get("TableName") or pv.get("Key") or "").strip()
            description = " ".join((pv.get("Desc") or pv.get("Value") or "").split())
            if not table_name:
                continue
            text = (
                f"NIPA table {table_name}: {description}"
                if description
                else f"NIPA table {table_name}"
            )
            out.append(
                Document(
                    id=f"bea:nipa:table:{table_name}",
                    text=text,
                    metadata={
                        "source": "bea",
                        "url": f"https://apps.bea.gov/iTable/?reqid=19&step=2&isuri=1&TableID={table_name}",
                        "grade": "A",
                        "title": text,
                        "dataset": "NIPA",
                        "table_name": table_name,
                    },
                )
            )
        return out
    finally:
        if owns_client:
            client.close()


def get_industry_account(
    industry: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch GDP-by-industry data for a specific industry.

    ``industry`` is a BEA industry code (e.g. ``'ALL'`` for all industries).
    Returns Documents with value-added and output by industry.
    Raises ``httpx.HTTPStatusError`` on error.
    """
    key = _api_key(api_key)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = guarded_get(
            _BASE,
            allowed_domains=_ALLOWED_HOSTS,
            headers=_HEADERS,
            params={
                "UserID": key,
                "method": "GetData",
                "DataSetName": "GDPbyIndustry",
                "Frequency": "A",
                "Industry": industry,
                "TableID": "1",
                "Year": "ALL",
                "ResultFormat": "JSON",
            },
            client=client,
        )
        resp.raise_for_status()
        result = resp.json().get("BEAAPI", {}).get("Results", {})
        data_rows = result.get("Data") or []
        by_desc: dict[str, list[str]] = {}
        for row in data_rows:
            desc = (row.get("IndustrYDescription") or row.get("IndustryDescription") or "").strip()
            year = str(row.get("Year") or "").strip()
            val = str(row.get("DataValue") or "").strip()
            if desc and year and val and val != "---":
                by_desc.setdefault(desc, []).append(f"{year}: {val}")
        out: list[Document] = []
        for desc, vals in list(by_desc.items())[:max_results]:
            text = f"BEA GDP by industry — {desc}: {'; '.join(vals[-5:])}"
            out.append(
                Document(
                    id=f"bea:gdpbyindustry:{desc[:40]}",
                    text=text,
                    metadata={
                        "source": "bea",
                        "url": "https://apps.bea.gov/iTable/?reqid=52&step=2",
                        "grade": "A",
                        "title": f"GDP by Industry — {desc}",
                        "dataset": "GDPbyIndustry",
                        "industry": industry,
                    },
                )
            )
        return out
    finally:
        if owns_client:
            client.close()
