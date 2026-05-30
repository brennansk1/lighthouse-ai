"""OECD source adapter — OECD SDMX JSON API.

The OECD provides comparative cross-country economic and social indicators via
a SDMX-JSON REST API. The primary base URL is
``https://sdmx.oecd.org/public/rest``.

Key endpoints:
  * ``/dataflow/OECD.SDD.NAD`` — list available datasets (dataflows)
  * ``/data/{dataflow}/{key}`` — fetch dataset observations

OECD dataset IDs follow the pattern ``{AGENCY}.{COLLECTION}``, e.g.:
  * ``OECD.SDD.NAD,DSD_NAMAIN1@DF_TABLE1_EXPENDITURE`` — GDP by expenditure
  * ``OECD.SDD.TPS,DSD_LFS@DF_IALFS_INDIC`` — labour force statistics

**Auth:** None required for the SDMX public API.

**Egress note:** ``sdmx.oecd.org`` must be on the Lighthouse platform allowlist.
Run ``lighthouse trust add sdmx.oecd.org`` to enable live fetches.

The adapter is httpx-based and client-injectable for respx testability.
"""

from __future__ import annotations

import httpx

from ..rag.chunker import Document

_BASE = "https://sdmx.oecd.org/public/rest"
_HEADERS = {
    "User-Agent": "Lighthouse/0.1",
    "Accept": "application/vnd.sdmx.data+json;version=1.0",
}

# Curated OECD dataset catalog for search
_DATASET_CATALOG = [
    ("OECD.SDD.NAD,DSD_NAMAIN1@DF_TABLE1_EXPENDITURE,1.0", "GDP by Expenditure — National Accounts", "gdp,expenditure,national accounts,economy"),
    ("OECD.SDD.TPS,DSD_LFS@DF_IALFS_INDIC,1.0", "Labour Force Statistics — Employment and Unemployment", "employment,unemployment,labour,labor,jobs"),
    ("OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0", "Consumer and Producer Prices", "cpi,inflation,prices,consumer"),
    ("OECD.SDD.NAD,DSD_NAMAIN1@DF_TABLE14A,1.0", "Productivity and ULC — National Accounts", "productivity,unit labour cost,ulc"),
    ("OECD.WISE,DSD_BLI@BLI,3.0", "Better Life Index — Well-being Indicators", "well-being,wellbeing,better life,happiness"),
    ("OECD.SDD.TPS,DSD_HEALTH_PROC@DF_HEALTH_PROC,1.0", "Health at a Glance — Health Expenditure", "health,expenditure,hospital"),
    ("OECD.EDU,DSD_EAG_UOE@DF_UOE_ENRL_PART_RATIO,1.0", "Education at a Glance — Enrolment", "education,enrolment,school,university"),
    ("OECD.SDD.TPS,DSD_TAX_STRUCTURES@DF_TABLE_I2_1,1.0", "Revenue Statistics — Tax Structures", "tax,revenue,taxation,fiscal"),
    ("OECD.SDD.NAD,DSD_NAMAIN1@DF_TABLE2,1.0", "Population and GDP per Capita", "population,gdp per capita,income"),
    ("OECD.SDD.TPS,DSD_POVERTY@DF_POVERTY,1.0", "Income Distribution and Poverty", "poverty,inequality,gini,distribution"),
]


def _parse_sdmx_data(data: dict, dataset_id: str) -> list[Document]:
    """Parse OECD SDMX-JSON response into Documents."""
    # SDMX-JSON structure: data.dataSets[0].series → dict of series keys
    try:
        datasets = data.get("data", {}).get("dataSets") or []
        structure = data.get("data", {}).get("structure") or {}
        dimensions = structure.get("dimensions", {}).get("series") or []
        obs_dims = structure.get("dimensions", {}).get("observation") or []
    except (AttributeError, TypeError):
        return []

    if not datasets:
        return []

    dataset = datasets[0]
    series_data = dataset.get("series") or {}

    # Build dimension labels for readable output
    dim_labels: list[list[str]] = []
    for dim in dimensions:
        values = dim.get("values") or []
        dim_labels.append([v.get("name", str(i)) for i, v in enumerate(values)])

    # Time labels from observation dimension
    time_labels: list[str] = []
    for dim in obs_dims:
        if dim.get("id", "").upper() in ("TIME_PERIOD", "TIME"):
            time_labels = [v.get("id", str(i)) for i, v in enumerate(dim.get("values") or [])]
            break

    out: list[Document] = []
    for key_str, series_obj in list(series_data.items())[:5]:
        key_parts = key_str.split(":")
        # Build a label from dimension values
        label_parts = []
        for i, part in enumerate(key_parts):
            try:
                idx = int(part)
                if i < len(dim_labels) and idx < len(dim_labels[i]):
                    label_parts.append(dim_labels[i][idx])
            except (ValueError, IndexError):
                label_parts.append(part)
        label = " — ".join(label_parts) if label_parts else key_str

        observations = series_obj.get("observations") or {}

        def _obs_index(obs_key: str) -> int:
            # SDMX observation keys are usually a single integer ("0") but can be
            # multi-dimensional ("0:1") when several observation dimensions are
            # present. Use the first numeric component as the time index; fall
            # back to a large sentinel so unparseable keys sort last instead of
            # raising ValueError.
            head = obs_key.split(":", 1)[0]
            try:
                return int(head)
            except (ValueError, TypeError):
                return 10 ** 9

        obs_list = []
        for obs_key, obs_val in sorted(observations.items(), key=lambda x: _obs_index(x[0]))[-8:]:
            idx = _obs_index(obs_key)
            time = (
                time_labels[idx]
                if time_labels and 0 <= idx < len(time_labels)
                else obs_key
            )
            value = obs_val[0] if isinstance(obs_val, list) else obs_val
            obs_list.append(f"{time}: {value}")

        text = f"OECD {dataset_id} — {label}: {'; '.join(obs_list)}"
        out.append(Document(
            id=f"oecd:{dataset_id}:{key_str[:40]}",
            text=text,
            metadata={
                "source": "oecd",
                "url": "https://data.oecd.org/",
                "grade": "A",
                "title": f"OECD {dataset_id} — {label}",
                "dataset_id": dataset_id,
                "series_key": key_str,
            },
        ))
    return out


def search_dataset(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Search the curated OECD dataset catalog matching ``query``.

    Performs client-side filtering on dataset name and tags. Returns up to
    ``max_results`` Documents. Never raises on empty match.
    ``api_key`` and ``client`` are accepted for interface consistency.
    """
    q = query.lower()
    out: list[Document] = []
    for dataset_id, name, tags in _DATASET_CATALOG:
        combined = f"{name} {tags}".lower()
        if not q or any(w in combined for w in q.split()):
            url = "https://data.oecd.org/"
            out.append(Document(
                id=f"oecd:dataset:{dataset_id[:40]}",
                text=name,
                metadata={
                    "source": "oecd",
                    "url": url,
                    "grade": "A",
                    "title": name,
                    "dataset_id": dataset_id,
                },
            ))
        if len(out) >= max_results:
            break
    return out


def fetch_dataset(
    dataset_id: str,
    *,
    filter_expression: str = "all",
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch OECD dataset observations via SDMX-JSON.

    ``dataset_id`` is the full dataflow ID (e.g.
    ``'OECD.SDD.NAD,DSD_NAMAIN1@DF_TABLE1_EXPENDITURE,1.0'``).
    ``filter_expression`` is appended to narrow the request (e.g. ``'USA..'``).
    Returns Documents with time-series observations.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        url = f"{_BASE}/data/{dataset_id}/{filter_expression}"
        resp = client.get(
            url,
            headers=_HEADERS,
            params={"dimensionAtObservation": "TIME_PERIOD", "startPeriod": "2015"},
        )
        resp.raise_for_status()
        return _parse_sdmx_data(resp.json(), dataset_id)
    finally:
        if owns_client:
            client.close()


def compare_countries(
    dataset_id: str,
    country_codes: list[str],
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch an OECD dataset filtered to specific countries for comparison.

    ``country_codes`` should be ISO 3166-1 alpha-3 codes (e.g. ``['USA', 'DEU']``).
    Returns Documents with per-country observations.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    # Build SDMX filter: first dimension is typically country
    filter_expr = "+".join(country_codes) + ".."
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        docs = fetch_dataset(
            dataset_id,
            filter_expression=filter_expr,
            max_results=max_results,
            client=client,
            timeout=timeout,
        )
        return docs[:max_results]
    finally:
        if owns_client:
            client.close()


def list_recent_releases(
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """List recently updated OECD datasets from the curated catalog.

    Returns curated dataset stubs. Does not require network access (catalog
    is local). For live availability status, use ``fetch_dataset``.
    """
    out = []
    for dataset_id, name, _tags in _DATASET_CATALOG[:max_results]:
        out.append(Document(
            id=f"oecd:dataset:{dataset_id[:40]}",
            text=name,
            metadata={
                "source": "oecd",
                "url": "https://data.oecd.org/",
                "grade": "A",
                "title": name,
                "dataset_id": dataset_id,
            },
        ))
    return out
