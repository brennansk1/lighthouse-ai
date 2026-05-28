"""Logseq landing — write an approved draft as a Logseq-compatible markdown
page on the filesystem (design §16).

We use the *filesystem* path (write ``pages/<title>.md`` into the graph dir)
rather than the HTTP API, so it works with zero setup — no running Logseq,
no API token. Logseq picks up the file on its next scan. Idempotent: a
stable ``id::`` block property derived from the draft id means re-exporting
updates the same page instead of duplicating it.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path


def _slugify(title: str) -> str:
    s = re.sub(r"[^\w\s-]", "", title).strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    return s[:80] or "untitled"


def _block_uuid(draft_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"lighthouse:draft:{draft_id}"))


@dataclass(frozen=True)
class LogseqPage:
    path: Path
    title: str
    uuid: str


def _html_to_blocks(body_html: str) -> list[str]:
    """Very small HTML→markdown-block conversion for our own draft HTML."""
    text = body_html
    # Drop <style>/<script>/<head> blocks and their contents entirely.
    text = re.sub(r"<(style|script|head)[^>]*>.*?</\1>", "", text, flags=re.S | re.I)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1", text, flags=re.S)
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1", text, flags=re.S)
    text = re.sub(r"</?(ul|section|div)[^>]*>", "", text, flags=re.S)
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)            # strip remaining tags
    blocks = [b.strip() for b in text.splitlines() if b.strip()]
    return blocks


def export_draft(graph_dir: Path, *, draft_id: str, title: str, body_html: str,
                 topic: str = "", wep_phrase: str | None = None,
                 source_count: int = 0, tags: list[str] | None = None) -> LogseqPage:
    """Write/overwrite a Logseq page for the draft. Returns the page handle."""
    pages_dir = Path(graph_dir) / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_path = pages_dir / f"{_slugify(title)}.md"
    block_uuid = _block_uuid(draft_id)

    lines = [
        f"title:: {title}",
        f"id:: {block_uuid}",
        f"type:: lighthouse-draft",
        f"lighthouse-draft-id:: {draft_id}",
    ]
    if topic:
        lines.append(f"topic:: {topic}")
    if wep_phrase:
        lines.append(f"confidence:: {wep_phrase}")
    if source_count:
        lines.append(f"sources:: {source_count}")
    tag_str = " ".join(f"#{t}" for t in (tags or ["lighthouse"]))
    lines.append("")
    lines.append(f"- # {title} {tag_str}")
    for block in _html_to_blocks(body_html):
        # nest content blocks under the heading block
        lines.append(f"  - {block}")
    page_path.write_text("\n".join(lines) + "\n")
    return LogseqPage(path=page_path, title=title, uuid=block_uuid)
