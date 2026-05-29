"""FRED (St. Louis Fed) source adapter — FRED API.

The Federal Reserve Bank of St. Louis FRED API provides access to hundreds of
thousands of economic time series from scores of national, international,
public, and private sources. The base URL is ``https://api.stlouisfed.org/fred``.

Key endpoints used here:
  * ``/series/search`` — search for series matching a query string
  * ``/series/observations`` — fetch time-series observations for a series ID
  * ``/releases`` — list data releases (watchable)
  * ``/series/vintagedates`` — list vintage dates for point-in-time revision data
  * ``/series/categories`` — get category hierarchy for a series

**Auth:** A free API key is required. Register at https://fred.stlouisfed.org/docs/api/api_key.html.
Pass via ``api_key`` parameter or the ``FRED_API_KEY`` environment variable.

**Egress note:** ``api.stlouisfed.org`` must be on the Lighthouse platform
allowlist. The skill wrapping this adapter degrades gracefully on EgressBlocked.
Run ``lighthouse trust add api.stlouisfed.org`` to enable live fetches.

The adapter is httpx-based and client-injectable for respx testability.
"""

from __future__ import annotations

import os

import httpx

from ..rag.chunker import Document

_BASE = "https://api.stlouisfed.org/fred"
_HEADERS = {"User-Agent": "Lighthouse/0.1", "Accept": "application/json"}


def _api_key(api_key: str | None) -> str:
    """Resolve API key from argument or environment variable."""
    key = api_key or os.environ.get("FRED_API_KEY", "")
    return key


def _parse_series_search(data: dict) -> list[Document]:
    """Parse /series/search JSON into Documents."""
    seriess = data.get("seriess") or []
    out: list[Document] = []
    for s in seriess:
        series_id = (s.get("id") or "").strip()
        title = " ".join((s.get("title") or "").split())
        if not title:
            continue
        notes = " ".join((s.get("notes") or "").split())
        frequency = (s.get("frequency") or "").strip()
        units = (s.get("units") or "").strip()
        seasonal_adjustment = (s.get("seasonal_adjustment") or "").strip()
        observation_start = (s.get("observation_start") or "").strip()
        observation_end = (s.get("observation_end") or "").strip()
        url = f"https://fred.stlouisfed.org/series/{series_id}" if series_id else ""

        text = title
        if notes:
            text = f"{title}. {notes[:300]}"

        out.append(Document(
            id=f"fred:{series_id}" if series_id else f"fred:{title[:40]}",
            text=text,
            metadata={
                "source": "fred",
                "url": url,
                "grade": "A",
                "title": title,
                "series_id": series_id,
                "frequency": frequency,
                "units": units,
                "seasonal_adjustment": seasonal_adjustment,
                "observation_start": observation_start,
                "observation_end": observation_end,
            },
        ))
    return out


def _parse_observations(data: dict, series_id: str) -> list[Document]:
    """Parse /series/observations JSON into a single Document."""
    observations = data.get("observations") or []
    if not observations:
        return []
    # Build a concise text representation: last 10 observations
    recent = observations[-10:]
    obs_text = "; ".join(
        f"{o.get('date', '')}: {o.get('value', '')}" for o in recent
    )
    title = f"FRED {series_id} observations"
    text = f"{title}. Recent values — {obs_text}"
    url = f"https://fred.stlouisfed.org/series/{series_id}"
    return [Document(
        id=f"fred:{series_id}:observations",
        text=text,
        metadata={
            "source": "fred",
            "url": url,
            "grade": "A",
            "title": title,
            "series_id": series_id,
            "observation_count": len(observations),
            "observation_start": observations[0].get("date", "") if observations else "",
            "observation_end": observations[-1].get("date", "") if observations else "",
        },
    )]


def _parse_releases(data: dict) -> list[Document]:
    """Parse /releases JSON into Documents."""
    releases = data.get("releases") or []
    out: list[Document] = []
    for r in releases:
        release_id = str(r.get("id") or "").strip()
        name = " ".join((r.get("name") or "").split())
        if not name:
            continue
        press_release = r.get("press_release", False)
        link = (r.get("link") or "").strip()
        url = link or f"https://fred.stlouisfed.org/release?release_id={release_id}"
        out.append(Document(
            id=f"fred:release:{release_id}" if release_id else f"fred:release:{name[:40]}",
            text=name,
            metadata={
                "source": "fred",
                "url": url,
                "grade": "A",
                "title": name,
                "release_id": release_id,
                "press_release": press_release,
            },
        ))
    return out


def search_series(
    query: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Search FRED for series matching ``query``; returns up to ``max_results`` Documents.

    Uses ``/series/search`` with ``search_text`` parameter. Pass ``client``
    for respx testability. Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    key = _api_key(api_key)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/series/search",
            headers=_HEADERS,
            params={
                "search_text": query,
                "limit": max_results,
                "file_type": "json",
                "api_key": key,
            },
        )
        resp.raise_for_status()
        return _parse_series_search(resp.json())
    finally:
        if owns_client:
            client.close()


def fetch_series(
    series_id: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch time-series observations for a FRED series ID.

    Returns a single Document containing the most recent observations as text.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    key = _api_key(api_key)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/series/observations",
            headers=_HEADERS,
            params={
                "series_id": series_id,
                "file_type": "json",
                "api_key": key,
            },
        )
        resp.raise_for_status()
        return _parse_observations(resp.json(), series_id)
    finally:
        if owns_client:
            client.close()


def list_releases(
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """List FRED data releases (watchable).

    Returns up to ``max_results`` release Documents. Raises
    ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    key = _api_key(api_key)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/releases",
            headers=_HEADERS,
            params={
                "limit": max_results,
                "file_type": "json",
                "api_key": key,
            },
        )
        resp.raise_for_status()
        docs = _parse_releases(resp.json())
        return docs[:max_results]
    finally:
        if owns_client:
            client.close()


def get_revisions(
    series_id: str,
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Get vintage dates (revision history) for a FRED series.

    Each vintage date represents a data revision. Returns Documents with
    revision metadata for point-in-time analysis. Raises
    ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    key = _api_key(api_key)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        resp = client.get(
            f"{_BASE}/series/vintagedates",
            headers=_HEADERS,
            params={
                "series_id": series_id,
                "file_type": "json",
                "api_key": key,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        vintage_dates = data.get("vintage_dates") or []
        if not vintage_dates:
            return []
        # Return up to max_results most recent vintage dates as a single summary doc
        recent_vintages = vintage_dates[-max_results:]
        text = (
            f"FRED {series_id} revision history. "
            f"Vintage dates (most recent): {', '.join(recent_vintages)}"
        )
        url = f"https://fred.stlouisfed.org/series/{series_id}"
        return [Document(
            id=f"fred:{series_id}:revisions",
            text=text,
            metadata={
                "source": "fred",
                "url": url,
                "grade": "A",
                "title": f"FRED {series_id} revision history",
                "series_id": series_id,
                "vintage_count": len(vintage_dates),
                "latest_vintage": vintage_dates[-1] if vintage_dates else "",
                "earliest_vintage": vintage_dates[0] if vintage_dates else "",
            },
        )]
    finally:
        if owns_client:
            client.close()


def compare_series(
    series_ids: list[str],
    *,
    max_results: int = 5,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    api_key: str | None = None,
) -> list[Document]:
    """Fetch metadata for multiple series for comparison.

    Returns one Document per series ID with metadata from ``/series``.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx.
    """
    key = _api_key(api_key)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        docs: list[Document] = []
        for series_id in series_ids[:max_results]:
            resp = client.get(
                f"{_BASE}/series",
                headers=_HEADERS,
                params={
                    "series_id": series_id,
                    "file_type": "json",
                    "api_key": key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            seriess = data.get("seriess") or []
            for s in seriess:
                sid = (s.get("id") or "").strip()
                title = " ".join((s.get("title") or "").split())
                if not title:
                    continue
                units = (s.get("units") or "").strip()
                frequency = (s.get("frequency") or "").strip()
                obs_end = (s.get("observation_end") or "").strip()
                url = f"https://fred.stlouisfed.org/series/{sid}"
                text = f"{title} ({units}, {frequency}, through {obs_end})"
                docs.append(Document(
                    id=f"fred:{sid}",
                    text=text,
                    metadata={
                        "source": "fred",
                        "url": url,
                        "grade": "A",
                        "title": title,
                        "series_id": sid,
                        "units": units,
                        "frequency": frequency,
                        "observation_end": obs_end,
                    },
                ))
        return docs
    finally:
        if owns_client:
            client.close()
