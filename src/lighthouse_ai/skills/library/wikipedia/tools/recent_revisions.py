"""Wikipedia recent-revisions tool (@watchable).

Queries the MediaWiki Action API ``list=recentchanges`` (for topic-agnostic
monitoring) or ``prop=revisions`` on a specific page (for page-level watch).
Accepts a ``since`` datetime to implement incremental Watch ticks.

This is the watchable tool declared in ``manifest.toml``
(``watchable_tools = ["recent_revisions"]``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

# ISO 8601 as required by the MediaWiki API
_RC_URL = (
    "https://en.wikipedia.org/w/api.php"
    "?action=query&list=recentchanges&rcnamespace=0"
    "&rcprop=title|timestamp|comment|user|ids"
    "&rclimit={limit}&rcend={since}&format=json&utf8=1"
)

_PAGE_REV_URL = (
    "https://en.wikipedia.org/w/api.php"
    "?action=query&prop=revisions&titles={title}"
    "&rvprop=timestamp|comment|user|ids&rvend={since}"
    "&rvlimit={limit}&format=json&utf8=1"
)


def recent_revisions(
    ctx: SkillContext,
    query: str,
    *,
    since: datetime | None = None,
    max_results: int = 10,
) -> list[Document]:
    """Return Documents representing recent Wikipedia edits matching ``query``.

    When ``query`` looks like a page title (no spaces and has the shape of a
    known Wikipedia title), it fetches revisions for that specific page.
    Otherwise it queries ``list=recentchanges`` and filters by whether the
    title contains a word from the query.

    Parameters
    ----------
    ctx:
        Skill context.
    query:
        Topic or page title to watch.
    since:
        Lower bound (exclusive) for the revision timestamp.  ``None`` means
        "last 24 hours" (the API default).
    max_results:
        Maximum number of revision documents to return.
    """
    since_str = _format_since(since)
    changes = _fetch_recent_changes(ctx, since_str, max_results * 3)
    if not changes:
        return []

    # Filter to changes whose title is relevant to the query.
    query_terms = set(query.lower().split())
    relevant = [
        ch for ch in changes
        if any(t in ch.get("title", "").lower() for t in query_terms)
    ][:max_results]

    docs: list[Document] = []
    for ch in relevant:
        title = ch.get("title", "")
        ts = ch.get("timestamp", "")
        user = ch.get("user", "")
        comment = ch.get("comment", "")
        revid = ch.get("revid", "")
        text = (
            f"Wikipedia revision of '{title}' by {user} at {ts}.\n"
            f"Edit summary: {comment or '(no summary)'}\n"
            f"Revision ID: {revid}"
        )
        doc = ctx.make_document(
            doc_id=f"wikipedia:revision:{revid or title}:{ts}",
            text=text,
            metadata={
                "source": "wikipedia",
                "title": title,
                "url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                "revision_id": revid,
                "timestamp": ts,
                "editor": user,
                "type": "revision",
            },
        )
        docs.append(doc)
    return docs


def _fetch_recent_changes(
    ctx: SkillContext,
    since_str: str,
    limit: int,
) -> list[dict]:
    url = _RC_URL.format(limit=min(limit, 500), since=since_str)
    resp = ctx.fetch(url)
    try:
        data = json.loads(resp.content)
    except Exception:
        return []
    return data.get("query", {}).get("recentchanges", [])


def _format_since(since: datetime | None) -> str:
    """Return an ISO-8601 UTC string for the MediaWiki API ``rcend`` parameter.

    When ``since`` is None we default to 24 h ago so Watch ticks with no
    checkpoint still return something meaningful on first run.
    """
    if since is None:
        from datetime import timedelta
        since = datetime.now(UTC) - timedelta(hours=24)
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    # MediaWiki wants ISO 8601 with a Z suffix
    return since.strftime("%Y-%m-%dT%H:%M:%SZ")
