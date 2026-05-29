"""Logseq landing — write an approved draft as a Logseq-compatible markdown
page on the filesystem (design §16).

We use the *filesystem* path (write ``pages/<title>.md`` into the graph dir)
rather than the HTTP API, so it works with zero setup — no running Logseq,
no API token. Logseq picks up the file on its next scan. Idempotent: a
stable ``id::`` block property derived from the draft id means re-exporting
updates the same page instead of duplicating it.

Structured rendering
--------------------
Drafts carry both a flattened ``body_html`` and (for the seven typed modes) a
structured ``body_json`` plus an ``artifact_type``. When the structured payload
is present we render *idiomatic* Logseq markdown per type — markdown tables for
matrix/table artifacts, dated bullet blocks with ``date::`` / ``sources::``
block properties for timelines, nested perspective blocks for verdicts, Q/A
turn blocks for transcripts, section blocks with per-claim citations for
reports, and salience-tagged item bullets for digests. When ``body_json`` is
absent (or the type is unknown) we fall back to flattening ``body_html`` into
generic blocks, preserving the original behaviour.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


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


# ── HTML fallback ───────────────────────────────────────────────────────────

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


# ── markdown helpers ─────────────────────────────────────────────────────────

def _md_cell(value: Any) -> str:
    """Escape a value for use inside a markdown table cell.

    Pipes break Logseq tables, newlines break the row; both are neutralised.
    """
    s = "" if value is None else str(value)
    return s.replace("\n", " ").replace("|", "\\|").strip()


def _md_table(headers: list[str], rows: Iterable[Iterable[Any]]) -> list[str]:
    """Render a GitHub/Logseq-flavoured markdown table as a list of lines."""
    lines = ["| " + " | ".join(_md_cell(h) for h in headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(c) for c in row) + " |")
    return lines


def _nested(lines: list[str], depth: int, text: str) -> None:
    """Append a Logseq bullet at the given nesting depth (2 spaces per level)."""
    indent = "  " * depth
    lines.append(f"{indent}- {text}")


def _prop(lines: list[str], depth: int, key: str, value: Any) -> None:
    """Append a Logseq block property line under the current block.

    Block properties are continuation lines (no leading ``-``) indented one
    level deeper than the bullet they annotate.
    """
    indent = "  " * (depth + 1)
    lines.append(f"{indent}{key}:: {_md_cell(value)}")


# ── per-artifact-type renderers ──────────────────────────────────────────────
#
# Every renderer receives the structured ``body_json`` and returns the page's
# content blocks *below* the top heading (which the caller emits). Blocks are
# pre-indented Logseq lines; renderers nest under depth 1 (one level below the
# heading block at depth 0).

def _render_matrix(bj: dict) -> list[str]:
    """Decide → options × criteria table with totals, winner + crux blocks."""
    lines: list[str] = []
    options = [o.get("label", "") for o in bj.get("options", [])]
    criteria = bj.get("criteria", [])
    totals = bj.get("totals", {})
    # cells indexed by (option, criterion) → score
    cell_map: dict[tuple[str, str], Any] = {}
    for c in bj.get("cells", []):
        cell_map[(c.get("option"), c.get("criterion"))] = c.get("score")

    crit_labels = [c.get("label", "") for c in criteria]
    headers = ["Option", *[f"{lab} (w={c.get('weight')})"
                           for lab, c in zip(crit_labels, criteria, strict=False)],
               "Total"]
    rows = []
    for opt in options:
        row = [opt]
        for clab in crit_labels:
            row.append(cell_map.get((opt, clab), ""))
        row.append(totals.get(opt, ""))
        rows.append(row)
    _nested(lines, 1, "## Decision matrix")
    for tline in _md_table(headers, rows):
        _nested(lines, 2, tline)

    winner = bj.get("winner")
    if winner is not None:
        runner = bj.get("runner_up")
        margin = bj.get("margin")
        win_txt = f"**Winner:** {winner}"
        if runner:
            win_txt += f" (over {runner}, margin {margin})"
        _nested(lines, 1, win_txt)
    crux = bj.get("crux")
    if crux:
        _nested(lines, 1, f"**Crux:** {crux}")
    return lines


def _render_timeline(bj: dict) -> list[str]:
    """Reconstruct → chronological bullets with date:: / sources:: + certainty."""
    lines: list[str] = []
    events = bj.get("events", [])
    _nested(lines, 1, f"## Timeline ({len(events)} events)")
    for ev in events:
        actors = ", ".join(ev.get("actors", []) or [])
        head = ev.get("action", "") or "(event)"
        if actors:
            head = f"{head} — {actors}"
        _nested(lines, 2, head)
        _prop(lines, 2, "date", ev.get("date", ""))
        sources = ev.get("sources", []) or []
        if sources:
            _prop(lines, 2, "sources", ", ".join(str(s) for s in sources))
        _prop(lines, 2, "certainty", ev.get("certainty", ""))
        if ev.get("inferred"):
            _prop(lines, 2, "inferred", "true")
    return lines


def _render_verdict(bj: dict) -> list[str]:
    """Adjudicate → each perspective as a nested block + crux + judge summary."""
    lines: list[str] = []
    _nested(lines, 1, "## Perspectives")
    for r in bj.get("responses", []):
        persp = r.get("perspective", {})
        name = persp.get("name", "perspective")
        agrees = "agrees" if r.get("agrees") else "dissents"
        _nested(lines, 2, f"**{name}** ({agrees})")
        _nested(lines, 3, r.get("critique", ""))
    disputes = bj.get("disputes", []) or []
    crux = disputes[0] if disputes else "No unresolved dispute recorded."
    _nested(lines, 1, f"**Crux of disagreement:** {crux}")
    summary = bj.get("judge_summary")
    if summary:
        _nested(lines, 1, f"**Judge summary:** {summary}")
    return lines


def _render_table(bj: dict) -> list[str]:
    """Survey → rows × attributes evidence table + PRISMA counts."""
    lines: list[str] = []
    attributes = [a.get("label", "") for a in bj.get("attributes", [])]
    rows_in = bj.get("rows", [])
    headers = ["Document", *attributes]
    out_rows = []
    for row in rows_in:
        cell_by_attr = {c.get("attribute"): c.get("value", "") for c in row.get("cells", [])}
        out_rows.append([row.get("title") or row.get("doc_id", "")]
                        + [cell_by_attr.get(a, "") for a in attributes])
    _nested(lines, 1, "## Evidence table")
    for tline in _md_table(headers, out_rows):
        _nested(lines, 2, tline)

    prisma = bj.get("prisma", {})
    _nested(lines, 1, "## PRISMA flow")
    _nested(lines, 2, f"Identified: {prisma.get('identified', 0)}")
    _nested(lines, 2, f"Screened: {prisma.get('screened', 0)}")
    _nested(lines, 2, f"Included: {prisma.get('included', 0)}")
    _nested(lines, 2, f"Excluded: {prisma.get('excluded', 0)}")
    return lines


def _render_transcript(bj: dict) -> list[str]:
    """Ask → Q/A turn blocks; answers carry their citations."""
    lines: list[str] = []
    _nested(lines, 1, "## Transcript")
    for turn in bj.get("turns", []):
        role = str(turn.get("role", "")).title() or "Turn"
        _nested(lines, 2, f"**{role}:** {turn.get('text', '')}")
        citations = turn.get("citations", []) or []
        if citations:
            _prop(lines, 2, "citations", ", ".join(str(c) for c in citations))
    return lines


def _render_report(bj: dict) -> list[str]:
    """Investigate → section headings as blocks with per-section citations."""
    lines: list[str] = []
    for sec in bj.get("sections", []):
        _nested(lines, 1, f"## {sec.get('title', 'Section')}")
        body = sec.get("body", "")
        if body:
            _nested(lines, 2, body)
        citations = sec.get("citations", []) or []
        if citations:
            _prop(lines, 2, "sources", ", ".join(str(c) for c in citations))
    open_qs = bj.get("open_questions", []) or []
    if open_qs:
        _nested(lines, 1, "## Open questions")
        for q in open_qs:
            _nested(lines, 2, q)
    return lines


def _render_digest(bj: dict) -> list[str]:
    """Watch → item bullets with salience (alerts first, then digest)."""
    lines: list[str] = []
    alerts = bj.get("alerts", []) or []
    digest = bj.get("digest", []) or []

    def _item_line(ci: dict) -> tuple[str, float, str]:
        item = ci.get("item", {})
        label = item.get("title") or item.get("url") or "(item)"
        return str(label), float(ci.get("salience", 0.0)), str(ci.get("category", ""))

    if alerts:
        _nested(lines, 1, f"## Alerts ({len(alerts)})")
        for ci in alerts:
            label, sal, cat = _item_line(ci)
            _nested(lines, 2, f"{label} — salience {sal:.2f} ({cat})")
    _nested(lines, 1, f"## Digest ({len(digest)})")
    for ci in digest:
        label, sal, cat = _item_line(ci)
        _nested(lines, 2, f"{label} — salience {sal:.2f} ({cat})")
    if not alerts and not digest:
        _nested(lines, 2, "No items in this cycle.")
    return lines


_RENDERERS = {
    "matrix": _render_matrix,
    "timeline": _render_timeline,
    "verdict": _render_verdict,
    "table": _render_table,
    "transcript": _render_transcript,
    "report": _render_report,
    "digest": _render_digest,
}


def _render_body(artifact_type: str | None, body_json: dict | None,
                 body_html: str) -> list[str]:
    """Render the page's content blocks (below the heading).

    Dispatches to the typed renderer when a structured ``body_json`` and a
    recognised ``artifact_type`` are present; otherwise falls back to flattening
    ``body_html`` into generic nested blocks.
    """
    renderer = _RENDERERS.get(artifact_type or "")
    if renderer is not None and isinstance(body_json, dict):
        try:
            blocks = renderer(body_json)
            if blocks:
                return blocks
        except Exception:
            # Never let a malformed payload break the export — fall back.
            pass
    return [f"  - {block}" for block in _html_to_blocks(body_html)]


def export_draft(graph_dir: Path, *, draft_id: str, title: str, body_html: str,
                 topic: str = "", wep_phrase: str | None = None,
                 source_count: int = 0, tags: list[str] | None = None,
                 body_json: dict | None = None,
                 artifact_type: str | None = None) -> LogseqPage:
    """Write/overwrite a Logseq page for the draft. Returns the page handle.

    ``body_json`` + ``artifact_type`` are optional: when supplied (and the type
    is one of the seven typed artifacts) the page is rendered with idiomatic,
    type-specific Logseq markdown. When omitted, ``body_html`` is flattened into
    generic blocks (backward-compatible with existing callers).

    The page is idempotent: a stable ``id::`` block-uuid derived from
    ``draft_id`` means a re-export overwrites the same file in place rather than
    creating a duplicate page.
    """
    pages_dir = Path(graph_dir) / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_path = pages_dir / f"{_slugify(title)}.md"
    block_uuid = _block_uuid(draft_id)

    # Page-level properties live at the very top of the file (before any block).
    tag_list = list(tags) if tags else []
    if "lighthouse" not in tag_list:
        tag_list = ["lighthouse", *tag_list]
    tags_value = " ".join(f"#{t}" for t in tag_list)

    lines = [
        f"title:: {title}",
        f"id:: {block_uuid}",
        f"type:: {artifact_type or 'lighthouse-draft'}",
        f"created:: {date.today().isoformat()}",
        f"source-count:: {source_count}",
        f"tags:: {tags_value}",
        f"lighthouse-draft-id:: {draft_id}",
    ]
    if topic:
        lines.append(f"topic:: {topic}")
    if wep_phrase:
        lines.append(f"confidence:: {wep_phrase}")

    lines.append("")
    lines.append(f"- # {title} {tags_value}")
    lines.extend(_render_body(artifact_type, body_json, body_html))

    page_path.write_text("\n".join(lines) + "\n")
    return LogseqPage(path=page_path, title=title, uuid=block_uuid)
