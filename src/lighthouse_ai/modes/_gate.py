"""Shared host-courtesy gate helper used by the mode engines.

Every engine that makes LLM calls wraps each call in ``gate_ctx(gate)`` so a
paused SchedulerGate can throttle the work without the engine knowing the
details. When no gate is wired (offline / deterministic runs) it is a no-op.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING, TypeVar

from ..governor.scheduler_gate import SchedulerGate

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..gateway import Gateway

T = TypeVar("T")


def gate_ctx(gate: SchedulerGate | None):
    """Host-courtesy permit around an LLM call; no-op when no gate is wired."""
    return gate.permit() if gate is not None else nullcontext()


def complete_structured_or(
    gateway: Gateway,
    prompt: str,
    *,
    parse: Callable[[str], T | None],
    fallback: Callable[[], T],
    gate: SchedulerGate | None = None,
    job_id: str | None = None,
) -> T:
    """Gate-wrapped ``complete_structured`` call with a deterministic fallback.

    The shared scaffolding behind the engines' LLM-or-stub calls: take a gate
    permit, call the model, hand the reply text to *parse*. The *fallback*
    runs when the call or the parser raises, or when *parse* returns ``None``
    (its "unusable reply" signal) — a transient model failure degrades to the
    mode's offline heuristic, never to a crash. ``None`` is the only fallback
    sentinel: falsy-but-meaningful parses (``""``, ``0.0``) are returned as-is.
    """
    try:
        with gate_ctx(gate):
            resp = gateway.complete_structured(prompt, job_id=job_id)
        parsed = parse(resp.text)
    except Exception:
        return fallback()
    return fallback() if parsed is None else parsed
