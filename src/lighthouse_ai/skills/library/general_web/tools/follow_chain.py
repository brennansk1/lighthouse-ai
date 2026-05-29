"""follow_chain — follow a chain of URLs depth-first.

Given a seed URL, fetches it and extracts any hrefs in the resulting Document
text (or metadata), then optionally fetches those linked pages too.  Useful
for following citation chains, news article "related stories" links, or
walking a multi-page FAQ.

Egress policy is still enforced on every hop: only allowlisted hosts are
reachable.  The skill cannot widen the egress ceiling regardless of what URLs
appear in the fetched content.

The chain is bounded by ``max_depth`` and ``max_pages`` to prevent runaway
crawls.  Each fetched page passes through the SandboxBroker; rejected pages
are skipped rather than raising.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lighthouse_ai.rag.chunker import Document
    from lighthouse_ai.skills.capabilities import SkillContext

# Minimal href extractor — no HTML parser dependency (import guard forbids
# anything that might smuggle socket/subprocess).
_HREF_RE = re.compile(r'href=["\']?(https?://[^\s"\'<>]+)', re.IGNORECASE)


def follow_chain(
    ctx: SkillContext,
    seed_url: str,
    *,
    max_depth: int = 2,
    max_pages: int = 5,
) -> list[Document]:
    """Follow a URL chain and return broker-admitted Documents for each hop.

    Fetches ``seed_url``, extracts ``href`` links from the raw response content,
    and follows up to ``max_depth - 1`` hops from the seed.  Pages rejected by
    the broker or blocked by egress policy are silently skipped so the chain
    degrades gracefully.

    Args:
        ctx: The SkillContext passed to the skill entrypoint.
        seed_url: Starting URL for the chain.
        max_depth: Maximum hop depth (1 = seed only, 2 = seed + its links, …).
        max_pages: Hard cap on total pages fetched across all depths.

    Returns:
        List of Documents, one per successfully fetched-and-admitted page.
        Empty if the seed is egress-blocked or broker-rejected.
    """
    visited: set[str] = set()
    docs: list[Document] = []

    def _fetch(url: str, depth: int) -> None:
        if url in visited or len(docs) >= max_pages or depth > max_depth:
            return
        visited.add(url)

        try:
            resp = ctx.fetch(url)
        except Exception:
            # EgressBlocked or any transport error — skip this URL.
            return

        # Pass through broker + ingest.
        ct = resp.headers.get("content-type") if hasattr(resp, "headers") else None
        doc = None
        try:
            doc = ctx.document_from_bytes(
                resp.content,
                url=url,
                content_type=ct,
                extra_meta={"chain_depth": depth, "seed": seed_url},
            )
        except Exception:
            return

        if doc is not None:
            docs.append(doc)

        # Extract links from the raw bytes for the next hop.
        if depth < max_depth:
            try:
                raw_text = resp.content.decode("utf-8", errors="replace")
            except Exception:
                return
            for href_match in _HREF_RE.finditer(raw_text):
                next_url = href_match.group(1)
                if len(docs) >= max_pages:
                    break
                _fetch(next_url, depth + 1)

    _fetch(seed_url, 1)
    return docs
