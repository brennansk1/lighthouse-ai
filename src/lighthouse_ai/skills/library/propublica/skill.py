"""ProPublica news skill — entrypoints run, run_watchable, and named tools.

Access method: ProPublica RSS + web search + open data repo API.
AllSides bias rating: Lean Left.

ProPublica open data APIs (free, no key for most):
  - Congress API: https://projects.propublica.org/api-docs/congress-api/
  - Campaign Finance: https://projects.propublica.org/api-docs/campaign-finance/
  - Nonprofit Explorer: https://projects.propublica.org/api-docs/nonprofit-explorer/

Security invariants:
  - No httpx / requests / urllib / socket / subprocess imports.
  - All I/O goes through ctx.fetch / ctx.fetch_and_document.
  - EgressBlocked is caught and returns [] gracefully.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from lighthouse_ai.modes.monitor import MonitorItem
from lighthouse_ai.sources import news as _news


def _urlencode(params: dict) -> str:
    """Minimal URL percent-encoding for simple ASCII key=value params."""
    pairs: list[str] = []
    for k, v in params.items():
        vs = str(v).replace(" ", "+").replace("&", "%26").replace("=", "%3D")
        pairs.append(f"{k}={vs}")
    return "&".join(pairs)


if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

_OUTLET_ID = "propublica"

# ProPublica main RSS feed
_FEED_URL = "https://feeds.propublica.org/propublica/main"

# Additional topic feeds
_TOPIC_FEEDS: dict[str, str] = {
    "top": "https://feeds.propublica.org/propublica/main",
    "main": "https://feeds.propublica.org/propublica/main",
    "politics": "https://feeds.propublica.org/propublica/main",
    "health": "https://feeds.propublica.org/propublica/main",
    "criminal_justice": "https://feeds.propublica.org/propublica/main",
    "environment": "https://feeds.propublica.org/propublica/main",
}
_DEFAULT_FEED = _FEED_URL
_SEARCH_BASE = "https://www.propublica.org/search"

# ProPublica open data endpoints (sampler — no API key required for basic use)
_DATA_ENDPOINTS: dict[str, str] = {
    "congress": "https://api.propublica.org/congress/v1",
    "campaign_finance": "https://api.propublica.org/campaign-finance/v1",
    "nonprofits": "https://projects.propublica.org/nonprofits/api/v2",
}


def _parse_propublica_search_json(payload: bytes) -> list[MonitorItem]:
    """Parse ProPublica search JSON response (if structured)."""
    try:
        data = json.loads(payload)
    except Exception:
        return []
    articles = data.get("results", data.get("articles", []))
    if not isinstance(articles, list):
        return []
    items: list[MonitorItem] = []
    for r in articles:
        title = r.get("title", "") or r.get("headline", "")
        url = r.get("url", "") or r.get("link", "")
        body = r.get("blurb", "") or r.get("description", "")
        pub = r.get("published_at", "") or r.get("date", "")
        if not url:
            continue
        items.append(
            MonitorItem(
                source=_OUTLET_ID,
                url=url,
                title=_news._strip_html(title),
                body=_news._strip_html(body),
                published_at=pub or None,
            )
        )
    return items


# ---------------------------------------------------------------------------
# Named tools
# ---------------------------------------------------------------------------


def search_articles(
    ctx: SkillContext,
    query: str,
    *,
    max_results: int = 10,
) -> list[Document]:
    """Search ProPublica articles via RSS feed and web search fallback."""
    items: list = []
    terms = [t for t in query.lower().split() if len(t) > 3]

    try:
        raw = _news.fetch_outlet_feed(_DEFAULT_FEED, client=ctx.fetch, max_results=max_results * 3)
        for item in raw:
            text = ((item.title or "") + " " + (item.body or "")).lower()
            if not terms or any(t in text for t in terms):
                items.append(item)
            if len(items) >= max_results:
                break
    except Exception:
        pass

    if len(items) < max_results // 2:
        try:
            web_items = _news.search_outlet(
                _SEARCH_BASE, query, client=ctx.fetch, max_results=max_results
            )
            items.extend(web_items[: max_results - len(items)])
        except Exception:
            pass

    return _news.items_to_documents(ctx, items[:max_results], outlet_id=_OUTLET_ID)


def fetch_article(
    ctx: SkillContext,
    url: str,
) -> list[Document]:
    """Fetch a single ProPublica article URL."""
    try:
        doc = ctx.fetch_and_document(url, extra_meta={"outlet": _OUTLET_ID, "type": "news_article"})
    except Exception:
        return []
    return [doc] if doc is not None else []


def search_data_repo(
    ctx: SkillContext,
    query: str,
    *,
    dataset: str = "nonprofits",
    max_results: int = 10,
) -> list[Document]:
    """Search the ProPublica open data repository.

    Provides access to ProPublica's structured datasets:
    - ``nonprofits`` — IRS 990 data for 1.8M+ nonprofits
    - ``congress`` — bills, votes, members (requires ProPublica API key)
    - ``campaign_finance`` — FEC filings (requires ProPublica API key)

    In v1, the nonprofit explorer is accessible without a key.

    Parameters
    ----------
    query:
        Search terms.
    dataset:
        One of: nonprofits, congress, campaign_finance.
    max_results:
        Maximum results to return.
    """
    if dataset == "nonprofits":
        url = (
            f"https://projects.propublica.org/nonprofits/api/v2/search.json"
            f"?{_urlencode({'q': query, 'page': '0'})}"
        )
        try:
            resp = ctx.fetch(url)
            if resp.status_code != 200:
                return []
            data = json.loads(resp.content)
            orgs = data.get("organizations", [])[:max_results]
            items = []
            for org in orgs:
                name = org.get("name", "")
                ntee = org.get("ntee_code", "")
                city = org.get("city", "")
                state = org.get("state", "")
                ein = org.get("ein", "")
                text = f"{name} (EIN: {ein}, {city}, {state}, NTEE: {ntee})"
                if not text.strip():
                    continue
                _np_id = ein if ein else f"{hash(name) & 0xFFFFFFFF:08x}"
                items.append(
                    ctx.make_document(
                        doc_id=f"propublica:nonprofit:{_np_id}",
                        text=text,
                        metadata={
                            "source": _OUTLET_ID,
                            "url": f"https://projects.propublica.org/nonprofits/organizations/{ein}",
                            "type": "open_data",
                            "dataset": "nonprofits",
                            "outlet": _OUTLET_ID,
                            "name": name,
                            "ein": ein,
                        },
                    )
                )
            return items
        except Exception:
            return []
    else:
        # Other datasets require API key — return empty list with graceful degradation
        return []


def list_recent_in_topic(
    ctx: SkillContext,
    topic: str,
    *,
    since: datetime | None = None,
    max_results: int = 10,
) -> list[Document]:
    """List recent ProPublica articles (watchable tool).

    ProPublica publishes to a single main feed; topic filtering is applied
    by matching keywords in the feed items.
    """
    feed_url = _TOPIC_FEEDS.get(topic.lower(), _DEFAULT_FEED)
    try:
        raw = _news.fetch_outlet_feed(feed_url, client=ctx.fetch, max_results=max_results * 3)
    except Exception:
        return []

    if since is not None:
        raw = _news.filter_since(raw, since)

    # Filter by topic keyword if not a generic topic
    if topic.lower() not in ("top", "main", "politics"):
        filtered = [
            item
            for item in raw
            if topic.lower() in ((item.title or "") + " " + (item.body or "")).lower()
        ]
        raw = filtered if filtered else raw

    return _news.items_to_documents(ctx, raw[:max_results], outlet_id=_OUTLET_ID, feed_url=feed_url)


# ---------------------------------------------------------------------------
# Entrypoints
# ---------------------------------------------------------------------------


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question using ProPublica journalism and open data."""
    try:
        return search_articles(ctx, question, max_results=max_results)
    except _news.EgressBlocked:
        return []
    except Exception:
        return []


def run_watchable(
    ctx: SkillContext,
    query: str,
    *,
    since: datetime | None = None,
    max_results: int = 5,
) -> list[Document]:
    """Watch ProPublica for new investigative reports published after ``since``."""
    try:
        return list_recent_in_topic(ctx, "top", since=since, max_results=max_results)
    except _news.EgressBlocked:
        return []
    except Exception:
        return []
