"""News Orchestrator meta-skill — cross-outlet news aggregation with bias overlay.

This skill orchestrates the six first-party news outlet skills (Reuters, AP,
BBC News, NPR, The Guardian, ProPublica) via ``sources/news.py`` directly,
maintaining its own OUTLETS table so it never calls run_skill() from inside
a skill (which would be heavy) — instead it drives the shared RSS/feed adapter
with the same ``ctx`` passed to it by the runner.

Bias overlay: every returned Document is tagged with the outlet's AllSides
media-bias rating in ``metadata["allsides_rating"]`` so Adjudicate mode can
weight perspective diversity without a separate lookup.

Security invariants:
  - No httpx / requests / urllib / socket / subprocess / asyncio imports.
  - All I/O goes through ctx.fetch (passed as ``client`` to sources/news.py).
  - EgressBlocked for any single outlet is caught per-outlet; remaining
    outlets continue normally (graceful partial degradation).
  - No datetime.now() at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from lighthouse_ai.sources import news as _news

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext


# ---------------------------------------------------------------------------
# Outlets table — id, AllSides bias rating, primary RSS feeds
# ---------------------------------------------------------------------------

@dataclass
class _OutletSpec:
    """Static descriptor for one trusted news outlet."""

    id: str
    name: str
    allsides_rating: str          # e.g. "center", "lean_left", "left"
    feeds: list[str]              # default / primary feed URLs (in priority order)
    enabled: bool = True          # set False via validate_outlet_access on hard failures


# Feed URLs match the per-outlet skills' _TOPIC_FEEDS / _DEFAULT_FEED constants.
_TRUSTED_OUTLETS: list[_OutletSpec] = [
    _OutletSpec(
        id="reuters",
        name="Reuters",
        allsides_rating="center",
        feeds=["https://feeds.reuters.com/reuters/topNews"],
    ),
    _OutletSpec(
        id="associated_press",
        name="Associated Press",
        allsides_rating="center",
        feeds=["https://apnews.com/hub/ap-top-news?format=rss"],
    ),
    _OutletSpec(
        id="bbc_news",
        name="BBC News",
        allsides_rating="lean_left",
        feeds=["https://feeds.bbci.co.uk/news/world/rss.xml"],
    ),
    _OutletSpec(
        id="npr",
        name="NPR",
        allsides_rating="lean_left",
        feeds=["https://feeds.npr.org/1001/rss.xml"],
    ),
    _OutletSpec(
        id="guardian",
        name="The Guardian",
        allsides_rating="left",
        feeds=["https://www.theguardian.com/world/rss"],
    ),
    _OutletSpec(
        id="propublica",
        name="ProPublica",
        allsides_rating="lean_left",
        feeds=["https://www.propublica.org/feeds/propublica/main"],
    ),
]

# Ephemeral user-registered outlets (in-process only; not persisted).
_custom_outlets: list[_OutletSpec] = []


def _all_outlets(outlet_ids: list[str] | None) -> list[_OutletSpec]:
    """Return the full list of enabled outlets, optionally filtered by id."""
    combined = _TRUSTED_OUTLETS + _custom_outlets
    if outlet_ids is None:
        return [o for o in combined if o.enabled]
    lower = {oid.lower() for oid in outlet_ids}
    return [o for o in combined if o.id in lower and o.enabled]


# ---------------------------------------------------------------------------
# Internal fetch helper — fetch + filter for a single outlet
# ---------------------------------------------------------------------------

def _fetch_outlet(
    ctx: SkillContext,
    outlet: _OutletSpec,
    query: str,
    *,
    max_results: int,
    since: datetime | None = None,
) -> list[Document]:
    """Fetch the primary feed for ``outlet``, filter by query terms, return Documents.

    EgressBlocked and all other exceptions are caught here; returns [] so that
    the calling aggregator can skip this outlet and continue.
    """
    terms = [t for t in query.lower().split() if len(t) > 2]
    items: list = []

    for feed_url in outlet.feeds:
        try:
            raw = _news.fetch_outlet_feed(
                feed_url, client=ctx.fetch, max_results=max_results * 3
            )
        except _news.EgressBlocked:
            return []
        except Exception:
            continue

        for item in raw:
            text = ((item.title or "") + " " + (item.body or "")).lower()
            if not terms or any(t in text for t in terms):
                items.append(item)
            if len(items) >= max_results:
                break
        if len(items) >= max_results:
            break

    if since is not None:
        items = _news.filter_since(items, since)

    docs = _news.items_to_documents(ctx, items[:max_results], outlet_id=outlet.id)
    # Attach bias overlay to every document
    for doc in docs:
        doc.metadata["allsides_rating"] = outlet.allsides_rating
        doc.metadata["outlet_name"] = outlet.name
    return docs


# ---------------------------------------------------------------------------
# Named tools
# ---------------------------------------------------------------------------


def search_news(
    ctx: SkillContext,
    query: str,
    *,
    outlets: list[str] | None = None,
    max_results: int = 5,
) -> list[Document]:
    """Fan-out ``query`` across all trusted news outlets and return aggregated Documents.

    Each Document is tagged with ``metadata["allsides_rating"]`` and
    ``metadata["outlet"]`` so callers can distinguish provenance.

    Parameters
    ----------
    ctx:
        Skill capability context — all fetches go through ``ctx.fetch``.
    query:
        The search query / headline keywords.
    outlets:
        Optional list of outlet ids to restrict the fan-out.  ``None`` uses
        all six default trusted outlets plus any user-registered outlets.
    max_results:
        Maximum documents to return *per outlet*.  The aggregate result may
        contain up to ``max_results * len(outlets)`` documents.

    Returns
    -------
    list[Document]
        Aggregated Documents sorted by outlet order, each carrying bias tags.
        Outlets that raise EgressBlocked or network errors are silently skipped.
    """
    all_docs: list[Document] = []
    for outlet in _all_outlets(outlets):
        try:
            docs = _fetch_outlet(ctx, outlet, query, max_results=max_results)
        except _news.EgressBlocked:
            continue
        except Exception:
            continue
        all_docs.extend(docs)
    return all_docs


def compare_coverage(
    ctx: SkillContext,
    query: str,
    *,
    outlets: list[str] | None = None,
) -> dict[str, object]:
    """Run the same query across N outlets and return a side-by-side structure.

    Returns a dict with two keys:

    - ``"outlets"``: ``list[dict]`` — one entry per outlet, each containing
      ``outlet_id``, ``outlet_name``, ``allsides_rating``, and ``documents``
      (list[Document]).
    - ``"bias_overlay"``: the AllSides rating map from :func:`get_bias_overlay`.

    Outlets that fail (EgressBlocked / network) appear in the result with an
    empty ``documents`` list so the caller knows they were attempted.

    Parameters
    ----------
    ctx:
        Skill capability context.
    query:
        The query / topic to compare across outlets.
    outlets:
        Optional list of outlet ids.  ``None`` uses all trusted outlets.
    """
    bias_map = get_bias_overlay()
    result_outlets: list[dict] = []

    for outlet in _all_outlets(outlets):
        try:
            docs = _fetch_outlet(ctx, outlet, query, max_results=5)
        except Exception:
            docs = []
        result_outlets.append({
            "outlet_id": outlet.id,
            "outlet_name": outlet.name,
            "allsides_rating": outlet.allsides_rating,
            "documents": docs,
        })

    return {
        "outlets": result_outlets,
        "bias_overlay": bias_map,
    }


def register_custom_outlet(
    feed_url: str,
    outlet_id: str,
    outlet_name: str,
    allsides_rating: str = "unknown",
) -> dict[str, str]:
    """Register a user-supplied RSS feed as an ephemeral additional outlet.

    The outlet is added to the in-process ``_custom_outlets`` list and will be
    included in subsequent ``search_news`` / ``compare_coverage`` calls within
    this process lifetime.  It is NOT persisted to disk.

    Parameters
    ----------
    feed_url:
        Full URL of the RSS / Atom feed to register.
    outlet_id:
        A short, unique identifier (must be a valid Python identifier-ish slug).
    outlet_name:
        Human-readable outlet name.
    allsides_rating:
        The user-supplied AllSides / bias rating for this outlet.  Defaults to
        ``"unknown"`` when unrated.

    Returns
    -------
    dict
        ``{"status": "registered", "outlet_id": outlet_id, ...}``
    """
    # Deduplicate by id — replace if already registered.
    global _custom_outlets
    _custom_outlets = [o for o in _custom_outlets if o.id != outlet_id]
    _custom_outlets.append(
        _OutletSpec(
            id=outlet_id,
            name=outlet_name,
            allsides_rating=allsides_rating,
            feeds=[feed_url],
        )
    )
    return {
        "status": "registered",
        "outlet_id": outlet_id,
        "outlet_name": outlet_name,
        "feed_url": feed_url,
        "allsides_rating": allsides_rating,
    }


def validate_outlet_access(
    ctx: SkillContext,
    outlet_id: str | None = None,
) -> list[dict[str, object]]:
    """Best-effort reachability check for one or all outlets.

    Attempts to fetch the first feed URL for each target outlet with a
    small ``max_results=1`` cap.  Returns a list of status dicts, one per
    outlet, each with ``outlet_id``, ``reachable`` (bool), and ``error``
    (str | None).

    Parameters
    ----------
    ctx:
        Skill capability context.
    outlet_id:
        If given, only check that outlet.  ``None`` checks all outlets.
    """
    targets = _all_outlets([outlet_id] if outlet_id else None)
    results: list[dict[str, object]] = []
    for outlet in targets:
        if not outlet.feeds:
            results.append({"outlet_id": outlet.id, "reachable": False, "error": "no feeds configured"})
            continue
        feed_url = outlet.feeds[0]
        try:
            _news.fetch_outlet_feed(feed_url, client=ctx.fetch, max_results=1)
            results.append({"outlet_id": outlet.id, "reachable": True, "error": None})
        except _news.EgressBlocked as exc:
            results.append({"outlet_id": outlet.id, "reachable": False, "error": f"EgressBlocked: {exc}"})
        except Exception as exc:
            results.append({"outlet_id": outlet.id, "reachable": False, "error": str(exc)})
    return results


def get_bias_overlay() -> dict[str, str]:
    """Return the AllSides media-bias rating map for all registered outlets.

    Returns
    -------
    dict[str, str]
        ``{outlet_id: allsides_rating}`` for every trusted and custom outlet.
        Ratings: ``"left"``, ``"lean_left"``, ``"center"``, ``"lean_right"``,
        ``"right"``, ``"unknown"``.
    """
    overlay: dict[str, str] = {}
    for outlet in _TRUSTED_OUTLETS + _custom_outlets:
        overlay[outlet.id] = outlet.allsides_rating
    return overlay


# ---------------------------------------------------------------------------
# Entrypoints (SKILL_FRAMEWORK.md §2)
# ---------------------------------------------------------------------------


def run(
    ctx: SkillContext,
    question: str,
    *,
    max_results: int = 5,
) -> list[Document]:
    """Research a question across all six trusted news outlets.

    Calls :func:`search_news` with the default outlet set.  Degrades gracefully:
    outlets that raise EgressBlocked or any network error are skipped without
    failing the overall result.

    Parameters
    ----------
    ctx:
        Skill capability context.
    question:
        The research question / search query.
    max_results:
        Maximum results *per outlet*.
    """
    try:
        return search_news(ctx, question, outlets=None, max_results=max_results)
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
    """Watch all trusted outlets for articles published after ``since``.

    Runs a time-filtered fan-out: fetches each outlet's primary feed and
    applies :func:`~lighthouse_ai.sources.news.filter_since` so only items
    after the Watch tick boundary are returned.

    Parameters
    ----------
    ctx:
        Skill capability context.
    query:
        Keywords to filter the fetched feed items.
    since:
        Timestamp threshold; items at or before this time are excluded.
        ``None`` returns all available items.
    max_results:
        Maximum results per outlet.
    """
    all_docs: list[Document] = []
    for outlet in _all_outlets(None):
        try:
            docs = _fetch_outlet(ctx, outlet, query, max_results=max_results, since=since)
        except _news.EgressBlocked:
            continue
        except Exception:
            continue
        all_docs.extend(docs)
    return all_docs
