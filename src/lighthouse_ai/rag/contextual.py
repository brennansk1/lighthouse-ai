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
from contextlib import AbstractContextManager
from typing import Any, Protocol, runtime_checkable

from .chunker import Chunk


@runtime_checkable
class _HasPermit(Protocol):
    """Minimal protocol satisfied by SchedulerGate (and any context-manager gate)."""

    def permit(self) -> AbstractContextManager[Any]: ...

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


def llm_preamble_fn(
    gateway: Any,
    *,
    document_text: str = "",
    gate: _HasPermit | None = None,
) -> PreambleFn:
    """Return a PreambleFn that generates context using the aux_context LLM role.

    Falls back to default_preamble if the gateway call fails.
    The generated preamble is a 1-sentence context locator per Anthropic's
    Contextual Retrieval technique (anthropic.com/news/contextual-retrieval).

    ``gate`` (optional) is a :class:`~lighthouse_ai.governor.scheduler_gate.SchedulerGate`
    that is acquired around each LLM completion for host-courtesy throttling (§1).
    """
    from contextlib import nullcontext

    def _fn(chunk: Chunk) -> str:
        try:
            prompt = (
                f"Document excerpt:\n"
                f"{document_text[:2000] if document_text else chunk.text[:500]}\n\n"
                f"Chunk to contextualize:\n{chunk.text[:400]}\n\n"
                "In one sentence, describe what this chunk is about and how it fits "
                "within the larger document. Be specific about names, dates, and claims."
            )
            ctx = gate.permit() if gate is not None else nullcontext()
            with ctx:
                resp = gateway.complete("aux_context", prompt)
            preamble = resp.text.strip()[:200]
            if preamble:
                return f"[Context: {preamble}] "
        except Exception:
            pass
        return default_preamble(chunk)
    return _fn
