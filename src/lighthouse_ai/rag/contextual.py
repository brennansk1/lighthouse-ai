"""Anthropic contextual retrieval helper (design §14.3).

Each chunk gets a 50-100 token preamble that names the source, grade, date,
and stakes. The preamble is prepended *before* both embedding and BM25
indexing so retrieval matches on the contextual frame as well as the body.

In production an aux_context model (Qwen3-8B / Llama-3.2-3B) drafts the
preamble per Anthropic's pattern. Here we provide:

  * :func:`prepend_context` — accepts a callable that produces the preamble
    (callers wire the Gateway in production; tests pass a lambda).
  * :func:`default_preamble` — deterministic preamble from chunk metadata,
    used when no model is available.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .chunker import Chunk

PreambleFn = Callable[[Chunk], str]


def default_preamble(chunk: Chunk) -> str:
    m = chunk.metadata
    parts = []
    if "source" in m:
        parts.append(f"Source: {m['source']}")
    if "grade" in m:
        parts.append(f"grade {m['grade']}")
    if "published_date" in m:
        parts.append(f"published {m['published_date']}")
    if m.get("stakes"):
        parts.append(f"stakes: {m['stakes']}")
    if not parts:
        return ""
    return "[" + "; ".join(parts) + "] "


def prepend_context(chunks: Iterable[Chunk], *,
                    preamble_fn: PreambleFn = default_preamble) -> list[Chunk]:
    """Return new Chunk objects with the preamble prepended to each text."""
    from dataclasses import replace
    out: list[Chunk] = []
    for c in chunks:
        preamble = preamble_fn(c)
        if not preamble:
            out.append(c)
            continue
        out.append(replace(c, text=preamble + c.text))
    return out
