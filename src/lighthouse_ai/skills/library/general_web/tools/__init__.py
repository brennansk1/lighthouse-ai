"""General Web tool implementations — each composes SkillContext + SearXNG.

No tool imports httpx/requests/urllib/socket/subprocess.  All outbound I/O
goes through ctx primitives or the vetted lighthouse_ai.sources.searxng module.
"""

from .expand_query import expand_query
from .fetch_url import fetch_url
from .fetch_url_js import fetch_url_js
from .follow_chain import follow_chain
from .search_images import search_images
from .search_news import search_news
from .search_scholar import search_scholar
from .search_videos import search_videos
from .search_web import search_web

__all__ = [
    "expand_query",
    "fetch_url",
    "fetch_url_js",
    "follow_chain",
    "search_images",
    "search_news",
    "search_scholar",
    "search_videos",
    "search_web",
]
