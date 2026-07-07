"""expand_query — generate query variants for broader coverage.

Produces semantically related query strings by searching with the original
query and extracting terminology from the top snippets, then returning a list
of expanded query strings the planner can use for follow-up searches.

This is a lightweight in-process expansion (no LLM call) based on:
1. The original query as-is
2. Common reformulations (quoted phrases, site: operators stripped)
3. Synonym hints extracted from result titles

The planner orchestrates follow-up calls; this tool just returns strings.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import lighthouse_ai.sources.searxng as _searxng
from lighthouse_ai.sources.searxng import SearXNGUnavailable

if TYPE_CHECKING:
    from lighthouse_ai.skills.capabilities import SkillContext


def expand_query(
    ctx: SkillContext,
    query: str,
    *,
    max_variants: int = 5,
) -> list[str]:
    """Generate query variants for broader corpus coverage.

    Searches with the original query, extracts terminology from the top result
    titles, and returns a deduplicated list of query strings the planner can
    use as inputs to search_web or search_news for additional coverage.

    Does NOT perform the follow-up searches itself; that is the planner's job.

    Args:
        ctx: The SkillContext (unused here, kept for consistent tool signature).
        query: The seed query to expand.
        max_variants: Maximum number of expanded query strings to return.

    Returns:
        List of query strings including the original as the first entry.
    """
    variants: list[str] = [query]

    # Try to extract top-result titles to surface related terminology.
    try:
        results = _searxng.search(query, max_results=5, categories="general")
    except SearXNGUnavailable:
        return variants[:max_variants]

    # Extract multi-word noun phrases from titles as expansion hints.
    seen: set[str] = {query.lower()}
    for result in results:
        title_words = re.findall(r"\b[A-Za-z][a-z]{3,}\b", result.title or "")
        # Build 2-word bigrams as focused sub-queries.
        for i in range(len(title_words) - 1):
            bigram = f"{title_words[i]} {title_words[i + 1]}"
            if bigram.lower() not in seen:
                candidate = f"{query} {bigram}"
                variants.append(candidate)
                seen.add(bigram.lower())
            if len(variants) >= max_variants:
                break
        if len(variants) >= max_variants:
            break

    return variants[:max_variants]
