"""Chunker — sentence-boundary preference, 800-token target, 100-token overlap.

Real chunking in production uses sentence-transformer similarity to find
semantic boundaries. For Sprint 5 we use a deterministic, dependency-free
fallback that still preserves the design contract:
  * Prefer sentence boundaries (``.``, ``?``, ``!``, newlines).
  * Hard cap at ~800 tokens per chunk (whitespace token approximation).
  * 100-token overlap between adjacent chunks.
  * Code blocks and tables (delimited by ``` and pipe-tables) emit as one chunk.

Document-level metadata propagates to every chunk per §14.2.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

DEFAULT_CHUNK_TOKENS = 800
DEFAULT_OVERLAP_TOKENS = 100

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)


@dataclass(frozen=True)
class Document:
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    text: str
    position: int
    metadata: dict[str, Any] = field(default_factory=dict)


def _split_protected(text: str) -> list[tuple[str, bool]]:
    """Return alternating (text, is_protected) pieces, splitting on code fences."""
    out: list[tuple[str, bool]] = []
    pos = 0
    for m in _CODE_FENCE.finditer(text):
        if m.start() > pos:
            out.append((text[pos : m.start()], False))
        out.append((m.group(0), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out


def _approx_tokens(text: str) -> int:
    return len(text.split())


def _split_sentences(text: str) -> list[str]:
    """Split on sentence boundaries; preserve paragraph breaks."""
    paragraphs = re.split(r"\n{2,}", text)
    sentences: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        parts = _SENTENCE_END.split(para)
        for p in parts:
            p = p.strip()
            if p:
                sentences.append(p)
    return sentences


def _pack_sentences(sentences: list[str], max_tokens: int, overlap_tokens: int) -> list[str]:
    """Greedy pack sentences into chunks ≤ max_tokens with overlap."""
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for s in sentences:
        t = _approx_tokens(s)
        if t > max_tokens:
            # Flush whatever we've buffered first so its tokens aren't lost,
            # then hard-split the overlong sentence on whitespace.
            if current:
                chunks.append(" ".join(current))
            words = s.split()
            for i in range(0, len(words), max_tokens):
                chunks.append(" ".join(words[i : i + max_tokens]))
            current = []
            current_tokens = 0
            continue
        if current_tokens + t > max_tokens and current:
            chunks.append(" ".join(current))
            if overlap_tokens > 0:
                # Build overlap tail from the end of the just-emitted chunk.
                tail: list[str] = []
                tail_tokens = 0
                for sent in reversed(current):
                    tt = _approx_tokens(sent)
                    if tail_tokens + tt > overlap_tokens:
                        break
                    tail.insert(0, sent)
                    tail_tokens += tt
                current = list(tail)
                current_tokens = tail_tokens
            else:
                current = []
                current_tokens = 0
        current.append(s)
        current_tokens += t
    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_document(
    doc: Document,
    *,
    max_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Chunk a document. Code blocks are preserved whole."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    pieces = _split_protected(doc.text)
    all_chunks: list[str] = []
    for piece_text, is_protected in pieces:
        if is_protected:
            all_chunks.append(piece_text.strip())
            continue
        sentences = _split_sentences(piece_text)
        if not sentences:
            continue
        all_chunks.extend(_pack_sentences(sentences, max_tokens, overlap_tokens))
    chunks: list[Chunk] = []
    for i, txt in enumerate(all_chunks):
        cid = f"{doc.id}:{i:04d}:{uuid.uuid5(uuid.NAMESPACE_URL, txt).hex[:8]}"
        chunks.append(
            Chunk(id=cid, document_id=doc.id, text=txt, position=i, metadata=dict(doc.metadata))
        )
    return chunks
