"""Logseq landing — write an approved draft as a Logseq-compatible markdown page.

Uses the filesystem path (write ``pages/<title>.md`` into the graph dir) rather
than the HTTP API — works with zero setup, no running Logseq instance required.
Logseq picks up the file on its next directory scan.

Page format follows Logseq's standard conventions:
- Page properties block at top (key:: value)
- Each research section becomes a top-level bullet block
- Topic and linked entities use [[Page Link]] syntax for graph connectivity
- Sources listed as reference blocks with bidirectional [[links]] and url:: property
- Namespace tags: lighthouse/draft, lighthouse/topic/<slug>
- related:: property for cross-referencing linked entities
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


def _convert_ol(inner: str) -> str:
    """Convert <ol> inner HTML to numbered Markdown list."""
    items = re.findall(r"<li[^>]*>(.*?)</li>", inner, flags=re.S)
    return "\n" + "\n".join(f"{i+1}. {item.strip()}" for i, item in enumerate(items))


def _html_to_md(html: str) -> str:
    """Convert draft HTML to clean Markdown suitable for Logseq blocks."""
    import html as html_lib

    text = html or ""
    # Remove entire style/script/head blocks
    text = re.sub(r"<(style|script|head)[^>]*>.*?</\1>", "", text, flags=re.S | re.I)
    # Headings
    text = re.sub(r"<h1[^>]*>(.*?)</h1>", r"\n# \1\n", text, flags=re.S)
    text = re.sub(r"<h2[^>]*>(.*?)</h2>", r"\n## \1\n", text, flags=re.S)
    text = re.sub(r"<h3[^>]*>(.*?)</h3>", r"\n### \1\n", text, flags=re.S)
    text = re.sub(r"<h4[^>]*>(.*?)</h4>", r"\n#### \1\n", text, flags=re.S)
    # Inline formatting
    text = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", text, flags=re.S)
    text = re.sub(r"<b[^>]*>(.*?)</b>", r"**\1**", text, flags=re.S)
    text = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", text, flags=re.S)
    text = re.sub(r"<i[^>]*>(.*?)</i>", r"*\1*", text, flags=re.S)
    text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.S)
    text = re.sub(r"<pre[^>]*>(.*?)</pre>", r"\n```\n\1\n```\n", text, flags=re.S)
    # Links — convert <a href="url">text</a> to [text](url)
    text = re.sub(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        r'[\2](\1)',
        text,
        flags=re.S,
    )
    # Blockquotes
    text = re.sub(
        r"<blockquote[^>]*>(.*?)</blockquote>",
        lambda m: "\n" + "\n".join(f"> {l}" for l in m.group(1).strip().splitlines()) + "\n",
        text,
        flags=re.S,
    )
    # Lists — ordered (must come before unordered to avoid eating <ol> tags)
    text = re.sub(
        r"<ol[^>]*>(.*?)</ol>",
        lambda m: _convert_ol(m.group(1)),
        text,
        flags=re.S,
    )
    # Lists — unordered
    text = re.sub(
        r"<ul[^>]*>(.*?)</ul>",
        lambda m: re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", m.group(1), flags=re.S),
        text,
        flags=re.S,
    )
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", text, flags=re.S)
    # Paragraphs and divs
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n", text, flags=re.S)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<hr\s*/?>", "\n---\n", text)
    text = re.sub(r"</?(div|section|article|main|aside)[^>]*>", "\n", text, flags=re.S | re.I)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities
    text = html_lib.unescape(text)
    # Collapse excess blank lines (max 2 in a row)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _source_title(s: dict) -> str:
    """Return a display title for a source dict, falling back to a truncated URL."""
    t = (s.get("title") or "").strip()
    if t:
        return t
    url = s.get("url", "")
    # Strip scheme + common prefixes for a readable slug
    clean = re.sub(r"^https?://(www\.)?", "", url)
    return clean[:60] or "Source"


def export_draft(
    graph_dir: Path,
    *,
    draft_id: str,
    title: str,
    body_html: str,
    topic: str = "",
    wep_phrase: str | None = None,
    source_count: int = 0,
    tags: list[str] | None = None,
    sources: list[dict] | None = None,
    mode: str = "",
    keywords: list[str] | None = None,
) -> LogseqPage:
    """Write/overwrite a Logseq page for the draft.

    Page structure:
    - Page properties (title, id, type, topic, confidence, date, tags, related)
    - One top-level block per research section, with content nested inside
    - References block at the bottom with [[linked]] source pages and url:: sub-properties

    Extra parameters:
    - sources: list of {"url": str, "title": str | None} dicts for source reference blocks
    - mode: research mode string ("deepdive", "monitor", etc.) added as research-mode property
    - keywords: entity/topic names added as related:: [[links]] for graph connectivity
    """
    from datetime import date as _date

    pages_dir = Path(graph_dir) / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_path = pages_dir / f"{_slugify(title)}.md"
    block_uuid = _block_uuid(draft_id)

    # ── Page properties block ──────────────────────────────────────────────
    props = [
        f"title:: {title}",
        f"id:: {block_uuid}",
        f"lighthouse-draft-id:: {draft_id}",
        f"type:: lighthouse/draft",
        f"date:: [[{_date.today().isoformat()}]]",
    ]
    if topic:
        props.append(f"topic:: [[{topic}]]")
    if mode:
        props.append(f"research-mode:: {mode}")
    if wep_phrase:
        props.append(f"confidence:: {wep_phrase}")
    if source_count:
        props.append(f"source-count:: {source_count}")
    if keywords:
        linked = ", ".join(f"[[{kw}]]" for kw in keywords if kw.strip())
        if linked:
            props.append(f"related:: {linked}")

    # tags:: uses Logseq's native tag system (shown as chips in the sidebar).
    # Add namespace tags: lighthouse/draft and lighthouse/topic/<slug> for graph queries.
    tag_list = list(tags) if tags else []
    base_tags = ["lighthouse", "lighthouse/draft"]
    if topic:
        base_tags.append(f"lighthouse/topic/{_slugify(topic)}")
    tag_list = base_tags + [t for t in tag_list if t not in ("lighthouse",)]
    props.append(f"tags:: {', '.join(tag_list)}")

    # ── Body ──────────────────────────────────────────────────────────────
    md_body = _html_to_md(body_html)

    blocks: list[str] = []
    if md_body:
        section_parts = re.split(r"(?m)^(## .+)$", md_body)
        if len(section_parts) <= 1:
            for line in md_body.splitlines():
                if line.strip():
                    blocks.append(f"- {line}")
        else:
            preamble = section_parts[0].strip()
            if preamble:
                for line in preamble.splitlines():
                    if line.strip():
                        blocks.append(f"- {line}")
            for i in range(1, len(section_parts), 2):
                heading = section_parts[i].strip()
                content = section_parts[i + 1].strip() if i + 1 < len(section_parts) else ""
                section_heading = heading.lstrip("# ").strip()
                block_lines = [f"- ## {section_heading}"]
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped:
                        block_lines.append(f"  - {stripped}")
                blocks.append("\n".join(block_lines))

    # ── References block ───────────────────────────────────────────────────
    # Use rich source references when available, otherwise fall back to count.
    if sources:
        ref_lines = ["- ## References"]
        for s in sources:
            st = _source_title(s)
            url = s.get("url", "")
            # Each source gets a linked page name + url:: sub-property.
            # [[Source Title]] creates a bidirectional graph link.
            ref_lines.append(f"  - [[{st}]]")
            if url:
                ref_lines.append(f"    url:: {url}")
        blocks.append("\n".join(ref_lines))
    elif source_count:
        blocks.append(f"- **Sources reviewed:** {source_count} independent sources")

    # ── Assemble ──────────────────────────────────────────────────────────
    page_content = "\n".join(props) + "\n\n" + "\n".join(blocks) + "\n"
    page_path.write_text(page_content, encoding="utf-8")
    return LogseqPage(path=page_path, title=title, uuid=block_uuid)
