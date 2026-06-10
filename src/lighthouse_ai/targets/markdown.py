"""Standalone Markdown landing — write a draft as one self-contained ``.md``
file with its full provenance manifest (FUTURE_FEATURES §7).

Unlike the Logseq target (which writes into a graph's ``pages/`` directory in
Logseq's block dialect), this produces a plain, portable Markdown document a
user can hand to anyone: title, the artifact body, and — when the run's PROV-O
sidecar is available — a Provenance section recording which models ran and
which sources were used, with the raw sidecar embedded in a fenced block so
the trail travels with the report.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .logseq import _html_to_blocks


def _provenance_section(sidecar: dict[str, Any]) -> list[str]:
    """Summarize the PROV-O sidecar (build_run_sidecar shape), then embed it."""
    lines: list[str] = ["", "## Provenance", ""]
    agents = sidecar.get("agents") or []
    models = [a.get("prov:label") or a.get("@id", "") for a in agents
              if isinstance(a, dict)]
    if models:
        lines.append(f"Models: {', '.join(m for m in models if m)}.")
    n_sources = sidecar.get("lighthouse:sourceCount")
    if n_sources:
        lines.append(f"Source slots recorded: {n_sources}.")
    activity = sidecar.get("activity") or {}
    if isinstance(activity, dict):
        started = activity.get("prov:startedAtTime")
        if started:
            lines.append(f"Run started: {started}.")
    content_hash = sidecar.get("lighthouse:contentHash")
    if content_hash:
        lines.append(f"Content hash: `{content_hash}`.")
    lines += ["", "The complete W3C PROV-O manifest for this run:", "",
              "```json",
              json.dumps(sidecar, sort_keys=True, indent=2),
              "```"]
    return lines


def export_markdown(out_path: str | Path, *, draft_id: str, title: str,
                    body_html: str, topic: str = "",
                    wep_phrase: str | None = None, source_count: int = 0,
                    provenance: dict[str, Any] | None = None) -> Path:
    """Write the draft as a standalone Markdown document. Returns the path.

    ``provenance`` is the loaded ``<draft_id>.prov.json`` sidecar when the
    caller has one; ``None`` simply omits the Provenance section (the export
    must not fail because a sidecar is missing — older drafts predate it).
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [f"# {title}", ""]
    meta: list[str] = []
    if topic and topic != title:
        meta.append(f"Topic: {topic}")
    if wep_phrase:
        meta.append(f"Confidence: {wep_phrase}")
    meta.append(f"Sources cited: {source_count}")
    meta.append(f"Draft: {draft_id} · exported "
                f"{datetime.now(UTC).date().isoformat()} by Lighthouse")
    lines += [" · ".join(meta), ""]
    lines += _html_to_blocks(body_html)
    if provenance is not None:
        lines += _provenance_section(provenance)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
