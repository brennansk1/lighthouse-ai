"""Archivist — clean → compose → append (OpenHuman §8).

A deliberately *dumb* bridge from a finished job to the durable corpus: it does
not entangle "how we record" with "how we summarise". The bridge is dumb; the
downstream tree (chunking, embedding, dossiers) is smart.

    clean_turns()    drop tool-call noise + non-content turns
    compose_md()     one markdown blob, "## role\\n<content>" per turn
    archive_report() finished report → clean markdown artifact in corpus (+Logseq)

Artifacts are content-addressed (sha256 of the composed markdown), so archiving
the same job twice writes the same file — idempotent by construction.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "ArchiveOutcome",
    "archive_conversation",
    "archive_report",
    "clean_turns",
    "compose_md",
    "report_to_markdown",
]

# Roles that are recording scaffolding, not durable content.
_DROP_ROLES = {"tool", "system"}
# Fenced tool/function-call JSON blocks emitted into assistant turns.
_TOOL_FENCE_RE = re.compile(
    r"```(?:json|tool|tool_call)?\s*\{[^`]*?\"(?:tool|function|tool_call)\"[^`]*?\}\s*```",
    re.IGNORECASE | re.DOTALL,
)


@runtime_checkable
class _TurnLike(Protocol):
    @property
    def role(self) -> str: ...
    @property
    def text(self) -> str: ...


@dataclass(frozen=True)
class ArchiveOutcome:
    markdown: str
    content_id: str  # idempotency key (sha256 prefix of the markdown)
    corpus_path: Path | None = None
    logseq_path: Path | None = None


@dataclass(frozen=True)
class _CleanTurn:
    role: str
    text: str


def _strip_tool_noise(text: str) -> str:
    return _TOOL_FENCE_RE.sub("", text).strip()


def clean_turns(turns: list[Any]) -> list[_TurnLike]:
    """Drop tool/system turns and strip tool-call JSON; pure transform.

    Turns are duck-typed on ``.role`` + ``.text`` so this works with QUC ``Turn``
    or any future turn type. Turns left empty after cleaning are dropped.
    """
    out: list[_TurnLike] = []
    for t in turns:
        if str(t.role).lower() in _DROP_ROLES:
            continue
        cleaned = _strip_tool_noise(t.text)
        if not cleaned:
            continue
        out.append(_CleanTurn(role=str(t.role), text=cleaned))
    return out


def compose_md(turns: list[Any]) -> str:
    """One markdown blob: ``## role`` then content, per turn (deterministic)."""
    blocks = [f"## {t.role}\n{t.text}".rstrip() for t in turns]
    return "\n\n".join(blocks).strip()


def report_to_markdown(report: Any, *, title: str | None = None) -> str:
    """Render a DraftReport-shaped object to a clean markdown artifact.

    Duck-typed: needs ``.question`` and ``.sections`` (each ``.title`` + ``.body``).
    """
    head = title or getattr(report, "question", "Research report")
    lines = [f"# {head}", ""]
    for section in getattr(report, "sections", []):
        sec_title = getattr(section, "title", "")
        body = (getattr(section, "body", "") or "").strip()
        if sec_title:
            lines.append(f"## {sec_title}")
        if body:
            lines.append(body)
        lines.append("")
    open_qs = getattr(report, "open_questions", None)
    if open_qs:
        lines.append("## Open questions")
        lines.extend(f"- {q}" for q in open_qs)
    return "\n".join(lines).strip() + "\n"


def _content_id(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()[:16]


def _slugify(text: str, *, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_len].rstrip("-")) or "untitled"


def archive_report(
    report: Any,
    *,
    corpus_dir: Path,
    logseq_dir: Path | None = None,
    title: str | None = None,
) -> ArchiveOutcome:
    """Compose a finished report into a clean markdown artifact in the corpus.

    Content-addressed → idempotent: the same report yields the same file path
    and content. Optionally also writes a Logseq page via the existing exporter.
    """
    markdown = report_to_markdown(report, title=title)
    cid = _content_id(markdown)
    head: str = title or str(getattr(report, "question", "report") or "report")

    corpus_dir = Path(corpus_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = corpus_dir / f"{_slugify(head)}-{cid}.md"
    corpus_path.write_text(markdown)

    logseq_path: Path | None = None
    if logseq_dir is not None:
        from ..targets.logseq import export_draft

        body_html = "".join(f"<p>{line}</p>" for line in markdown.splitlines() if line)
        page = export_draft(
            Path(logseq_dir),
            draft_id=cid,
            title=str(head),
            body_html=body_html,
            source_count=0,
            tags=["lighthouse", "archive"],
        )
        logseq_path = page.path

    return ArchiveOutcome(
        markdown=markdown, content_id=cid, corpus_path=corpus_path, logseq_path=logseq_path
    )


def archive_conversation(
    turns: list[Any],
    *,
    corpus_dir: Path,
    title: str,
) -> ArchiveOutcome:
    """Archive a finished conversation: clean → compose → append to corpus."""
    markdown = compose_md(clean_turns(turns))
    full = f"# {title}\n\n{markdown}\n"
    cid = _content_id(full)
    corpus_dir = Path(corpus_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = corpus_dir / f"{_slugify(title)}-{cid}.md"
    corpus_path.write_text(full)
    return ArchiveOutcome(markdown=full, content_id=cid, corpus_path=corpus_path)
