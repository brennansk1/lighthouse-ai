"""Shared host-courtesy gate helper used by the mode engines.

Every engine that makes LLM calls wraps each call in ``gate_ctx(gate)`` so a
paused SchedulerGate can throttle the work without the engine knowing the
details. When no gate is wired (offline / deterministic runs) it is a no-op.
"""

from __future__ import annotations

from contextlib import nullcontext

from ..governor.scheduler_gate import SchedulerGate


def gate_ctx(gate: SchedulerGate | None):
    """Host-courtesy permit around an LLM call; no-op when no gate is wired."""
    return gate.permit() if gate is not None else nullcontext()
